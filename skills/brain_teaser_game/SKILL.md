# brain_teaser_game

Use this skill when the group wants to play a brain-teaser / 脑筋急转弯 buzzer game.

Rules:

- Start the session with `start_group_game(game="brain_teaser")`.
- Do not start the game in plain chat before the session exists.
- Once the session starts, the GM should present one question at a time.
- The first correct answer gets the point.
- Keep the round interactive and concise.
- At the end of the session, show the leaderboard.
- If the user wants to stop, use `end_group_game`.

Behavior:

- Do not web search.
- Do not improvise new answers once the local question bank is active.
- Use the local game state as the source of truth for scores and round progression.
