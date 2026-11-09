# Architecture

## Research alongside conversation

A caller records a research instruction in SQLite. The background task runner claims pending work and gives the model the instruction and research tools in a separate conversation. The research tool can refine a query, gather evidence from multiple pages and return a brief to the model. The worker stores progress while it runs, then saves a report or records a failure. The database tracks delivery separately so an application can distinguish “the report is ready” from “the recipient received it.”

## Replies and recovery

A reply job records its source message, serialized payload and context cutoff. When a source message has an identifier, the queue can recognize another submission of that message. A worker claims a queued job before processing it. Recovery puts interrupted running jobs back into the queue. Applications that add a transport must account for the interval between sending a message and recording its delivery.

## Memory and model selection

Context is scoped to the conversation. Recent messages remain available verbatim. Older messages can be compressed asynchronously, and an intermediate window covers the gap until a summary catches up. The model client converts tool descriptions and tool results to the provider’s expected format. It can stop a tool loop when a handler produces a final answer, and it tracks repeated failed calls.

## Working with files

The document module reads PDF, DOCX and text files and splits extracted text into searchable passages. File checks can detect an incomplete PDF or an invalid DOCX archive before processing. The vision module prepares local images for a caller-supplied model. The included XML functions parse message markup without requiring a messaging client.

## Scope of the public edition

This library is suitable for studying and testing individual components. An application would have to supply ingress, authorization policy, delivery and deployment integration to use it as a live messaging agent. The shipped tests exercise the components locally. Historical commits show the evolution of the retained source; the current revision is the supported test target.

