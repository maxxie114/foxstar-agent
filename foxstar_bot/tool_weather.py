from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass


GEOCODE_ENDPOINT = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_ENDPOINT = "https://api.open-meteo.com/v1/forecast"

WEATHER_CODE_TEXT = {
    0: "晴朗",
    1: "大致晴",
    2: "局部多云",
    3: "阴天",
    45: "雾",
    48: "冻雾",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "强毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨",
    81: "较强阵雨",
    82: "强阵雨",
    85: "阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}


@dataclass(frozen=True)
class WeatherResult:
    location_name: str
    country: str
    admin1: str
    timezone: str
    latitude: float
    longitude: float
    temperature_c: float | None
    apparent_temperature_c: float | None
    humidity_percent: float | None
    wind_speed_kmh: float | None
    wind_direction_deg: float | None
    wind_gusts_kmh: float | None
    precipitation_mm: float | None
    cloud_cover_percent: float | None
    pressure_msl_hpa: float | None
    weather_code: int | None
    weather_text: str
    is_day: bool | None
    today_max_c: float | None
    today_min_c: float | None


class OpenMeteoWeatherTool:
    def fetch_weather(self, location: str) -> WeatherResult:
        place = str(location or "").strip()
        if not place:
            raise ValueError("location is required")
        geo = self._geocode(place)
        forecast = self._forecast(float(geo["latitude"]), float(geo["longitude"]))
        current = forecast.get("current", {})
        daily = forecast.get("daily", {})
        weather_code = _to_int(current.get("weather_code"))
        return WeatherResult(
            location_name=str(geo.get("name") or place),
            country=str(geo.get("country") or ""),
            admin1=str(geo.get("admin1") or ""),
            timezone=str(forecast.get("timezone") or geo.get("timezone") or ""),
            latitude=float(geo["latitude"]),
            longitude=float(geo["longitude"]),
            temperature_c=_to_float(current.get("temperature_2m")),
            apparent_temperature_c=_to_float(current.get("apparent_temperature")),
            humidity_percent=_to_float(current.get("relative_humidity_2m")),
            wind_speed_kmh=_to_float(current.get("wind_speed_10m")),
            wind_direction_deg=_to_float(current.get("wind_direction_10m")),
            wind_gusts_kmh=_to_float(current.get("wind_gusts_10m")),
            precipitation_mm=_to_float(current.get("precipitation")),
            cloud_cover_percent=_to_float(current.get("cloud_cover")),
            pressure_msl_hpa=_to_float(current.get("pressure_msl")),
            weather_code=weather_code,
            weather_text=WEATHER_CODE_TEXT.get(weather_code or -1, "未知天气"),
            is_day=_to_int(current.get("is_day")) == 1 if current.get("is_day") is not None else None,
            today_max_c=_first_float(daily.get("temperature_2m_max")),
            today_min_c=_first_float(daily.get("temperature_2m_min")),
        )

    def _geocode(self, location: str) -> dict[str, object]:
        params = urllib.parse.urlencode({"name": location, "count": 1, "language": "zh", "format": "json"})
        payload = self._get_json(f"{GEOCODE_ENDPOINT}?{params}")
        results = payload.get("results") or []
        if not results:
            raise RuntimeError("location not found")
        return dict(results[0])

    def _forecast(self, latitude: float, longitude: float) -> dict[str, object]:
        params = urllib.parse.urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": ",".join(
                    [
                        "temperature_2m",
                        "relative_humidity_2m",
                        "apparent_temperature",
                        "is_day",
                        "precipitation",
                        "weather_code",
                        "cloud_cover",
                        "pressure_msl",
                        "wind_speed_10m",
                        "wind_direction_10m",
                        "wind_gusts_10m",
                    ]
                ),
                "daily": "temperature_2m_max,temperature_2m_min",
                "timezone": "auto",
                "forecast_days": 1,
            }
        )
        return self._get_json(f"{FORECAST_ENDPOINT}?{params}")

    @staticmethod
    def _get_json(url: str) -> dict[str, object]:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with opener.open(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))


def _to_float(value: object) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: object) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _first_float(values: object) -> float | None:
    if not isinstance(values, list) or not values:
        return None
    return _to_float(values[0])
