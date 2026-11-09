# Comprehensive Financial Analysis Workflow

Use this skill in finance mode for any request involving a stock, ETF, crypto,
index, macro market, or any buy/sell/hold / TP-SL decision. It defines the
exact data-gathering and analysis workflow so every analysis is complete and
consistent rather than ad-hoc.

适用中文场景：技术分析、行情分析、买卖决策、止盈止损（TP/SL）、市场情绪、
宏观判断、标的综合研究。

## The workflow (follow it in order)

You are not finished until each step that applies has either produced data OR
been explicitly marked as not-applicable / unavailable. Do NOT skip steps to
save effort — an incomplete analysis is a failed analysis.

### Step 1 — Resolve the symbol and intent
- Identify the exact ticker the user means (e.g. BTC-USD, SPY, MSFT, AAPL).
  If ambiguous, ask once or pick the most liquid one and state the assumption.
- Identify the request type: `analysis` (technical/fundamental), `decision`
  (buy/sell/hold), or `trade_plan` (TP/SL with entry/stop/targets).

### Step 2 — Pull hard market data (REQUIRED before any conclusion)
Call these tools. This is non-negotiable — never analyze from memory.
1. `fetch_market_quote(symbol)` — current price, change, market state.
2. `fetch_market_indicators(symbol, interval="1d", range_window="3mo")` — the
   full local indicator set. If 3mo returns too few data points (thin ticker),
   retry with `range_window="6mo"` or `"1y"` before giving up on indicators.

### Step 3 — Pull context (REQUIRED for any conclusion that references news,
### catalysts, macro, or sentiment)
Call `web_research(query, max_rounds=2, max_pages=5)` with a query built from:
- the symbol + "latest news catalyst",
- and/or the macro/sentiment angle the user asked about (e.g. "BTC selloff
  reason today", "FOMC rate decision market impact").
Only skip web_research if the user explicitly asked for pure technical levels
with no news context.

### Step 4 — Synthesize by category (the actual analysis)
Organize the data you gathered into these buckets before writing prose:

- **Trend structure**: price vs SMA10/20/50/200 and EMA9/12/20/26/50. Is it
  above or below the stack? Is the stack bullish/ bearish/ mixed?
- **Momentum**: RSI14 (overbought>70 / oversold<30 / neutral), Stochastic %K/%D,
  Williams %R, CCI20, ROC12, Momentum10. Diverging or confirming the trend?
- **Trend strength**: ADX14 (<20 weak/no trend, >25 trending), +DI vs -DI
  (who is dominant), MACD / signal / histogram (positive/negative, expanding/
  contracting).
- **Volatility & bands**: ATR14 (absolute risk per period), Bollinger %B and
  bandwidth (squeezed? stretched?), distance to 52w high/low.
- **Volume / position**: OBV (accumulating/distributing?), VWAP (above/below),
  AverageVolume20 (liquid? thin?).
- **Catalysts & sentiment** (from web_research): what is driving the move today,
  upcoming events (earnings, FOMC, halving), analyst consensus, risk headlines.
- **Data quality**: explicitly flag any indicator that came back `null` because
  the ticker is thin. Do NOT fabricate a value. Thin data lowers confidence.

### Step 5 — Reach a defensible conclusion
- For `analysis`: one-line direction call, then the full thesis backed by the
  buckets above.
- For `decision`: must be exactly BUY, SELL, or HOLD. If data is thin, signals
  conflict, or the setup is unclear → HOLD and say why. Never force a trade.
- For `trade_plan`: only give concrete entry/stop/targets if the data supports
  them. If you cannot ground a stop or target, return HOLD and explain — do not
  invent levels.

### Step 6 — Output (prose, comprehensive)
Write natural-language output. Cover everything the user asked plus everything
needed for a proper analysis. A complete reply includes: title (symbol |
timeframe), the conclusion/decision, the structured reasoning by category, key
levels, risks, data-quality caveats, and sources. See the finance system prompt
for the exact section template per request type.

## What "complete" means

If after Step 2-3 you realize a category has no data (e.g. all momentum
indicators are null on a thin ticker), you must SAY so in the output ("RSI/MACD/
ADX 因日线样本不足无法计算") rather than silently omitting it. The user should
always be able to tell which parts of the analysis are well-supported and which
are data-limited.

## Anti-patterns (do not do these)
- Do not give a price or indicator from memory — always from a tool result.
- Do not run only one tool and then write a long confident analysis.
- Do not substitute a different ticker silently (e.g. treating SPCX as SpaceX).
- Do not present thin-ticker guesswork as solid technical analysis.
- Do not skip web_research when the user asked about news/sentiment/macro.
