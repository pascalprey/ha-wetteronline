"""Client and parser for wetteronline.de.

The city page (``/wetter/<slug>``) is server-side rendered (Angular Universal)
and embeds an Angular *TransferState* blob — ``<script id="ng-state">`` — that
contains the cached responses of WetterOnline's own backend API
(``api-web.wo-cloud.com``).  That JSON is far richer and far more stable than the
rendered DOM, so we parse it instead of scraping HTML elements:

* ``/blending/shortcast/`` -> current conditions + hourly (~48 h)
* ``/blending/forecast/``  -> daily (up to 14 days)
* ``/astro/days/``         -> sunrise/sunset, moon
* ``/pollen/v4``           -> pollen forecast (14 allergens)
* ``/warnings/``           -> severe-weather warnings

A second blob — ``<script id="wo-global-json">`` — carries per-day precipitation
amount (mm) and relative sunshine duration, which are not in ``ng-state``.

This module is free of Home Assistant imports so the parser can be unit-tested
standalone against a saved HTML file.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime

import aiohttp
from bs4 import BeautifulSoup

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.wetteronline.de"

# A normal desktop browser UA.  We identify as a browser (the site blocks
# obvious bot UAs at the WAF) but do NOT rotate UAs or otherwise actively evade
# protection -- we poll politely and infrequently.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 30

# Canonical order of the 14 pollen allergens WetterOnline reports.
POLLEN_ALLERGENS = (
    "Gräser", "Ampfer", "Wegerich", "Eiche", "Beifuß", "Ambrosia", "Ulme",
    "Birke", "Buche", "Weide", "Roggen", "Pappel", "Esche", "Erle",
)

# Pollen burden level (0-3) -> human label.
POLLEN_LEVELS = {0: "keine", 1: "gering", 2: "mittel", 3: "hoch"}

# weather_condition_image (only present on `current`) -> HA condition.
_CONDITION_BY_IMAGE = {
    "sunny": "sunny",
    "clear": "clear-night",
    "clear-night": "clear-night",
    "partly-cloudy": "partlycloudy",
    "partlycloudy": "partlycloudy",
    "cloudy": "cloudy",
    "overcast": "cloudy",
    "fog": "fog",
    "foggy": "fog",
    "rain": "rainy",
    "rainy": "rainy",
    "showers": "rainy",
    "heavy-rain": "pouring",
    "thunderstorm": "lightning-rainy",
    "lightning": "lightning",
    "snow": "snowy",
    "snowy": "snowy",
    "sleet": "snowy-rainy",
    "hail": "hail",
}


# --- data model --------------------------------------------------------------


@dataclass
class CurrentConditions:
    temperature: float | None = None
    apparent_temperature: float | None = None
    dew_point: float | None = None
    humidity: int | None = None  # %
    pressure: float | None = None  # hPa
    pressure_tendency: int | None = None  # -1/0/1 category
    wind_bearing: float | None = None
    wind_speed: float | None = None  # km/h
    wind_gust_speed: float | None = None  # km/h
    condition: str | None = None
    condition_text: str | None = None  # German, e.g. "sonnig"
    precipitation_probability: int | None = None
    precipitation_type: str | None = None  # rain / snow / ...
    smog_level: str | None = None
    solar_elevation: float | None = None
    visibility: float | None = None  # km


@dataclass
class HourlyForecast:
    datetime: str | None = None
    temperature: float | None = None
    apparent_temperature: float | None = None
    dew_point: float | None = None
    humidity: int | None = None
    pressure: float | None = None
    condition: str | None = None
    precipitation_probability: int | None = None
    convection_probability: int | None = None  # thunderstorm likelihood %
    wind_bearing: float | None = None
    wind_speed: float | None = None
    wind_gust_speed: float | None = None
    visibility: float | None = None


@dataclass
class DailyForecast:
    datetime: str | None = None
    temperature: float | None = None  # max
    templow: float | None = None  # min
    apparent_temperature: float | None = None  # max
    humidity: int | None = None
    pressure: float | None = None
    uv_index: int | None = None
    uv_description: str | None = None  # e.g. "moderate", "very_high"
    sunshine_hours: float | None = None
    sunshine_relative: int | None = None  # % of possible sunshine
    condition: str | None = None
    precipitation_probability: int | None = None
    precipitation: float | None = None  # mm
    precipitation_type: str | None = None  # rain / snow / ...
    significant_weather: str | None = None  # significant_weather_index
    wind_bearing: float | None = None
    wind_speed: float | None = None
    wind_gust_speed: float | None = None
    smog_level: str | None = None


@dataclass
class Astro:
    sunrise: str | None = None  # ISO
    sunset: str | None = None
    day_length: str | None = None  # e.g. "16:00"
    moon_phase_age: int | None = None  # days
    moonrise: str | None = None
    moonset: str | None = None
    solar_elevation: float | None = None


@dataclass
class PollenDay:
    date: str | None = None
    levels: dict[str, int] = field(default_factory=dict)


@dataclass
class Warning:
    type: str | None = None
    level: int | None = None
    headline: str | None = None
    start: str | None = None
    end: str | None = None


@dataclass
class WeatherData:
    location_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    current: CurrentConditions = field(default_factory=CurrentConditions)
    hourly: list[HourlyForecast] = field(default_factory=list)
    daily: list[DailyForecast] = field(default_factory=list)
    astro: Astro = field(default_factory=Astro)
    pollen: list[PollenDay] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)
    water_temperature: float | None = None  # °C of nearby water, if any
    forecast_text: str | None = None  # today's prose forecast (copyrighted)


# --- value helpers -----------------------------------------------------------


def _num(value) -> float | None:
    """Coerce ``"10"`` / ``10`` / ``10.5`` -> float, anything else -> None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _celsius(d) -> float | None:
    return _num(d.get("celsius")) if isinstance(d, dict) else None


def _humidity(value) -> int | None:
    n = _num(value)
    return round(n * 100) if n is not None else None


def _probability(d) -> int | None:
    if not isinstance(d, dict):
        return None
    n = _num(d.get("probability"))
    return round(n * 100) if n is not None else None


def _percent(value) -> int | None:
    """Fraction (0.7) -> 70."""
    n = _num(value)
    return round(n * 100) if n is not None else None


def _pressure(d) -> float | None:
    return _num(d.get("hpa")) if isinstance(d, dict) else None


def _visibility_km(d) -> float | None:
    if not isinstance(d, dict):
        return None
    m = _num(d.get("meter"))
    return round(m / 1000, 1) if m is not None else None


def _wind(d) -> tuple[float | None, float | None, float | None]:
    """(bearing, speed_kmh, gust_kmh) from a WetterOnline wind dict."""
    if not isinstance(d, dict):
        return None, None, None
    bearing = _num(d.get("direction"))
    kmh = d.get("speed", {}).get("kilometer_per_hour", {}) if d.get("speed") else {}
    return bearing, _num(kmh.get("value")), _num(kmh.get("max_gust"))


def _condition(symbol: str | None, image: str | None = None) -> str | None:
    """Map a WetterOnline symbol code (+ optional condition image) to HA."""
    if image:
        norm = str(image).lower().replace("_", "-")
        if norm in _CONDITION_BY_IMAGE:
            return _CONDITION_BY_IMAGE[norm]
    if not symbol:
        return None
    code = symbol.lower()
    sky = code[:2]
    rest = code[2:].replace("_", "")
    night = sky.startswith("m")
    if "g" in rest:  # Gewitter (thunderstorm)
        return "lightning-rainy" if ("r" in rest or "s" in rest) else "lightning"
    if "n" in rest:  # Schnee
        return "snowy"
    if "s" in rest or "r" in rest:  # Schauer / Regen
        return "pouring" if "3" in rest else "rainy"
    if sky == "so":
        return "sunny"
    if sky == "mo":
        return "clear-night"
    if sky in ("wb", "mb"):
        return "partlycloudy"
    if sky in ("bw", "bd", "bm", "tr", "ns"):
        return "cloudy"
    return "clear-night" if night else "partlycloudy"


# --- parsing -----------------------------------------------------------------


def _load_state(soup: BeautifulSoup, script_id: str) -> dict:
    sc = soup.find("script", attrs={"id": script_id})
    if not sc or not sc.string:
        return {}
    try:
        return json.loads(sc.string)
    except (ValueError, TypeError):
        return {}


def _find(state: dict, substr: str):
    for key, value in state.items():
        if substr in key:
            return value
    return None


def parse_weather(raw_html: str, *, now: date | None = None) -> WeatherData:
    """Parse a wetteronline.de city page into a :class:`WeatherData`."""
    soup = BeautifulSoup(raw_html, "html.parser")
    state = _load_state(soup, "ng-state")
    globals_ = _load_state(soup, "wo-global-json")

    data = WeatherData()
    _parse_geo(raw_html, data)
    _parse_current(_find(state, "/blending/shortcast/"), data)
    _parse_hourly(_find(state, "/blending/shortcast/"), data)
    _parse_daily(_find(state, "/blending/forecast/"), globals_, data)
    _parse_astro(_find(state, "/astro/days/"), data, now)
    _parse_pollen(_find(state, "/pollen/v4"), data)
    _parse_warnings(_find(state, "/warnings/"), data)
    _parse_water(_find(state, "weather/water"), data, now)
    _parse_text(_find(state, "/blending/texts/"), data, now)
    return data


def _parse_geo(raw: str, data: WeatherData) -> None:
    m = re.search(r"WO\.geo\s*=\s*\{(.*?)\};", html_lib.unescape(raw), re.S)
    if not m:
        return
    block = m.group(1)
    name = re.search(r'locationname\s*:\s*"([^"]*)"', block)
    lat = re.search(r"lat\s*:\s*(-?\d+(?:\.\d+)?)", block)
    lon = re.search(r"lon\s*:\s*(-?\d+(?:\.\d+)?)", block)
    if name and name.group(1):
        data.location_name = name.group(1)
    if lat:
        data.latitude = float(lat.group(1))
    if lon:
        data.longitude = float(lon.group(1))


def _parse_current(short: dict | None, data: WeatherData) -> None:
    if not isinstance(short, dict):
        return
    cur = short.get("current")
    if not isinstance(cur, dict):
        return
    c = data.current
    c.temperature = _celsius(cur.get("air_temperature"))
    c.apparent_temperature = _celsius(cur.get("apparent_temperature"))
    c.dew_point = _celsius(cur.get("dew_point"))
    c.humidity = _humidity(cur.get("humidity"))
    c.pressure = _pressure(cur.get("air_pressure"))
    c.pressure_tendency = cur.get("air_pressure_tendency_category")
    c.wind_bearing, c.wind_speed, c.wind_gust_speed = _wind(cur.get("wind"))
    c.condition = _condition(cur.get("symbol"), cur.get("weather_condition_image"))
    c.precipitation_probability = _probability(cur.get("precipitation"))
    if isinstance(cur.get("precipitation"), dict):
        c.precipitation_type = cur["precipitation"].get("type")
    c.smog_level = cur.get("smog_level")
    c.solar_elevation = _num(cur.get("solar_elevation"))
    c.visibility = _visibility_km(cur.get("visibility"))
    trend = short.get("nowcast_trend")
    if isinstance(trend, dict):
        c.condition_text = trend.get("description")


def _parse_hourly(short: dict | None, data: WeatherData) -> None:
    if not isinstance(short, dict):
        return
    for h in short.get("hours", []) or []:
        if not isinstance(h, dict):
            continue
        bearing, speed, gust = _wind(h.get("wind"))
        data.hourly.append(
            HourlyForecast(
                datetime=h.get("date"),
                temperature=_celsius(h.get("air_temperature")),
                apparent_temperature=_celsius(h.get("apparent_temperature")),
                dew_point=_celsius(h.get("dew_point")),
                humidity=_humidity(h.get("humidity")),
                pressure=_pressure(h.get("air_pressure")),
                condition=_condition(h.get("symbol"), h.get("weather_condition_image")),
                precipitation_probability=_probability(h.get("precipitation")),
                convection_probability=_percent(h.get("convection_probability")),
                wind_bearing=bearing,
                wind_speed=speed,
                wind_gust_speed=gust,
                visibility=_visibility_km(h.get("visibility")),
            )
        )


def _parse_daily(
    forecast: dict | None, globals_: dict, data: WeatherData
) -> None:
    if not isinstance(forecast, dict):
        return
    # Per-day precipitation amount (mm) and relative sunshine live in the
    # separate wo-global-json blob, aligned by index (both start today).
    longterm = globals_.get("metadata_p_city_local_LongTerm", []) if globals_ else []

    for i, d in enumerate(forecast.get("days", []) or []):
        if not isinstance(d, dict):
            continue
        bearing, speed, gust = _wind(d.get("wind"))
        temp = d.get("air_temperature", {}) if isinstance(d.get("air_temperature"), dict) else {}
        app = d.get("apparent_temperature", {}) if isinstance(d.get("apparent_temperature"), dict) else {}
        uv = d.get("uv_index", {}) if isinstance(d.get("uv_index"), dict) else {}
        sun = d.get("sunshine_duration", {}) if isinstance(d.get("sunshine_duration"), dict) else {}

        day = DailyForecast(
            datetime=d.get("date"),
            temperature=_celsius(temp.get("max")),
            templow=_celsius(temp.get("min")),
            apparent_temperature=_celsius(app.get("max")),
            humidity=_humidity(d.get("humidity")),
            pressure=_pressure(d.get("air_pressure")),
            uv_index=_int(uv.get("value")),
            uv_description=uv.get("description"),
            sunshine_hours=_num(sun.get("hours")),
            condition=_condition(d.get("symbol"), d.get("weather_condition_image")),
            precipitation_probability=_probability(d.get("precipitation")),
            precipitation_type=(
                d["precipitation"].get("type")
                if isinstance(d.get("precipitation"), dict)
                else None
            ),
            significant_weather=d.get("significant_weather_index"),
            wind_bearing=bearing,
            wind_speed=speed,
            wind_gust_speed=gust,
            smog_level=d.get("smog_level"),
        )
        if i < len(longterm) and isinstance(longterm[i], dict):
            day.precipitation = _num(longterm[i].get("precipitationAmount24"))
            day.sunshine_relative = _int(longterm[i].get("relativeSunshineDuration"))
        data.daily.append(day)


def _parse_astro(astro: dict | None, data: WeatherData, now: date | None) -> None:
    if not isinstance(astro, dict):
        return
    days = astro.get("days", []) or []
    ref = (now or date.today()).isoformat()
    chosen = None
    for d in days:
        if isinstance(d, dict) and str(d.get("date", "")).startswith(ref):
            chosen = d
            break
    if chosen is None and days:
        chosen = days[len(days) // 2]  # fall back to a middle (≈ today) entry
    if not isinstance(chosen, dict):
        return
    sun = chosen.get("sun", {}) or {}
    moon = chosen.get("moon", {}) or {}
    data.astro.sunrise = sun.get("rise")
    data.astro.sunset = sun.get("set")
    data.astro.day_length = _iso_duration_to_hhmm(sun.get("day_length"))
    data.astro.moon_phase_age = _int(moon.get("age"))
    data.astro.moonrise = moon.get("rise")
    data.astro.moonset = moon.get("set")


def _parse_pollen(pollen: dict | None, data: WeatherData) -> None:
    if not isinstance(pollen, dict):
        return
    for d in pollen.get("days", []) or []:
        if not isinstance(d, dict):
            continue
        levels = {}
        for item in d.get("pollen", []) or []:
            if isinstance(item, dict) and item.get("name") is not None:
                levels[item["name"]] = _int(item.get("value")) or 0
        data.pollen.append(PollenDay(date=d.get("date"), levels=levels))


def _parse_warnings(warnings, data: WeatherData) -> None:
    items = None
    if isinstance(warnings, dict):
        items = warnings.get("warnings") or warnings.get("items") or warnings.get("dynamic")
    elif isinstance(warnings, list):
        items = warnings
    for w in items or []:
        if not isinstance(w, dict):
            continue
        data.warnings.append(
            Warning(
                type=w.get("type") or w.get("event"),
                level=_int(w.get("level") or w.get("severity")),
                headline=w.get("headline") or w.get("title"),
                start=w.get("start") or w.get("start_time"),
                end=w.get("end") or w.get("end_time"),
            )
        )


def _parse_water(water: dict | None, data: WeatherData, now: date | None) -> None:
    """Nearby water (lake/sea) temperature, when WetterOnline reports one."""
    if not isinstance(water, dict):
        return
    days = water.get("days", []) or []
    ref = (now or date.today()).isoformat()
    chosen = next(
        (d for d in days if isinstance(d, dict) and str(d.get("date", "")).startswith(ref)),
        days[0] if days else None,
    )
    if isinstance(chosen, dict):
        temp = chosen.get("temperature", {}) or {}
        data.water_temperature = _num(temp.get("water"))


def _parse_text(texts, data: WeatherData, now: date | None) -> None:
    """Today's prose forecast text (note: this is copyrighted WetterOnline content)."""
    if not isinstance(texts, list):
        return
    ref = (now or date.today()).isoformat()
    chosen = next(
        (t for t in texts if isinstance(t, dict) and str(t.get("date", "")).startswith(ref)),
        texts[0] if texts else None,
    )
    if isinstance(chosen, dict) and chosen.get("text"):
        # Strip the inline <WO...>value</WO...> template tags, keeping the value.
        data.forecast_text = re.sub(r"</?WO[^>]*>", "", chosen["text"]).strip()


def _int(value) -> int | None:
    n = _num(value)
    return int(n) if n is not None else None


def _iso_duration_to_hhmm(value) -> str | None:
    """'PT16H00M' -> '16:00'."""
    if not value:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", str(value))
    if not m:
        return None
    h = int(m.group(1) or 0)
    mi = int(m.group(2) or 0)
    return f"{h:02d}:{mi:02d}"


# --- async client ------------------------------------------------------------


class WetterOnlineError(Exception):
    """Base error for the WetterOnline client."""


class WetterOnlineConnectionError(WetterOnlineError):
    """Network / HTTP error talking to wetteronline.de."""


@dataclass
class LocationResult:
    """A resolved location candidate from the search/autosuggest endpoints."""

    name: str
    slug: str  # URL fragment, e.g. "koeln" for /wetter/koeln


class WetterOnlineClient:
    """Thin async client around the public wetteronline.de pages.

    Polite by design: identifies as a normal browser, no UA rotation, and is
    only driven by the integration's (infrequent) update coordinator.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _get(self, url: str, **params) -> aiohttp.ClientResponse:
        try:
            resp = await self._session.get(
                url,
                params=params or None,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "de-DE,de;q=0.9",
                },
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            )
            resp.raise_for_status()
            return resp
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise WetterOnlineConnectionError(str(err)) from err

    async def async_fetch_html(self, slug: str) -> str:
        """Fetch the raw city-page HTML for a location slug."""
        resp = await self._get(f"{BASE_URL}/wetter/{slug}")
        return await resp.text()

    async def async_search_locations(self, query: str) -> list[LocationResult]:
        """Resolve a free-text query to candidate locations for disambiguation.

        Uses ``/autosuggest`` for distinct, region-qualified names (e.g.
        "Neustadt, Brandenburg" vs "Neustadt, Bayern"), then resolves each to its
        ``/wetter/<slug>`` URL so the user can pick the right one.
        """
        query = query.strip()
        if not query:
            return []

        results: list[LocationResult] = []
        seen_slugs: set[str] = set()
        seen_names: set[str] = set()
        for name in await self._autosuggest(query):
            if name in seen_names:
                continue
            seen_names.add(name)
            slugs = await self._search_slugs(name)
            if slugs and slugs[0].slug not in seen_slugs:
                seen_slugs.add(slugs[0].slug)
                results.append(LocationResult(name=name, slug=slugs[0].slug))
        if results:
            return results

        # Fallback: the search endpoint's own best match.
        return await self._search_slugs(query)

    async def _search_slugs(self, query: str) -> list[LocationResult]:
        resp = await self._get(
            f"{BASE_URL}/search",
            ireq="true",
            pid="p_search",
            searchstring=query,
        )
        text = html_lib.unescape(await resp.text())
        out: list[LocationResult] = []
        seen: set[str] = set()
        for m in re.finditer(r'href="/wetter/([^"?]+)"[^>]*>([^<]*)', text):
            slug = m.group(1).strip("/")
            label = re.sub(r"\s+", " ", m.group(2)).strip()
            if label.lower() in ("", "hier"):
                label = slug.replace("-", " ").title()
            if slug and slug not in seen:
                seen.add(slug)
                out.append(LocationResult(name=label, slug=slug))
        return out

    async def _autosuggest(self, query: str) -> list[str]:
        resp = await self._get(
            f"{BASE_URL}/autosuggest",
            ireq="true",
            pid="a_autosuggest",
            s=query,
        )
        try:
            payload = await resp.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError):
            return []
        return [str(i["n"]) for i in payload or [] if isinstance(i, dict) and i.get("n")]
