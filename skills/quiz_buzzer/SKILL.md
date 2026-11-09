# Quiz Buzzer

Use this skill when the user wants a 抢答问答 game such as:

- 常识问答
- AI基础知识问答
- 逆水寒问答
- quiz / trivia

Rules:

1. This is a GM-led buzzer game.
2. If the user wants to start a session, call `start_group_game` with one of:
   - `quiz_common`
   - `quiz_ai`
   - `quiz_nsh`
3. Each local question bank now has 100+ questions. Prefer the local bank first.
4. The first correct answer for the current question gets the point.
5. Use GM judgement strictly. Exact canonical answers are preferred, but standard aliases and obvious semantically equivalent short answers may count.
6. Keep the game moving. After a correct answer, reveal the official answer and immediately move to the next question.

Behavior:

- Do not use web search for ordinary quiz rounds.
- Use local session state for the current question.
- Keep the tone energetic and concise.
