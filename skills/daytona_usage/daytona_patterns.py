"""
Daytona helper notes for this bot's run_python_code tool.

These patterns are for copy/paste into one single Daytona execution.
"""

# Pattern 1: one-shot JSON output
ONE_SHOT_JSON = r'''
import json

result = {
    "ok": True,
    "summary": "put your result here",
}
print(json.dumps(result, ensure_ascii=False))
'''


# Pattern 2: shell fallback for simple probes
SHELL_PROBE = r'''
import subprocess

proc = subprocess.run(
    ["python", "--version"],
    capture_output=True,
    text=True,
    timeout=10,
)
print(proc.stdout or proc.stderr)
'''


# Pattern 3: network fetch with explicit failure handling
NETWORK_FETCH = r'''
import json
import urllib.request

url = "https://example.com"
try:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8")
    print(json.dumps({"ok": True, "preview": body[:500]}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
'''


# Pattern 4: what a future persistent interpreter workflow would look like
STATEFUL_NOTES = r'''
This bot does not currently expose Daytona's persistent code_interpreter API.

Official Daytona supports:
    sandbox.code_interpreter.run_code(...)
    ctx = sandbox.code_interpreter.create_context()
    sandbox.code_interpreter.delete_context(ctx)

That mode keeps Python state across calls inside the same context.
Do not assume it exists in this bot unless the tool wrapper is upgraded.
'''
