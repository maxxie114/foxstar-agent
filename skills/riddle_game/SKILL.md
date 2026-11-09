# Riddle Game

Use this skill when the user wants 猜谜语 / 猜灯谜 / 灯谜抢答.

Applicable cases:
- 猜谜语
- 猜灯谜
- 抢答谜语

Rules:

1. Treat this as a GM-led buzzer game.
2. If the user wants to start a game session, call `start_group_game` with `game="riddle"` first.
3. During the session, only the first correct answer for the current question gets the point.
4. Do not award partial credit.
5. Reveal the official answer when a round is won or when the game ends.
6. Keep the pacing fast and concise.

Behavior:

- Use the local riddle session state; do not invent hidden answers in plain text.
- Do not run web search for normal rounds.
- Announce winners clearly and keep a simple leaderboard.

Built-in local riddle bank includes common题型 such as:
- 字谜：一口咬掉牛尾巴 / 上下一体 / 十五天 / 四面都是山
- 物谜：桌子 / 冰箱 / 手套 / 桥 / 火车
- 自然类：彩虹 / 月亮 / 星星 / 雷 / 雨
- 食物植物类：花生 / 石榴 / 胡萝卜 / 玉米 / 蒜

The bank is randomized per session. Use the stored session questions instead of inventing your own mid-game.
