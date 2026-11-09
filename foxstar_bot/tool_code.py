from __future__ import annotations

import logging
import base64
from dataclasses import dataclass

from .config import AppConfig

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class CodeExecutionResult:
    ok: bool
    output: str
    error: str = ""


class DaytonaCodeTool:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def enabled(self) -> bool:
        return bool(self.config.tools.code_execution_enabled and self.config.daytona_api_key)

    def run_python(self, code: str, timeout_seconds: int = 20) -> CodeExecutionResult:
        code = (code or "").strip()
        if not code:
            return CodeExecutionResult(False, "", "code is empty")
        if not self.enabled():
            return CodeExecutionResult(False, "", "Daytona code execution is not enabled")

        timeout_seconds = max(1, min(int(timeout_seconds or 20), 60))
        sandbox = None
        try:
            from daytona import Daytona, DaytonaConfig
        except Exception as exc:
            return CodeExecutionResult(False, "", f"daytona SDK is not installed: {exc}")

        try:
            daytona = Daytona(DaytonaConfig(api_key=self.config.daytona_api_key))
            sandbox = daytona.create()
            response = _run_code_in_sandbox(sandbox, code, timeout_seconds)
            exit_code = int(getattr(response, "exit_code", 0) or 0)
            result = str(getattr(response, "result", "") or getattr(response, "stdout", "") or "")
            if exit_code != 0:
                error = str(getattr(response, "stderr", "") or result or f"exit_code={exit_code}")
                return CodeExecutionResult(False, result[:8000], error[:4000])
            return CodeExecutionResult(True, result[:8000])
        except Exception as exc:
            LOG.exception("daytona code execution failed")
            return CodeExecutionResult(False, "", str(exc)[:4000])
        finally:
            if sandbox is not None:
                try:
                    sandbox.delete()
                except Exception:
                    LOG.warning("daytona sandbox cleanup failed", exc_info=True)


def _run_code_in_sandbox(sandbox: object, code: str, timeout_seconds: int) -> object:
    process = getattr(sandbox, "process")
    if hasattr(process, "code_run"):
        return process.code_run(code)
    encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
    command = f"python -c \"import base64; exec(base64.b64decode('{encoded}').decode('utf-8'))\""
    if hasattr(process, "exec"):
        try:
            return process.exec(command, timeout=timeout_seconds)
        except TypeError:
            return process.exec(command)
    if hasattr(process, "execute_command"):
        try:
            return process.execute_command(command, timeout=timeout_seconds)
        except TypeError:
            return process.execute_command(command)
    raise RuntimeError("unsupported Daytona process API")
