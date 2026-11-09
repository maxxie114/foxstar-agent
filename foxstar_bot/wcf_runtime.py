from __future__ import annotations

import logging
import os
import shutil
import filecmp
from pathlib import Path


LOG = logging.getLogger(__name__)


def ensure_windows_local_wcf_binaries() -> None:
    if os.name != "nt":
        return

    try:
        import wcferry
    except Exception:
        return

    package_dir = Path(wcferry.__file__).resolve().parent
    required = ["sdk.dll", "spy.dll", "spy_debug.dll", "DISCLAIMER.md"]

    configured = os.getenv("WCF_SDK_DLL", "").strip().strip('"')
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).parent)
    candidates.extend(
        [
            Path.cwd() / "wcf-release",
            Path.cwd() / "WeChatFerry" / "WeChatFerry" / "Out",
            Path.cwd(),
        ]
    )

    for candidate in candidates:
        if all((candidate / name).exists() for name in required):
            for name in required:
                src = candidate / name
                dst = package_dir / name
                if src.resolve() != dst.resolve() and (
                    not dst.exists() or not filecmp.cmp(src, dst, shallow=False)
                ):
                    LOG.info("copying %s from %s to %s", name, src, dst)
                    shutil.copy2(src, dst)
            return

    searched = "\n".join(f"  - {path}" for path in candidates)
    raise FileNotFoundError(
        "Windows local mode needs sdk.dll, spy.dll, spy_debug.dll, and DISCLAIMER.md.\n"
        "Put the extracted WeChatFerry release files at one of these paths, or set WCF_SDK_DLL:\n"
        f"{searched}"
    )
