# Eval dataset

Evaluation dataset for measuring pipeline quality (§12). Documents in this directory
are intentionally excluded from git (see `.gitignore`); add them manually.

## Adding a document

1. Copy the anonymized PDF to `documents/`:
   ```
   tests/eval/documents/exemple_facture_edf.pdf
   ```

2. Add an entry to `golden.json`:
   ```json
   {
     "filename": "exemple_facture_edf.pdf",
     "expected": {
       "document_type": "invoice",
       "correspondent": "EDF",
       "document_date": "2025-10-15",
       "language": "fr"
     }
   }
   ```

**Required fields in `expected`:** `document_type`, `correspondent`.  
**Optional fields:** `document_date`, `language` — evaluated only when present.  
**Not evaluated:** `title` (too variable across runs).

## Running the eval

```sh
# Default provider (from config.yaml)
make eval

# Compare two providers
python -m filethat eval --providers anthropic,openai
```

Reports are written to `tests/eval/report_<timestamp>.md` (excluded from git).

## Document types

Use the exact keys from `config.yaml` → `referential.document_types`:
`identity`, `civil_status`, `legal`, `education`, `employment`, `payslip`,
`tax`, `banking`, `health`, `insurance`, `housing`, `vehicle`, `invoice`,
`admin`, `other`.
