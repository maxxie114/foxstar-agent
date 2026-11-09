# Signup Roster Compare

Use this skill when the user asks to compare a guild roster against a signup / RSVP / attendance list and produce counts, missing names, leave requests, substitutes, or role-based summaries.

适用中文场景：当用户要求对比帮众名单和接龙名单，统计接龙人数、未接龙、请假、替补，或按职业/名单做汇总时，必须优先使用这个 skill。

Keywords:
- signup
- roster
- attendance
- RSVP
- guild
- 帮众名单
- 接龙名单
- 接龙统计
- 请假
- 替补
- 未接龙

Required workflow:

1. First call `load_skill("signup_roster_compare")` and follow this workflow. Do not skip it.
2. Use `search_knowledge_base` to retrieve the official roster section from `knowledge.md`.
3. Parse the current user message and any quoted content to extract the signup list text.
4. If the roster or signup list is long, use the bundled helper code from this skill as the starting point for `run_python_code` instead of hand-writing a huge script from scratch.
5. Prefer exact player-name matching first. Only use fuzzy matching when the message clearly contains aliases or obvious typos.
6. When reporting results, separate:
   - total signed up
   - missing roster members
   - leave / unavailable
   - substitutes / backup
   - 接龙总人数
   - 未接龙名单
   - 请假名单
   - 替补名单
7. If the pasted signup text is incomplete or truncated, say so explicitly instead of pretending the count is final.

Failure policy:

- If `run_python_code` fails, do not bluff a final count from memory or rough eyeballing.
- If tool input/code is truncated, malformed, or execution returns an error, explicitly say the calculation did not complete reliably.
- Do not retry the same broken method repeatedly. Change method once at most.
- If you cannot complete a reliable count, return a partial diagnostic answer instead of a fake final answer.

Output guidance:

- Keep the final answer structured and easy to scan.
- Do not invent missing names.
- If alias mapping is uncertain, mark it as "needs manual confirmation".
- If the result is partial or uncertain, label it clearly.

Reference files are bundled below when you call `load_skill`.
