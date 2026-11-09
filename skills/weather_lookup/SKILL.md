# Weather Lookup

Use this skill when the user asks for current weather, temperature, humidity, rain, wind, or today's high/low in any city worldwide.

What to do:

1. Use the local `fetch_weather` tool first.
2. Prefer direct weather lookup over web search for normal current-weather requests.
3. If the user asks for weather news, storms in the headlines, or source comparison, then web search can be a follow-up.

Output guidance:

- Include place name clearly.
- Report current temperature, apparent temperature, humidity, wind, precipitation, and today's high/low when available.
- Keep the answer compact unless the user explicitly wants a detailed forecast.

Implementation note:

- The local weather tool uses Open-Meteo geocoding + forecast APIs.
- No API key is required.
- It supports Chinese and international place names.
