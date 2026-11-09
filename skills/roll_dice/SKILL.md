# Roll Dice

Use this skill when the user wants to roll dice, throw a die, test luck, or do a simple random tabletop-style roll.

适用中文场景：
- 扔筛子
- 掷骰子
- 骰一下
- 来个 d20

What to do:

1. Use the local `play_mini_game` tool with `game="dice"`.
2. If the user specifies count or sides, pass them through.
3. Do not invent dice outcomes in plain text.
4. After the tool result returns, you can add short playful commentary.

Output guidance:

- Show the actual rolls and total.
- Keep it quick and playful.
- If the group is in game mode, keep the pace fast.
- During a dice game session, only accept text triggers like `骰子`, `继续`, or `roll`; do not treat WeChat random emoji as valid moves.
- Do not run web search.
