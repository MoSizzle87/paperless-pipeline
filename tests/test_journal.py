from __future__ import annotations

import csv
from pathlib import Path

import pytest

from filethat.journal import Journal, JournalEntry


def make_entry(
    hash_sha256: str = "abc123",
    status: str = "success",
    entry_id: str = "test0001",
) -> JournalEntry:
    return JournalEntry(
        id=entry_id,
        hash_sha256=hash_sha256,
        source_filename="test.pdf",
        source_size_bytes=1234,
        processed_at="2024-01-01T00:00:00+00:00",
        status=status,
    )


def test_new_journal_has_no_hashes(tmp_path):
    journal = Journal(tmp_path / "journal.csv")
    assert not journal.has_hash("abc123")


def test_append_registers_hash(tmp_path):
    journal = Journal(tmp_path / "journal.csv")
    journal.append(make_entry(hash_sha256="deadbeef"))
    assert journal.has_hash("deadbeef")


def test_csv_has_header_and_row(tmp_path):
    path = tmp_path / "journal.csv"
    journal = Journal(path)
    journal.append(make_entry(hash_sha256="abc001"))

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["hash_sha256"] == "abc001"
    assert rows[0]["status"] == "success"
    assert rows[0]["source_filename"] == "test.pdf"


def test_hash_stable_across_reload(tmp_path):
    path = tmp_path / "journal.csv"
    j1 = Journal(path)
    j1.append(make_entry(hash_sha256="persist1"))

    j2 = Journal(path)
    assert j2.has_hash("persist1")


def test_multiple_entries_all_loaded(tmp_path):
    path = tmp_path / "journal.csv"
    journal = Journal(path)
    for i in range(5):
        journal.append(make_entry(hash_sha256=f"hash{i:03d}", entry_id=f"id{i:06d}"))

    for i in range(5):
        assert journal.has_hash(f"hash{i:03d}")


def test_header_written_once(tmp_path):
    path = tmp_path / "journal.csv"
    journal = Journal(path)
    journal.append(make_entry(hash_sha256="h1", entry_id="id000001"))
    journal.append(make_entry(hash_sha256="h2", entry_id="id000002"))

    with open(path) as f:
        lines = f.readlines()

    # One header line + two data lines
    assert len(lines) == 3
    assert lines[0].startswith("id,")


def test_new_id_is_8_chars():
    for _ in range(10):
        assert len(Journal.new_id()) == 8


def test_error_entry_appended(tmp_path):
    path = tmp_path / "journal.csv"
    journal = Journal(path)
    entry = make_entry(hash_sha256="errhash", status="error")
    entry.error_stage = "classify"
    entry.error_message = "API timeout"
    journal.append(entry)

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert rows[0]["status"] == "error"
    assert rows[0]["error_stage"] == "classify"


def test_journal_creates_parent_dir(tmp_path):
    nested_path = tmp_path / "sub" / "dir" / "journal.csv"
    journal = Journal(nested_path)
    journal.append(make_entry(hash_sha256="nested1"))
    assert nested_path.exists()
