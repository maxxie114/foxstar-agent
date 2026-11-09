import json
import urllib.error
import urllib.parse
import urllib.request

SYMBOLS = ["NVDA"]
ENDPOINT = "https://query1.finance.yahoo.com/v7/finance/quote?symbols="


def fetch_quotes(symbols: list[str]) -> dict:
    encoded = urllib.parse.quote(",".join(symbols))
    url = ENDPOINT + encoded
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    results = []
    for item in payload.get("quoteResponse", {}).get("result", []):
        results.append(
            {
                "symbol": item.get("symbol"),
                "shortName": item.get("shortName"),
                "regularMarketPrice": item.get("regularMarketPrice"),
                "regularMarketChange": item.get("regularMarketChange"),
                "regularMarketChangePercent": item.get("regularMarketChangePercent"),
                "currency": item.get("currency"),
                "marketState": item.get("marketState"),
                "regularMarketTime": item.get("regularMarketTime"),
            }
        )
    return {"ok": True, "quotes": results}


if __name__ == "__main__":
    try:
        print(json.dumps(fetch_quotes(SYMBOLS), ensure_ascii=False))
    except urllib.error.HTTPError as exc:
        print(json.dumps({"ok": False, "error": f"Yahoo HTTP error: {exc.code} {exc.reason}"}, ensure_ascii=False))
    except Exception as exc:
        message = str(exc)
        if "Connection reset by peer" in message or "SSL" in message or "TLS" in message:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "Yahoo endpoint unreachable from current Daytona sandbox (TLS / connection reset). Stop retrying this same method and report the environment limitation.",
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
