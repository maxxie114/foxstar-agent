# Architecture

## Message flow

The application assembles configuration, authorization, persistence, model clients, tools, skills and a transport adapter. Incoming messages enter a bounded worker queue. `MessageRouter` records context, dispatches commands, evaluates whether to reply, selects a model and executes a bounded tool loop. Replies are split for delivery through the adapter.

The default adapter connects to an operator-supplied WeChat runtime. Both the adapter and model client can be injected into `build_router` for other integrations or offline testing. Importing the framework does not require the WeChat client or native libraries.

## Research, schedules and recovery

A background task runner claims research jobs, gives the model separate task context, and persists progress, results and delivery state. The application also polls due schedules; the router executes scheduled commands or prompts and updates their next run time.

Reply-job storage supports deduplication, claiming and recovery. These queue APIs remain available to callers; the restored application retains its upstream in-memory ingress worker queue. Applications using durable reply jobs must account for the interval between sending a reply and recording delivery.

## Memory and skills

Conversation context combines recent messages with rolling summaries of older history. Memory and settings are scoped by caller-supplied identifiers. The model client supports provider selection and tool schemas; the router adds per-conversation overrides and configurable routing tiers.

The skill registry searches `skills/*/SKILL.md` and loads companion source files. Document, vision, search, market, weather, game, code-execution and optional clan-service tools are available through the router. Native image analysis and document validation are preserved.

## Release boundary

The public source includes the authored application, routing, model switching, commands, scheduling, skills, control API, tools and Python WeChat integration. All upstream top-level Python modules are represented. The public edition also retains its context snapshot and durable reply-job helpers.

Private `.env` and deployment configuration, database files and dumps, chat logs, stored memory, knowledgebase contents, private persona prompts, operational bug-report IDs and production identity defaults are excluded. Generic prompt templates and invented test fixtures are supplied instead. The database schema and data-access code remain, allowing users to create their own empty database.

Third-party DLLs, executables, SDK/vendor trees, release archives and expanded external game datasets are excluded. WeChat dependencies are installed separately by the operator. Game loaders retain support for external resources and use built-in examples when those files are absent.

The exact-path Git allowlist admits reviewed source and examples. Runtime output and local secrets are ignored by default. Historical snapshots describe the earlier partial library extraction; the restored current source is the supported integration target.
