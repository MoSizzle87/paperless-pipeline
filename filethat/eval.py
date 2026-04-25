from __future__ import annotations

import json
import logging
import shutil
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import tenacity

from filethat.classify import (
    ANTHROPIC_TOOL,
    OPENAI_TOOL,
    SYSTEM_PROMPT,
    ClassificationResult,
    _build_user_prompt,
    _is_transient,
)
from filethat.config import Config
from filethat.extract import extract_text
from filethat.normalize import normalize

logger = logging.getLogger(__name__)

# (input $/M tokens, output $/M tokens) — approximate, for reporting only
_COST_PER_M: dict[str, tuple[float, float]] = {
    "claude-opus-4-7": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
}

_PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
}


def _model_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    for prefix, (cin, cout) in _COST_PER_M.items():
        if model.startswith(prefix):
            return (input_tokens * cin + output_tokens * cout) / 1_000_000
    return 0.0


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class EvalDocumentResult:
    filename: str
    expected: dict
    predicted: ClassificationResult | None
    error: str | None
    duration_total: float
    duration_ocr: float
    duration_llm: float
    usage: _Usage = field(default_factory=_Usage)


# ---------------------------------------------------------------------------
# Metric functions
# ---------------------------------------------------------------------------


def _field_accuracy(results: list[EvalDocumentResult], fname: str) -> tuple[int, int]:
    """Return (correct, total) for documents that have ``fname`` in expected."""
    correct = total = 0
    for r in results:
        if r.predicted is None or fname not in r.expected:
            continue
        total += 1
        got = getattr(r.predicted, fname, None)
        if got is not None and str(got).lower() == str(r.expected[fname]).lower():
            correct += 1
    return correct, total


def _ece(results: list[EvalDocumentResult], n_bins: int = 10) -> float:
    """Expected Calibration Error computed on document_type correctness."""
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]
    for r in results:
        if r.predicted is None or "document_type" not in r.expected:
            continue
        conf = max(0.0, min(1.0, r.predicted.confidence))
        ok = r.predicted.document_type == r.expected["document_type"]
        buckets[min(int(conf * n_bins), n_bins - 1)].append((conf, ok))

    n = sum(len(b) for b in buckets)
    if n == 0:
        return 0.0
    return round(
        sum(
            len(b) / n * abs(sum(c for c, _ in b) / len(b) - sum(ok for _, ok in b) / len(b))
            for b in buckets
            if b
        ),
        4,
    )


def _confusion_matrix(
    results: list[EvalDocumentResult],
) -> tuple[list[str], dict[str, dict[str, int]]]:
    labels: set[str] = set()
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in results:
        if r.predicted is None or "document_type" not in r.expected:
            continue
        actual = r.expected["document_type"]
        pred = r.predicted.document_type
        labels.update([actual, pred])
        matrix[actual][pred] += 1
    return sorted(labels), {k: dict(v) for k, v in matrix.items()}


# ---------------------------------------------------------------------------
# Eval classifiers (capture token usage; no prompt caching)
# ---------------------------------------------------------------------------


class _AnthropicEvalClassifier:
    def classify_with_usage(self, text: str, config: Config) -> tuple[ClassificationResult, _Usage]:
        import anthropic

        client = anthropic.Anthropic()

        @tenacity.retry(
            retry=tenacity.retry_if_exception(_is_transient),
            wait=tenacity.wait_exponential(multiplier=1, min=2, max=30),
            stop=tenacity.stop_after_attempt(3),
            reraise=True,
        )
        def _call() -> tuple[ClassificationResult, _Usage]:
            resp = client.messages.create(
                model=config.llm.model,
                max_tokens=1024,
                temperature=config.llm.temperature,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _build_user_prompt(text, config)}],
                tools=[ANTHROPIC_TOOL],
                tool_choice={"type": "tool", "name": "classify_document"},
            )
            for block in resp.content:
                if block.type == "tool_use" and block.name == "classify_document":
                    result = ClassificationResult.model_validate(block.input)
                    u = resp.usage
                    return result, _Usage(
                        input_tokens=u.input_tokens,
                        output_tokens=u.output_tokens,
                        cost_usd=_model_cost(config.llm.model, u.input_tokens, u.output_tokens),
                    )
            raise ValueError("No classify_document tool_use block in response")

        return _call()


class _OpenAIEvalClassifier:
    def classify_with_usage(self, text: str, config: Config) -> tuple[ClassificationResult, _Usage]:
        import openai

        client = openai.OpenAI()

        @tenacity.retry(
            retry=tenacity.retry_if_exception(_is_transient),
            wait=tenacity.wait_exponential(multiplier=1, min=2, max=30),
            stop=tenacity.stop_after_attempt(3),
            reraise=True,
        )
        def _call() -> tuple[ClassificationResult, _Usage]:
            resp = client.chat.completions.create(
                model=config.llm.model,
                temperature=config.llm.temperature,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _build_user_prompt(text, config)},
                ],
                tools=[OPENAI_TOOL],
                tool_choice={"type": "function", "function": {"name": "classify_document"}},
            )
            data = json.loads(resp.choices[0].message.tool_calls[0].function.arguments)
            result = ClassificationResult.model_validate(data)
            u = resp.usage
            inp, out = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
            return result, _Usage(
                input_tokens=inp,
                output_tokens=out,
                cost_usd=_model_cost(config.llm.model, inp, out),
            )

        return _call()


def _get_eval_classifier(provider: str) -> _AnthropicEvalClassifier | _OpenAIEvalClassifier:
    if provider == "anthropic":
        return _AnthropicEvalClassifier()
    if provider == "openai":
        return _OpenAIEvalClassifier()
    raise ValueError(f"Unknown provider for eval: {provider!r}")


# ---------------------------------------------------------------------------
# Per-document sandbox runner
# ---------------------------------------------------------------------------


def _eval_document(
    doc_path: Path, expected: dict, config: Config, provider: str
) -> EvalDocumentResult:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / doc_path.name
        shutil.copy2(doc_path, src)
        t0 = time.monotonic()
        try:
            t_ocr = time.monotonic()
            ocr_pdf, _ = normalize(src, config, tmp_path)
            dur_ocr = time.monotonic() - t_ocr

            text = extract_text(ocr_pdf, config)

            t_llm = time.monotonic()
            predicted, usage = _get_eval_classifier(provider).classify_with_usage(text, config)
            dur_llm = time.monotonic() - t_llm

            return EvalDocumentResult(
                filename=doc_path.name,
                expected=expected,
                predicted=predicted,
                error=None,
                duration_total=time.monotonic() - t0,
                duration_ocr=dur_ocr,
                duration_llm=dur_llm,
                usage=usage,
            )
        except Exception as exc:
            logger.error("Eval failed for %s: %s", doc_path.name, exc)
            return EvalDocumentResult(
                filename=doc_path.name,
                expected=expected,
                predicted=None,
                error=str(exc),
                duration_total=time.monotonic() - t0,
                duration_ocr=0.0,
                duration_llm=0.0,
            )


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def _confusion_md(results: list[EvalDocumentResult]) -> str:
    labels, matrix = _confusion_matrix(results)
    if not labels:
        return ""
    w = max(len(lbl) for lbl in labels) + 2
    lines = [" " * w + "".join(lbl.ljust(w) for lbl in labels)]
    for actual in labels:
        lines.append(
            actual.ljust(w)
            + "".join(str(matrix.get(actual, {}).get(p, 0)).ljust(w) for p in labels)
        )
    return "### Confusion matrix (document_type)\n\n```\n" + "\n".join(lines) + "\n```\n"


def _provider_section(results: list[EvalDocumentResult], provider: str, model: str) -> str:
    parts = [f"## {provider} ({model})\n"]
    for fname, label in [
        ("document_type", "Document type accuracy"),
        ("correspondent", "Correspondent accuracy"),
        ("document_date", "Date extraction accuracy"),
        ("language", "Language accuracy"),
    ]:
        c, t = _field_accuracy(results, fname)
        if t:
            parts.append(f"{label}: {c}/{t} ({100.0 * c / t:.1f}%)")
    parts.append(f"Confidence ECE: {_ece(results):.4f}")
    valid = [r for r in results if r.predicted is not None]
    if valid:
        avg_cost = sum(r.usage.cost_usd for r in valid) / len(valid)
        avg_t = sum(r.duration_total for r in valid) / len(valid)
        avg_ocr = sum(r.duration_ocr for r in valid) / len(valid)
        avg_llm = sum(r.duration_llm for r in valid) / len(valid)
        parts.append(f"Avg cost per document: ${avg_cost:.4f}")
        parts.append(
            f"Avg processing time: {avg_t:.1f}s"
            f" (OCR: {avg_ocr:.1f}s, LLM: {avg_llm:.1f}s, other: {avg_t - avg_ocr - avg_llm:.1f}s)"
        )
    return "\n".join(parts)


def format_terminal_summary(
    reports: dict[str, list[EvalDocumentResult]], models: dict[str, str]
) -> str:
    lines: list[str] = []
    for provider, results in reports.items():
        if len(reports) > 1:
            lines.append(f"\n[{provider} / {models[provider]}]")
        for fname, label in [
            ("document_type", "Document type accuracy"),
            ("correspondent", "Correspondent accuracy"),
            ("document_date", "Date extraction accuracy"),
        ]:
            c, t = _field_accuracy(results, fname)
            if t:
                lines.append(f"{label}: {c}/{t} ({100.0 * c / t:.1f}%)")
        lines.append(f"Confidence ECE: {_ece(results):.2f}")
        valid = [r for r in results if r.predicted is not None]
        if valid:
            avg_cost = sum(r.usage.cost_usd for r in valid) / len(valid)
            avg_t = sum(r.duration_total for r in valid) / len(valid)
            lines.append(f"Avg cost per document: ${avg_cost:.4f}")
            lines.append(f"Avg processing time: {avg_t:.1f}s")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_eval(
    dataset_path: Path,
    providers: list[str],
    config: Config,
) -> tuple[dict[str, list[EvalDocumentResult]], dict[str, str]]:
    """Run the full eval pipeline in sandbox for each provider.

    Returns (reports, models) where reports maps provider → results and
    models maps provider → model name. Writes a Markdown report to dataset_path.
    Does NOT touch data/journal.csv or data/library/.
    """
    entries: list[dict] = json.loads((dataset_path / "golden.json").read_text())
    reports: dict[str, list[EvalDocumentResult]] = {}
    models: dict[str, str] = {}

    for provider in providers:
        model = (
            config.llm.model
            if provider == config.llm.provider
            else _PROVIDER_DEFAULT_MODELS.get(provider, config.llm.model)
        )
        pcfg = config.model_copy(
            update={
                "llm": config.llm.model_copy(
                    update={"provider": provider, "model": model, "prompt_caching": False}
                )
            }
        )
        models[provider] = model
        results: list[EvalDocumentResult] = []
        for entry in entries:
            doc_path = dataset_path / "documents" / entry["filename"]
            if not doc_path.exists():
                logger.warning("Skipping missing document: %s", entry["filename"])
                continue
            results.append(_eval_document(doc_path, entry["expected"], pcfg, provider))
            logger.info("Evaluated %s / %s", provider, entry["filename"])
        reports[provider] = results

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    report_path = dataset_path / f"report_{ts}.md"
    sections: list[str] = [
        f"# Filethat eval report\n\nGenerated: {datetime.now(timezone.utc).isoformat()}\n"
    ]
    for provider, results in reports.items():
        sections.append(_provider_section(results, provider, models[provider]))
        cm = _confusion_md(results)
        if cm:
            sections.append(cm)
    if len(reports) > 1:
        rows = []
        for provider, results in reports.items():
            cols = [
                f"{100.0 * c / t:.0f}%" if t else "n/a"
                for c, t in (
                    _field_accuracy(results, f)
                    for f in ("document_type", "correspondent", "document_date")
                )
            ]
            rows.append(f"| {provider} | {models[provider]} | {' | '.join(cols)} |")
        sections.append(
            "## Cross-provider comparison\n\n"
            "| Provider | Model | doc_type | correspondent | date |\n"
            "|----------|-------|----------|---------------|------|\n"
            + "\n".join(rows)
        )
    report_path.write_text("\n\n".join(sections))
    logger.info("Eval report written: %s", report_path)

    return reports, models
