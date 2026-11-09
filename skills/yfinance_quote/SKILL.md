# Yahoo Finance Quote Lookup

Use this skill when the user asks for a stock, ETF, index, or crypto price and explicitly wants a Yahoo Finance style lookup, or asks to use tools instead of generic web search.

适用中文场景：当用户要求“用 coding tool 查实时价格”“直接调 Yahoo Finance / yfinance API”“不要 web search”时，优先使用这个 skill。

Keywords:
- yfinance
- yahoo finance
- quote
- ticker
- stock price
- 实时价格
- 行情
- 股票
- 代码
- RSI
- MACD
- SMA
- EMA
- technical indicators

What to do:

1. First prefer the local `fetch_market_quote` tool. It uses the host machine network directly and avoids Daytona sandbox TLS / egress issues.
2. If the user wants technical analysis or indicators, use `fetch_market_indicators` instead. It computes a broad local indicator set for comprehensive financial analysis:
   - Trend: `SMA10/SMA20/SMA50/SMA100/SMA200`, `EMA9/EMA12/EMA20/EMA26/EMA50`
   - Momentum: `RSI14`, `ROC12`, `Momentum10`, `Stochastic %K/%D`, `Williams %R`, `CCI20`
   - Trend strength: `ADX14`, `+DI14`, `-DI14`, `MACD`, `MACD signal`, `MACD histogram`
   - Volatility / bands: `ATR14`, `Bollinger middle/upper/lower`, `Bollinger bandwidth`, `%B`
   - Volume / position: `AverageVolume20`, `OBV`, `VWAP`, `52w high/low`, `distance to SMA50/SMA200`
3. If the local tool succeeds, answer from that result and do not also run web search.
4. Only fall back to the bundled helper script + `run_python_code` if the user explicitly wants Daytona/coding-tool verification after the local tool fails.
5. If the helper reports that Yahoo endpoints are unreachable from the current sandbox, stop retrying the same method. Say clearly that the Yahoo route is blocked from the current Daytona environment. In this repo's current Daytona setup, even generic HTTPS probes may fail from one-shot code execution, so do not keep blaming only the ticker or URL.
6. Do not waste tool budget by repeatedly attempting `pip install yfinance`. The current Daytona code tool is stateless per invocation.

Output guidance:

- Prefer concise structured output: symbol, price, currency, market state, timestamp.
- For indicator requests, include interval/range and report the latest indicator values clearly. Summarize them by category instead of dumping an unreadable wall of numbers.
- If a symbol is invalid or Yahoo is unreachable, say that explicitly.
- If both the local tool and the Daytona route fail, say so plainly. Do not pretend the coding path worked.
- Do not silently substitute a different ticker.

Reference files are bundled below when you call `load_skill`.
