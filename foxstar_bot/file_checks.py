from __future__ import annotations

import time
from pathlib import Path


def _file_size_stable(path: Path, samples: int = 2, interval: float = 0.6, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    stable_count = 0
    last_size = -1
    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size <= 0:
            stable_count = 0
        elif size == last_size:
            stable_count += 1
            if stable_count >= samples:
                return True
        else:
            stable_count = 0
        last_size = size
        time.sleep(interval)
    return False


def _file_format_complete(path: Path) -> bool:
    try:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            size = path.stat().st_size
            with path.open("rb") as handle:
                handle.seek(max(0, size - 2048))
                tail = handle.read()
            return b"%%EOF" in tail
        if suffix == ".docx":
            import zipfile

            return zipfile.ZipFile(str(path)).testzip() is None
    except Exception:
        return False
    return True
