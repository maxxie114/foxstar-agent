# FoxStar Agent

FoxStar is a Python agent built around conversations that continue while a model is working. This edition provides the model gateway, research worker, conversation memory and durable job storage as an importable library. It has no messaging transport or service entry point.

For example, an application can save a research question, hand it to a worker with its own model context, and retrieve the completed report from SQLite. The research client can search in several rounds, read pages and synthesize a report. A separate rolling summary keeps older conversation history available alongside recent messages. [Architecture and data flow](docs/architecture.md)

## Try it offline

Use Python 3.10 or later. From the repository root:

```sh
python -m venv .venv
```

Activate the environment, then install the test dependencies and run the suite:

```sh
python -m pip install -e ".[test]"
python -m pytest -q
```

The tests use synthetic inputs, temporary files and model doubles. To follow a research question from submission to completion, see [the background task tests](tests/test_agent_tasks.py). For an example of queue recovery after a process restart, see [the recovery test](tests/test_public_core.py).

## Configure a caller

Copy [config.example.json](config.example.json) to `config.json` for local edits. The example selects one model and disables optional tools. A caller can load it with Python's standard library:

```python
import json
import os
from pathlib import Path

from foxstar_bot.config import AppConfig, ModelConfig, ToolConfig

settings = json.loads(Path("config.json").read_text(encoding="utf-8"))
config = AppConfig(
    model=ModelConfig(**settings["model"]),
    tools=ToolConfig(**settings["tools"]),
    openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
)
```

For live OpenAI calls, set `OPENAI_API_KEY` in the caller's environment. If your application loads dotenv files, copy [.env.example](.env.example) to `.env` and fill in the key locally. FoxStar itself does not load dotenv files. The offline tests need no key.

## Explore the code

| Component | Responsibility |
| --- | --- |
| [Model client](foxstar_bot/llm_client.py) | Translates messages, tool schemas and results between provider protocols. Runs bounded tool loops and accounts for usage. |
| [Background tasks](foxstar_bot/agent_tasks.py) | Claims pending research, records progress and stores the final result or error. |
| [Research](foxstar_bot/tool_research.py) | Plans follow-up searches, collects page evidence and assembles reports. |
| [Conversation context](foxstar_bot/context_store.py) | Divides history into recent messages, older material to summarize and the messages between them. |
| [Routing utilities](foxstar_bot/router.py) | Parses reply decisions, schedules context compression and splits responses for delivery. |
| [Persistence](foxstar_bot/persistence.py) | Defines the SQLite schema and operations for jobs, messages, schedules and delivery state. Callers supply their own database path. |
| [Document tools](foxstar_bot/tool_docs.py) | Extracts and queries text from documents, including table content. |
| [Prompt templates](prompt_templates/) | Supplies generic Chinese-language conversation styles. |

The model and research components accept caller-supplied clients or credentials. The public distribution omits the native WeChat integration, deployment configuration, operational data and vendor binaries. [Release history](CHANGELOG.md)

FoxStar Agent is distributed under the [Apache License, Version 2.0](LICENSE).

