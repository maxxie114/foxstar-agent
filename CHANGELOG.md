# Changelog

## Public source edition

This edition contains the model gateway, research agent, background task runner, document and vision tools, rolling context, reply queue storage, and synthetic tests. The WeChat transport, vendor binaries, bundled datasets and production integration are outside this distribution.

## Development history

The reconstruction follows 349 upstream revisions in their original order and retains their calendar dates. 146 revisions contain changes to public files. The other 203 are empty checkpoints. Commit authors and subjects were replaced and all commit IDs were regenerated. Earlier versions are partial where a function, class or literal could not be cleared.

Use the short IDs below with Git to inspect the public diffs.

## 2026-04

| Date | Commit | Change |
| --- | --- | --- |
| 2026-04-10 | 984c578 | `foxstar_bot/__init__.py`, `foxstar_bot/auth.py`, `foxstar_bot/config.py`, `foxstar_bot/context_store.py`, `foxstar_bot/file_checks.py`, `foxstar_bot/guardrails.py`, `foxstar_bot/limiter.py`, `foxstar_bot/llm_client.py`, `foxstar_bot/memory_store.py`, `foxstar_bot/persistence.py`, `foxstar_bot/reply_style.py`, `foxstar_bot/router.py`, `foxstar_bot/tool_docs.py`, `foxstar_bot/tool_search.py`, `foxstar_bot/tool_vision.py`, `tests/test_reply_style.py` |
| 2026-04-10 | ea25c1a | `foxstar_bot/reply_style.py`, `tests/test_reply_style.py` |
| 2026-04-10 | 14e85ab | Checkpoint only |
| 2026-04-10 | ccc485b | `foxstar_bot/llm_client.py`, `foxstar_bot/reply_style.py`, `foxstar_bot/tool_search.py`, `tests/test_reply_style.py` |
| 2026-04-10 | 9c1c04f | `foxstar_bot/limiter.py` |
| 2026-04-10 | 8e0d44e | `foxstar_bot/auth.py` |
| 2026-04-11 | c91250b | Checkpoint only |
| 2026-04-11 | c8d8b1d | `foxstar_bot/router.py`, `foxstar_bot/style_profiles.py`, `foxstar_bot/wechat_xml.py`, `tests/test_style_profiles.py` |
| 2026-04-11 | bae3790 | Checkpoint only |
| 2026-04-11 | c69b20a | `foxstar_bot/wechat_xml.py` |
| 2026-04-11 | 7dc76cb | `foxstar_bot/llm_client.py` |
| 2026-04-11 | 53d3df4 | Checkpoint only |
| 2026-04-11 | 253dd94 | Checkpoint only |
| 2026-04-11 | 98c2024 | `foxstar_bot/style_profiles.py`, `tests/test_style_profiles.py` |
| 2026-04-11 | 5e09529 | `foxstar_bot/config.py`, `foxstar_bot/llm_client.py`, `foxstar_bot/memory_store.py`, `foxstar_bot/tool_url.py`, `tests/test_tool_url.py` |
| 2026-04-12 | 8e3be7b | `foxstar_bot/llm_client.py`, `foxstar_bot/router.py` |
| 2026-04-12 | 69abfec | `foxstar_bot/config.py`, `foxstar_bot/llm_client.py` |
| 2026-04-12 | e48fb79 | `foxstar_bot/config.py`, `foxstar_bot/llm_client.py`, `foxstar_bot/persistence.py`, `foxstar_bot/tool_vision.py` |
| 2026-04-12 | 005e84b | `foxstar_bot/llm_client.py` |
| 2026-04-12 | 9ed57a2 | Checkpoint only |
| 2026-04-12 | 5fd3188 | `foxstar_bot/llm_client.py` |
| 2026-04-12 | f279a92 | `foxstar_bot/llm_client.py` |
| 2026-04-12 | 1af4fc7 | `foxstar_bot/llm_client.py` |
| 2026-04-12 | f45107f | `foxstar_bot/llm_client.py` |
| 2026-04-12 | ea14cf7 | Checkpoint only |
| 2026-04-12 | 0d2b545 | Checkpoint only |
| 2026-04-12 | 58bcae8 | Checkpoint only |
| 2026-04-12 | 0e38530 | `foxstar_bot/llm_client.py` |
| 2026-04-12 | 898824f | Checkpoint only |
| 2026-04-12 | f953694 | Checkpoint only |
| 2026-04-12 | d81cfcb | Checkpoint only |
| 2026-04-12 | f2c273c | Checkpoint only |
| 2026-04-12 | 7da0143 | `foxstar_bot/config.py`, `foxstar_bot/limiter.py` |
| 2026-04-12 | 97e3ff3 | Checkpoint only |
| 2026-04-12 | 4738500 | Checkpoint only |
| 2026-04-12 | 9938b2a | Checkpoint only |
| 2026-04-12 | fc4e7a1 | Checkpoint only |
| 2026-04-12 | 9a9b9dc | Checkpoint only |
| 2026-04-13 | 3f6f459 | Checkpoint only |
| 2026-04-13 | 8e05ef6 | Checkpoint only |
| 2026-04-13 | da0e406 | Checkpoint only |
| 2026-04-13 | ee55564 | Checkpoint only |
| 2026-04-13 | b5f3b6f | Checkpoint only |
| 2026-04-13 | 9c1ea74 | `prompt_templates/debate.md`, `prompt_templates/default.md`, `prompt_templates/funny.md`, `prompt_templates/philosophy.md`, `prompt_templates/rational-neutral.md`, `prompt_templates/roast.md`, `prompt_templates/roleplay.md`, `prompt_templates/soft-cute.md` |
| 2026-04-13 | fb82767 | Checkpoint only |
| 2026-04-13 | 81942c8 | Checkpoint only |
| 2026-04-13 | 19cf349 | Checkpoint only |
| 2026-04-14 | d080d80 | Checkpoint only |
| 2026-04-14 | 5019cd1 | `foxstar_bot/memory_store.py`, `foxstar_bot/persistence.py` |
| 2026-04-14 | 120f424 | `foxstar_bot/memory_store.py`, `foxstar_bot/reply_style.py`, `tests/test_reply_style.py` |
| 2026-04-15 | f615338 | Checkpoint only |
| 2026-04-15 | 00d5422 | Checkpoint only |
| 2026-04-15 | 020d83e | `foxstar_bot/config.py` |
| 2026-04-15 | 0d8373e | `foxstar_bot/context_store.py` |
| 2026-04-15 | 2a41bb7 | `foxstar_bot/llm_client.py` |
| 2026-04-15 | 21711f5 | `foxstar_bot/context_store.py`, `tests/test_reply_style_ascii.py` |
| 2026-04-15 | 19fff03 | Checkpoint only |
| 2026-04-15 | 45e7c26 | Checkpoint only |
| 2026-04-16 | 170346e | Checkpoint only |
| 2026-04-16 | 9f4bde7 | `foxstar_bot/guardrails.py` |
| 2026-04-16 | 5b0cd3a | Checkpoint only |
| 2026-04-16 | 6b3eba5 | `foxstar_bot/config.py`, `foxstar_bot/router.py`, `foxstar_bot/tool_docs.py`, `foxstar_bot/tool_research.py` |
| 2026-04-17 | fd0fac0 | `foxstar_bot/config.py`, `foxstar_bot/llm_client.py`, `foxstar_bot/persistence.py` |
| 2026-04-17 | 2fb6b4b | Checkpoint only |
| 2026-04-17 | 45297ad | `foxstar_bot/llm_client.py`, `foxstar_bot/tool_research.py` |
| 2026-04-17 | 8b8db7c | `foxstar_bot/config.py`, `foxstar_bot/llm_client.py`, `foxstar_bot/tool_research.py`, `foxstar_bot/tool_search.py` |
| 2026-04-17 | 875584d | `foxstar_bot/tool_research.py` |
| 2026-04-17 | 4db735e | `foxstar_bot/tool_research.py` |
| 2026-04-17 | 6fc1845 | `foxstar_bot/llm_client.py`, `foxstar_bot/tool_research.py` |
| 2026-04-17 | 40969cd | `foxstar_bot/config.py`, `foxstar_bot/llm_client.py`, `foxstar_bot/tool_research.py`, `foxstar_bot/tool_search.py` |
| 2026-04-17 | fcc5a8c | `foxstar_bot/config.py`, `foxstar_bot/llm_client.py`, `foxstar_bot/tool_research.py` |
| 2026-04-17 | c30245c | `foxstar_bot/llm_client.py` |
| 2026-04-18 | 68fd421 | `foxstar_bot/context_store.py`, `foxstar_bot/privacy.py` |
| 2026-04-18 | bd4e025 | `foxstar_bot/context_store.py` |
| 2026-04-19 | b3a0a34 | `foxstar_bot/context_store.py`, `foxstar_bot/llm_client.py`, `foxstar_bot/privacy.py`, `foxstar_bot/reply_style.py`, `foxstar_bot/router.py`, `foxstar_bot/tool_url.py` |
| 2026-04-20 | d8ee329 | `foxstar_bot/llm_client.py` |
| 2026-04-20 | c218f4d | `foxstar_bot/llm_client.py` |
| 2026-04-22 | 495f6c3 | `foxstar_bot/config.py`, `foxstar_bot/llm_client.py`, `foxstar_bot/router.py`, `foxstar_bot/wechat_xml.py` |
| 2026-04-22 | 8ea52e0 | `foxstar_bot/config.py`, `foxstar_bot/limiter.py`, `foxstar_bot/llm_client.py` |
| 2026-04-22 | bce47f2 | Checkpoint only |
| 2026-04-23 | 3e9f099 | `foxstar_bot/router.py`, `tests/test_router_delivery.py` |
| 2026-04-23 | abf9fa1 | `foxstar_bot/llm_client.py` |
| 2026-04-23 | 66b262d | `foxstar_bot/router.py`, `foxstar_bot/tool_knowledge.py` |
| 2026-04-23 | 97e24af | `foxstar_bot/config.py`, `foxstar_bot/llm_client.py`, `tests/test_deepseek_provider.py` |
| 2026-04-24 | 1d181a7 | Checkpoint only |
| 2026-04-24 | f243655 | `foxstar_bot/config.py`, `foxstar_bot/llm_client.py` |
| 2026-04-24 | ce05f37 | `foxstar_bot/llm_client.py` |
| 2026-04-24 | aee240b | Checkpoint only |
| 2026-04-24 | 58304d1 | Checkpoint only |
| 2026-04-24 | 3e46a43 | Checkpoint only |
| 2026-04-24 | 435082b | `foxstar_bot/llm_client.py`, `tests/test_deepseek_provider.py` |
| 2026-04-24 | 88761a9 | `foxstar_bot/llm_client.py`, `foxstar_bot/persistence.py`, `foxstar_bot/tool_research.py` |
| 2026-04-24 | d8198e9 | `foxstar_bot/persistence.py` |
| 2026-04-24 | 3b71622 | `foxstar_bot/llm_client.py`, `tests/test_deepseek_provider.py` |
| 2026-04-25 | 2213072 | Checkpoint only |
| 2026-04-25 | 369d542 | `foxstar_bot/tool_market.py` |
| 2026-04-25 | fd8c7f1 | `foxstar_bot/tool_market.py` |
| 2026-04-25 | a0a429a | `foxstar_bot/tool_market.py` |
| 2026-04-26 | c7c9e51 | `foxstar_bot/llm_client.py` |
| 2026-04-26 | a59b311 | `foxstar_bot/persistence.py` |
| 2026-04-26 | 19ff5ed | `foxstar_bot/persistence.py` |
| 2026-04-26 | fc55ae4 | Checkpoint only |
| 2026-04-26 | 8f57c4b | `foxstar_bot/llm_client.py`, `foxstar_bot/tool_research.py` |
| 2026-04-26 | b3c26ef | `foxstar_bot/llm_client.py` |
| 2026-04-26 | 14f0fa8 | `foxstar_bot/tool_market.py` |
| 2026-04-26 | f522b6e | `foxstar_bot/llm_client.py`, `foxstar_bot/router.py` |
| 2026-04-26 | 6e43a72 | Checkpoint only |
| 2026-04-26 | 64e22f3 | Checkpoint only |
| 2026-04-26 | 99ce49b | `foxstar_bot/context_store.py` |
| 2026-04-26 | 939504f | Checkpoint only |
| 2026-04-26 | fce7b58 | Checkpoint only |
| 2026-04-26 | 0fce663 | `foxstar_bot/persistence.py`, `foxstar_bot/schedule_utils.py` |
| 2026-04-26 | 3415879 | Checkpoint only |
| 2026-04-26 | cca3c38 | Checkpoint only |
| 2026-04-26 | ded1ed9 | Checkpoint only |
| 2026-04-26 | 0ef41be | Checkpoint only |
| 2026-04-26 | 632a707 | `foxstar_bot/tool_weather.py` |
| 2026-04-26 | e8b057c | Checkpoint only |
| 2026-04-26 | 6847a5c | Checkpoint only |
| 2026-04-26 | 1fbf3fd | Checkpoint only |
| 2026-04-26 | 9a9897e | Checkpoint only |
| 2026-04-26 | 0659e1d | Checkpoint only |
| 2026-04-26 | 30032d7 | Checkpoint only |
| 2026-04-27 | 7db87d9 | Checkpoint only |
| 2026-04-28 | 7553b93 | Checkpoint only |
| 2026-04-28 | c774266 | `foxstar_bot/llm_client.py` |
| 2026-04-28 | 32ec246 | `foxstar_bot/context_store.py` |

## 2026-05

| Date | Commit | Change |
| --- | --- | --- |
| 2026-05-05 | a6394eb | Checkpoint only |
| 2026-05-05 | beb5f5b | `foxstar_bot/persistence.py` |
| 2026-05-05 | c62b207 | Checkpoint only |
| 2026-05-05 | c3a2a66 | Checkpoint only |
| 2026-05-05 | 5cef82f | Checkpoint only |
| 2026-05-05 | 58d042d | Checkpoint only |
| 2026-05-05 | e9d3c82 | Checkpoint only |
| 2026-05-05 | 8dcf3ee | Checkpoint only |
| 2026-05-05 | d72d724 | Checkpoint only |
| 2026-05-05 | 5ba9d9c | `foxstar_bot/persistence.py` |
| 2026-05-05 | 5acdbf1 | Checkpoint only |
| 2026-05-05 | 17a0eb5 | Checkpoint only |
| 2026-05-05 | e75781f | Checkpoint only |
| 2026-05-05 | df75e3b | Checkpoint only |
| 2026-05-06 | 5db3397 | Checkpoint only |
| 2026-05-06 | 90482b6 | `foxstar_bot/config.py`, `foxstar_bot/tool_research.py` |
| 2026-05-06 | 14f175f | Checkpoint only |
| 2026-05-06 | 8826347 | `foxstar_bot/config.py`, `foxstar_bot/llm_client.py` |
| 2026-05-06 | dfeb574 | Checkpoint only |
| 2026-05-06 | ea24d4a | Checkpoint only |
| 2026-05-06 | 6ceb46e | Checkpoint only |
| 2026-05-06 | e8386b9 | `foxstar_bot/llm_client.py` |
| 2026-05-06 | 2c00aee | `foxstar_bot/llm_client.py` |
| 2026-05-06 | 9a3db4c | `foxstar_bot/llm_client.py` |
| 2026-05-06 | 0cf5063 | `foxstar_bot/llm_client.py` |
| 2026-05-06 | 2054c0e | `foxstar_bot/persistence.py` |
| 2026-05-06 | 9cf667b | Checkpoint only |
| 2026-05-06 | 06b1a52 | `foxstar_bot/tool_market.py` |
| 2026-05-06 | 5e545c4 | `foxstar_bot/llm_client.py` |
| 2026-05-06 | 921cf95 | Checkpoint only |
| 2026-05-06 | 1f2219b | Checkpoint only |
| 2026-05-06 | 5687193 | Checkpoint only |
| 2026-05-06 | f1ca611 | Checkpoint only |
| 2026-05-07 | 3d5ce32 | `foxstar_bot/config.py` |
| 2026-05-07 | 4457aac | `foxstar_bot/persistence.py` |
| 2026-05-07 | a16f451 | `foxstar_bot/config.py` |
| 2026-05-07 | 7b87034 | Checkpoint only |
| 2026-05-22 | 624b58d | `foxstar_bot/config.py` |
| 2026-05-22 | b2548c7 | `foxstar_bot/llm_client.py`, `tests/test_minimax_provider.py` |
| 2026-05-22 | 6c13fbd | `foxstar_bot/llm_client.py`, `tests/test_minimax_provider.py` |

## 2026-06

| Date | Commit | Change |
| --- | --- | --- |
| 2026-06-16 | 2db6fd2 | `foxstar_bot/llm_client.py`, `foxstar_bot/persistence.py` |
| 2026-06-16 | 1a57fee | Checkpoint only |
| 2026-06-23 | a530453 | `foxstar_bot/config.py`, `foxstar_bot/llm_client.py`, `tests/test_deepseek_provider.py` |
| 2026-06-23 | 831f577 | `foxstar_bot/persistence.py`, `foxstar_bot/router.py` |
| 2026-06-24 | e7191ef | `foxstar_bot/llm_client.py`, `tests/test_schedule_task.py` |
| 2026-06-24 | 1c37172 | `foxstar_bot/persistence.py` |
| 2026-06-29 | de18672 | Checkpoint only |
| 2026-06-29 | b00fe02 | `foxstar_bot/router.py` |

## 2026-07

| Date | Commit | Change |
| --- | --- | --- |
| 2026-07-06 | 00dff9f | Checkpoint only |
| 2026-07-06 | eb59477 | Checkpoint only |
| 2026-07-06 | 4643429 | Checkpoint only |
| 2026-07-06 | 7ef1ce6 | Checkpoint only |
| 2026-07-06 | 8fbdc28 | Checkpoint only |
| 2026-07-15 | 0997c14 | Checkpoint only |
| 2026-07-15 | b0599eb | Checkpoint only |

## 2026-08

| Date | Commit | Change |
| --- | --- | --- |
| 2026-08-01 | 27d9b4a | `foxstar_bot/context_store.py`, `tests/test_context_store.py` |
| 2026-08-01 | a9ed73e | `foxstar_bot/context_store.py`, `foxstar_bot/persistence.py`, `foxstar_bot/router.py`, `tests/test_context_store.py` |
| 2026-08-04 | cbf579e | `foxstar_bot/context_store.py`, `foxstar_bot/router.py`, `tests/test_context_store.py` |
| 2026-08-04 | 28e39da | `foxstar_bot/persistence.py`, `foxstar_bot/router.py`, `tests/test_schedule_task.py` |
| 2026-08-05 | 97835cf | `foxstar_bot/config.py`, `foxstar_bot/llm_client.py`, `tests/test_additional_providers.py` |
| 2026-08-05 | 39beffc | Checkpoint only |
| 2026-08-05 | 277d6a0 | Checkpoint only |
| 2026-08-26 | 5e0d04a | `foxstar_bot/config.py`, `foxstar_bot/llm_client.py`, `foxstar_bot/tool_vision.py` |
| 2026-08-30 | 546023c | Checkpoint only |
| 2026-08-30 | 78007f1 | Checkpoint only |
| 2026-08-30 | f7ec2b2 | Checkpoint only |
| 2026-08-31 | fd08c2a | Checkpoint only |
| 2026-08-31 | 8765d97 | Checkpoint only |
| 2026-08-31 | 7cc7699 | `foxstar_bot/persistence.py` |
| 2026-08-31 | 1d3aced | Checkpoint only |
| 2026-08-31 | da42083 | Checkpoint only |
| 2026-08-31 | b2b20c1 | `foxstar_bot/router.py` |
| 2026-08-31 | 929edab | Checkpoint only |
| 2026-08-31 | d8f588f | Checkpoint only |
| 2026-08-31 | 70597b8 | `foxstar_bot/persistence.py` |
| 2026-08-31 | 7fff89a | Checkpoint only |
| 2026-08-31 | a9d7f37 | Checkpoint only |
| 2026-08-31 | 5f6927a | Checkpoint only |
| 2026-08-31 | 2175efa | Checkpoint only |
| 2026-08-31 | 78973eb | Checkpoint only |
| 2026-08-31 | 3c53999 | `foxstar_bot/persistence.py` |
| 2026-08-31 | 2881b22 | Checkpoint only |
| 2026-08-31 | db2ac33 | Checkpoint only |
| 2026-08-31 | df6f513 | Checkpoint only |

## 2026-09

| Date | Commit | Change |
| --- | --- | --- |
| 2026-09-01 | c2ba5f1 | `foxstar_bot/config.py` |
| 2026-09-08 | 24eea43 | `foxstar_bot/privacy.py` |
| 2026-09-08 | b7ca83d | Checkpoint only |
| 2026-09-08 | adfd7d7 | Checkpoint only |
| 2026-09-08 | 0e4dd18 | Checkpoint only |
| 2026-09-08 | f861100 | Checkpoint only |
| 2026-09-08 | 2899d93 | `foxstar_bot/persistence.py` |
| 2026-09-14 | 09b9c18 | Checkpoint only |
| 2026-09-14 | 4613cf2 | Checkpoint only |
| 2026-09-14 | fcb960c | `foxstar_bot/persistence.py` |
| 2026-09-14 | 50f08ae | `foxstar_bot/router.py` |
| 2026-09-14 | e9e8186 | Checkpoint only |
| 2026-09-14 | 4f48c1a | `foxstar_bot/tool_research.py`, `foxstar_bot/tool_search.py`, `tests/test_websearch_v2.py` |
| 2026-09-14 | 7ba0694 | `foxstar_bot/tool_research.py`, `tests/test_websearch_v2.py` |
| 2026-09-14 | 66b4f73 | `foxstar_bot/tool_research.py`, `tests/test_websearch_v2.py` |
| 2026-09-14 | 43c21a0 | `foxstar_bot/file_checks.py`, `foxstar_bot/router.py`, `foxstar_bot/tool_docs.py`, `tests/test_docs_v2.py` |
| 2026-09-14 | 358f365 | `foxstar_bot/agent_tasks.py`, `foxstar_bot/persistence.py`, `tests/test_agent_tasks.py` |
| 2026-09-14 | 46975ce | Checkpoint only |
| 2026-09-14 | 64cd901 | `foxstar_bot/config.py`, `foxstar_bot/tool_research.py`, `tests/test_websearch_v2.py` |
| 2026-09-14 | dcbbfdb | Checkpoint only |
| 2026-09-14 | 2a2e549 | Checkpoint only |
| 2026-09-14 | 88d0bf8 | Checkpoint only |
| 2026-09-14 | 803d46a | Checkpoint only |
| 2026-09-15 | 76a55f6 | `foxstar_bot/health.py`, `tests/test_health.py` |
| 2026-09-16 | 134cde3 | Checkpoint only |
| 2026-09-17 | 06bfae5 | Checkpoint only |
| 2026-09-28 | fe4e239 | Checkpoint only |
| 2026-09-28 | e17a6a1 | Checkpoint only |
| 2026-09-30 | 2c0f40d | Checkpoint only |
| 2026-09-30 | 2ddc692 | Checkpoint only |
| 2026-09-30 | f2c901a | Checkpoint only |
| 2026-09-30 | e708ee4 | Checkpoint only |
| 2026-09-30 | a4564cc | Checkpoint only |
| 2026-09-30 | af17a7c | Checkpoint only |
| 2026-09-30 | 011d9be | Checkpoint only |
| 2026-09-30 | 62b73a3 | `foxstar_bot/llm_client.py` |
| 2026-09-30 | 1fc4f8d | Checkpoint only |
| 2026-09-30 | 12baadd | Checkpoint only |
| 2026-09-30 | 38af054 | Checkpoint only |
| 2026-09-30 | ea2f333 | Checkpoint only |
| 2026-09-30 | d87d5d9 | Checkpoint only |

## 2026-10

| Date | Commit | Change |
| --- | --- | --- |
| 2026-10-01 | 1104145 | Checkpoint only |
| 2026-10-01 | a5bada5 | Checkpoint only |
| 2026-10-01 | 9307658 | Checkpoint only |
| 2026-10-01 | 5ce976e | Checkpoint only |
| 2026-10-01 | c29b8f2 | Checkpoint only |
| 2026-10-01 | 520ae28 | Checkpoint only |
| 2026-10-01 | f8fc687 | Checkpoint only |
| 2026-10-01 | 4f26892 | Checkpoint only |
| 2026-10-01 | 03b7db6 | Checkpoint only |
| 2026-10-01 | 1ec6f50 | Checkpoint only |
| 2026-10-01 | 7e5554c | Checkpoint only |
| 2026-10-01 | c3773a5 | Checkpoint only |
| 2026-10-01 | f4ce422 | Checkpoint only |
| 2026-10-01 | 5fb3ff3 | Checkpoint only |
| 2026-10-01 | 50097dc | Checkpoint only |
| 2026-10-01 | f02fc1b | Checkpoint only |
| 2026-10-01 | 6990b97 | Checkpoint only |
| 2026-10-01 | 400d1ca | Checkpoint only |
| 2026-10-01 | cadbb54 | Checkpoint only |
| 2026-10-01 | e5f60d4 | Checkpoint only |
| 2026-10-01 | b509eb8 | Checkpoint only |
| 2026-10-02 | cbf1358 | Checkpoint only |
| 2026-10-02 | 71f99fa | Checkpoint only |
| 2026-10-02 | a28fd55 | Checkpoint only |
| 2026-10-02 | 06c117b | Checkpoint only |
| 2026-10-02 | 3328de9 | `foxstar_bot/tool_docs.py` |
| 2026-10-02 | 6a2c504 | `foxstar_bot/llm_client.py` |
| 2026-10-02 | 1f89c96 | Checkpoint only |
| 2026-10-02 | 90cc09c | `foxstar_bot/llm_client.py` |
| 2026-10-02 | 9ef331f | `foxstar_bot/llm_client.py` |
| 2026-10-02 | bfa23d6 | `foxstar_bot/llm_client.py` |
| 2026-10-06 | bdfcb00 | Checkpoint only |
| 2026-10-06 | 2152e85 | `foxstar_bot/tool_docs.py` |
| 2026-10-06 | 0ae3a3a | `foxstar_bot/health.py` |
| 2026-10-06 | 32609ad | `foxstar_bot/health.py` |
| 2026-10-06 | 1e03a13 | `foxstar_bot/config.py`, `foxstar_bot/llm_client.py` |
| 2026-10-06 | 628cbce | Checkpoint only |
| 2026-10-06 | d3c55f6 | Checkpoint only |
| 2026-10-06 | a753097 | `foxstar_bot/auth.py` |
| 2026-10-07 | e6d13ba | Checkpoint only |
| 2026-10-07 | d339dc3 | Checkpoint only |
| 2026-10-07 | bee93b0 | Checkpoint only |
| 2026-10-07 | 3487605 | Checkpoint only |
| 2026-10-07 | 56aa9a7 | Checkpoint only |
| 2026-10-07 | 189b7da | Checkpoint only |
| 2026-10-07 | fcbc3e8 | `foxstar_bot/llm_client.py` |
| 2026-10-07 | 0239cd9 | `foxstar_bot/llm_client.py` |
| 2026-10-07 | 4faa34c | Checkpoint only |
| 2026-10-08 | 56508e0 | `foxstar_bot/llm_client.py` |
| 2026-10-12 | ea502a4 | Checkpoint only |
| 2026-10-12 | 64a724f | Checkpoint only |
| 2026-10-12 | 98bd38a | Checkpoint only |
| 2026-10-12 | 52b107a | Checkpoint only |
| 2026-10-12 | 87f6123 | Checkpoint only |
| 2026-10-12 | fe57cff | Checkpoint only |
| 2026-10-12 | 59d9b44 | `foxstar_bot/llm_client.py` |
| 2026-10-12 | f77aa58 | Checkpoint only |
| 2026-10-12 | fc04394 | `foxstar_bot/llm_client.py` |
| 2026-10-12 | 4ad6541 | Checkpoint only |
| 2026-10-12 | 0765896 | Checkpoint only |
| 2026-10-12 | 5711f8b | `foxstar_bot/llm_client.py` |
| 2026-10-12 | 8cd64c3 | `foxstar_bot/llm_client.py` |
| 2026-10-13 | e40d698 | `foxstar_bot/reply_style.py` |
| 2026-10-13 | 0cdd82d | `foxstar_bot/reply_style.py` |
| 2026-10-13 | 70379bc | Checkpoint only |
| 2026-10-13 | 34de177 | Checkpoint only |
| 2026-10-13 | 47a3dde | Checkpoint only |
| 2026-10-13 | f85320d | Checkpoint only |
| 2026-10-13 | dd46ec3 | Checkpoint only |
| 2026-10-14 | 870e371 | `foxstar_bot/latency.py`, `foxstar_bot/persistence.py`, `foxstar_bot/reply_style.py` |
| 2026-10-14 | e20f21a | Checkpoint only |
| 2026-10-14 | 56f2024 | Checkpoint only |
| 2026-10-14 | 439767d | Checkpoint only |
| 2026-10-14 | b6c830a | `foxstar_bot/llm_client.py`, `foxstar_bot/provider_catalog.py` |
| 2026-10-14 | 28528c3 | Checkpoint only |
| 2026-10-14 | 736b42b | Checkpoint only |
| 2026-10-15 | f1a1f60 | Checkpoint only |
| 2026-10-15 | 3407c6f | Checkpoint only |
| 2026-10-15 | 2c26f69 | Checkpoint only |
| 2026-10-15 | 8de052a | `foxstar_bot/llm_client.py` |
| 2026-10-15 | 5b72e05 | `foxstar_bot/reply_style.py` |
| 2026-10-16 | 572293c | `foxstar_bot/reply_style.py` |
| 2026-10-22 | bea8fc6 | `foxstar_bot/context_store.py`, `foxstar_bot/persistence.py`, `foxstar_bot/router.py` |
| 2026-10-26 | 3a9ae89 | `foxstar_bot/config.py`, `foxstar_bot/llm_client.py` |
| 2026-10-26 | 2c4d2a8 | Checkpoint only |
| 2026-10-26 | 49adcc1 | `foxstar_bot/router.py` |
| 2026-10-26 | 7aadb35 | Checkpoint only |
| 2026-10-26 | 662e884 | Checkpoint only |
| 2026-10-26 | afafe01 | `foxstar_bot/router.py` |
| 2026-10-26 | 051a82a | `foxstar_bot/persistence.py` |
| 2026-10-26 | 9c3af46 | Checkpoint only |
| 2026-10-26 | 8097041 | Checkpoint only |

## 2026-11

| Date | Commit | Change |
| --- | --- | --- |
| 2026-11-04 | 9c85533 | Checkpoint only |
| 2026-11-04 | c5320c4 | Checkpoint only |
| 2026-11-04 | 74f27b9 | Checkpoint only |
| 2026-11-05 | e889f07 | Checkpoint only |
| 2026-11-08 | 3542722 | `foxstar_bot/context_store.py`, `foxstar_bot/limiter.py`, `foxstar_bot/persistence.py` |
