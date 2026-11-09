# Daytona Stateless Code Tool

Use this skill when the task depends on `run_python_code` and the model needs to choose a reliable way to use the Daytona sandbox.

适用中文场景：当用户要求“用 coding tool 处理”“在 Daytona 里跑代码”“别乱 pip install”“直接给我脚本”时，优先使用这个 skill。

What Daytona means in this bot:

1. `run_python_code` creates a fresh Daytona sandbox for each call.
2. Package installs and filesystem changes do not persist to the next tool call.
3. Therefore:
   - avoid `pip install` loops
   - prefer standard library
   - prefer one self-contained script per tool call
   - if a network/API route fails, do not keep hammering the same failing method

Official Daytona notes reflected here:

- `sandbox.process.code_run(...)` is stateless code execution. Each call starts from a clean interpreter state.
- `sandbox.process.exec(...)` runs shell commands and is useful for quick environment/network probes.
- Daytona also exposes `sandbox.code_interpreter.run_code(...)`, which is stateful for Python and keeps variables/imports/functions in the same context across runs.
- `sandbox.code_interpreter.create_context()` creates an isolated interpreter context. Contexts can be listed and deleted later.
- This bot does not currently use Daytona's stateful code interpreter. Its `run_python_code` wrapper creates a sandbox, runs one snippet, and deletes the sandbox.
- if a dependency is truly required, the long-term fix is a custom sandbox image, not repeated installs inside each chat turn

How to choose the execution mode:

- For this bot today: assume one-shot execution only.
- For independent scripts: prefer `process.code_run`.
- For shell checks like `python --version`, `ls`, `curl`, or probing connectivity: prefer `process.exec`.
- If the project is upgraded later to persistent Daytona contexts, then repeated Python work can move to `code_interpreter.run_code`.

Recommended workflow:

1. Write one self-contained script.
2. Put all parsing / fetching / formatting in that single script.
3. Return structured JSON or short plain text.
4. If the first method fails for environmental reasons, explain it and switch method once at most.

Reference files are bundled below when you call `load_skill`.
