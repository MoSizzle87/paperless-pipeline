from __future__ import annotations

import fcntl

import pytest

from filethat.cli import _scan_lock


def test_concurrent_scan_exits_with_code_1(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    lock_path = data_dir / ".filethat.lock"

    with open(lock_path, "w") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)

        with pytest.raises(SystemExit) as exc_info:
            with _scan_lock(data_dir):
                pass

        assert exc_info.value.code == 1
