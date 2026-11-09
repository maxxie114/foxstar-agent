# Rock Paper Scissors

Use this skill when the user wants 剪刀石头布 / 石头剪刀布 / rock-paper-scissors / rps.

适用中文场景：
- 剪刀石头布
- 石头剪刀布
- rps

What to do:

1. Use the local `play_mini_game` tool with `game="rps"`.
2. Pass the user's choice as `choice`.
3. Do not fabricate the random result yourself.
4. After the tool result returns, you may add a short taunt or playful reaction.

Output guidance:

- Clearly show both sides' choices and the result.
- Keep it brief and lively.
- If game mode is on, keep the pace fast and avoid over-explaining.
- During a game session, only accept text moves `石头/布/剪刀` (or rock/paper/scissors); reject WeChat random emoji to avoid cheating.
