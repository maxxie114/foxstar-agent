# Local Fortune

Use this skill when the user asks for daily fortune, zodiac fortune, horoscope, huangli, divination, 梅花易数, or a combined daily luck reading.

适用中文场景：
- 今日运势
- 星座运势
- 黄历
- 占卜 / 卦象 / 梅花易数
- 每日运势总结

Keywords:
- fortune
- horoscope
- zodiac
- constellation
- almanac
- divination
- 运势
- 星座
- 黄历
- 占卜
- 卦象
- 梅花易数

What to do:

1. First use the local `get_daily_fortune` tool.
2. Prefer local deterministic output over generic improvisation.
3. Treat the local tool output as the factual base, not as the final wording.
4. After the tool succeeds, rewrite the answer in a fresh, slightly dynamic conversational style for that day:
   - keep the same sign/date/core advice
   - you may compress, rearrange, and paraphrase
   - add light personality and flow so repeated queries do not sound mechanically identical
   - do not invent contradictory details
   - do not add finance/trading/investment wording such as 开市, 纳财, 财神, explicit buy/sell language, or消费建议
5. If the user only wants fortune, answer from the local tool result plus light paraphrase and stop.
6. If the user explicitly wants a richer "today context" version, you may optionally add one `web_research` call after the local fortune succeeds.
7. Web research is only for public daily context, such as:
   - today's major public news
   - broad market mood
   - general atmosphere
8. Do not use web search as a replacement for the local fortune result.
9. Do not use Daytona or `run_python_code` for fortune unless the user explicitly asks to inspect or verify the local algorithm.

Output guidance:

- Keep the local result recognizable and structured.
- Make the final wording feel less templated across different users and signs.
- If you enrich with web research, clearly separate:
  - local fortune result
  - public-context add-on
- Do not claim scientific certainty.
- Treat it as entertainment / lifestyle guidance unless the user explicitly asks for a different framing.

Reference files are bundled below when you call `load_skill`.
