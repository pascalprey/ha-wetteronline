"""Client and HTML parser for wetteronline.de.

WetterOnline serves its city weather page (``/wetter/<slug>``) as server-side
rendered HTML (Angular Universal).  All forecast numbers are present in the
static markup, so a single GET is enough -- no JavaScript execution required.

The page wraps several sections in *declarative shadow DOM*
(``<template shadowrootmode="open">``).  ``html.parser`` / ``lxml`` do not merge
those into the light DOM, so we strip the template wrappers before parsing
(``_flatten_shadow_dom``).  After that, plain CSS selectors reach every value.

This module is deliberately free of Home Assistant imports so the parser can be
unit-tested standalone against a saved HTML file.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

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

# --- Home Assistant weather conditions ---------------------------------------
# clear-night, cloudy, fog, hail, lightning, lightning-rainy, partlycloudy,
# pouring, rainy, snowy, snowy-rainy, sunny, windy, windy-variant, exceptional

# Map of WetterOnline German "alt" texts (lower-cased, substring matched, most
# specific first) to HA conditions.  Day/night for clear sky is refined via the
# symbol code prefix (``mo``/``mb`` == night) in :func:`_map_condition`.
_CONDITION_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("schneeregen", "snowy-rainy"),
    ("schneeschauer", "snowy"),
    ("schneefall", "snowy"),
    ("schnee", "snowy"),
    ("graupel", "hail"),
    ("hagel", "hail"),
    ("kräftiges gewitter", "lightning-rainy"),
    ("gewitter", "lightning-rainy"),
    ("gewittrig", "lightning"),
    ("starkregen", "pouring"),
    ("starker regen", "pouring"),
    ("regenschauer", "rainy"),
    ("schauer", "rainy"),
    ("regen", "rainy"),
    ("regnerisch", "rainy"),
    ("nieselregen", "rainy"),
    ("niesel", "rainy"),
    ("sprühregen", "rainy"),
    ("nebel", "fog"),
    ("neblig", "fog"),
    ("trüb", "cloudy"),
    ("bedeckt", "cloudy"),
    # More specific "... bewölkt" phrases must come before the bare "bewölkt".
    ("wechselnd bewölkt", "partlycloudy"),
    ("leicht bewölkt", "partlycloudy"),
    ("stark bewölkt", "cloudy"),
    ("bewölkt", "cloudy"),
    ("wolkig", "partlycloudy"),
    ("heiter", "partlycloudy"),
    ("stürmisch", "windy"),
    ("sturm", "windy"),
    ("windig", "windy"),
    ("klar", "clear-night"),
    ("sonnig", "sunny"),
)

# Beaufort number -> representative wind speed (km/h), rough scale midpoints.
_BEAUFORT_KMH = {
    0: 1, 1: 3, 2: 9, 3: 16, 4: 24, 5: 34, 6: 44,
    7: 56, 8: 68, 9: 81, 10: 95, 11: 109, 12: 120,
}


# --- data model --------------------------------------------------------------


@dataclass
class CurrentConditions:
    """The 'Wetter aktuell' nowcast block."""

    temperature: float | None = None
    condition: str | None = None
    condition_text: str | None = None  # original German, e.g. "sonnig"
    wind_bearing: float | None = None
    wind_description: str | None = None  # e.g. "schwacher Wind"
    observation_time: str | None = None  # local "HH:MM" as shown


@dataclass
class HourlyForecast:
    datetime: str | None = None  # ISO 8601 (local, naive -> HA localises)
    temperature: float | None = None
    condition: str | None = None
    precipitation_probability: int | None = None
    wind_bearing: float | None = None


@dataclass
class DailyForecast:
    datetime: str | None = None  # ISO date
    temperature: float | None = None  # daily max
    templow: float | None = None  # daily min
    condition: str | None = None
    precipitation_probability: int | None = None
    precipitation: float | None = None  # mm
    sun_hours: float | None = None
    wind_bearing: float | None = None
    wind_speed: float | None = None  # km/h, derived from Beaufort
    wind_gust_speed: float | None = None  # km/h


@dataclass
class Astro:
    sunrise: str | None = None  # local "HH:MM"
    sunset: str | None = None
    sun_elevation: float | None = None


@dataclass
class WeatherData:
    location_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    current: CurrentConditions = field(default_factory=CurrentConditions)
    hourly: list[HourlyForecast] = field(default_factory=list)
    daily: list[DailyForecast] = field(default_factory=list)
    astro: Astro = field(default_factory=Astro)


# --- helpers -----------------------------------------------------------------


def _flatten_shadow_dom(raw: str) -> str:
    """Remove declarative shadow DOM wrappers so the content joins the light DOM."""
    opens = raw.count("shadowrootmode")
    closes = raw.count("</template>")
    flat = re.sub(r'<template\s+shadowrootmode="[^"]*"\s*>', "", raw)
    # Only safe to drop every closing tag if all templates are shadow roots.
    if opens and opens == closes:
        flat = flat.replace("</template>", "")
    return flat


def _to_float(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", text)
    return float(m.group(0).replace(",", ".")) if m else None


def _beaufort_to_kmh(bft: str | None) -> tuple[int | None, int | None]:
    """Parse a Beaufort field like ``"2"`` or ``"3-4"`` -> (beaufort, km/h)."""
    if not bft:
        return None, None
    nums = [int(n) for n in re.findall(r"\d+", bft)]
    if not nums:
        return None, None
    bf = sum(nums) / len(nums)
    speeds = [_BEAUFORT_KMH.get(n) for n in nums if n in _BEAUFORT_KMH]
    speeds = [s for s in speeds if s is not None]
    kmh = round(sum(speeds) / len(speeds)) if speeds else None
    return round(bf), kmh


def _precip_range_to_mm(part: str) -> float:
    """``"0"`` -> 0.0, ``"2-5"`` -> 3.5 (midpoint of the mm range)."""
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", part)]
    if not nums:
        return 0.0
    return sum(nums) / len(nums)


def _map_condition(alt: str | None, code: str | None = None) -> str | None:
    """Map a WetterOnline alt text (+ optional symbol code) to an HA condition."""
    if not alt:
        return None
    low = alt.lower()
    night = bool(code and code[:2] in ("mo", "mb", "na", "nb"))
    for keyword, cond in _CONDITION_KEYWORDS:
        if keyword in low:
            if cond == "sunny" and night:
                return "clear-night"
            return cond
    return None


_WIND_WORDS = {
    "nord": 0, "nordnordost": 23, "nordost": 45, "ostnordost": 68,
    "ost": 90, "ostsüdost": 113, "südost": 135, "südsüdost": 158,
    "süd": 180, "südsüdwest": 203, "südwest": 225, "westsüdwest": 248,
    "west": 270, "westnordwest": 293, "nordwest": 315, "nordnordwest": 338,
}


def _wind_word_to_bearing(text: str) -> float | None:
    """'aus SüdOst' -> 135.  Longest match wins."""
    low = text.lower().replace("-", "").replace(" ", "")
    best: tuple[int, float] | None = None
    for word, deg in _WIND_WORDS.items():
        if word in low and (best is None or len(word) > best[0]):
            best = (len(word), deg)
    return best[1] if best else None


def _symbol_code(img) -> str | None:
    if img is None:
        return None
    m = re.search(r"weather-symbol/([^.?]+)\.svg", img.get("src", ""))
    return m.group(1) if m else None


# --- parsing -----------------------------------------------------------------


def _parse_js_array(raw: str, key: str) -> list[str]:
    """Extract a ``WO.metadata.p_city_weather.<key> = [...]`` string array."""
    m = re.search(r"p_city_weather\." + re.escape(key) + r"\s*=\s*(\[.*?\]);", raw, re.S)
    if not m:
        return []
    try:
        return [str(x) for x in json.loads(m.group(1))]
    except (ValueError, TypeError):
        # Fall back to a lenient split on quoted items.
        return re.findall(r'"([^"]*)"', m.group(1))


def _date_from_label(label: str, ref: date) -> date | None:
    """'Do, 18.06.' -> date, choosing the year closest to ``ref``."""
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.", label)
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    for year in (ref.year, ref.year + 1, ref.year - 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if abs((d - ref).days) <= 200:
            return d
    return None


def parse_weather(raw_html: str, *, now: date | None = None) -> WeatherData:
    """Parse a wetteronline.de city page into a :class:`WeatherData`."""
    ref = now or date.today()
    raw = html_lib.unescape(raw_html)
    flat = _flatten_shadow_dom(raw)
    soup = BeautifulSoup(flat, "html.parser")

    data = WeatherData()
    _parse_geo(raw, data)
    _parse_current(soup, raw, data)
    _parse_astro(soup, raw, data)
    _parse_hourly(soup, ref, data)
    _parse_daily(soup, raw, ref, data)
    return data


def _parse_geo(raw: str, data: WeatherData) -> None:
    m = re.search(r"WO\.geo\s*=\s*\{(.*?)\};", raw, re.S)
    if not m:
        return
    block = m.group(1)
    name = re.search(r'locationname\s*:\s*"([^"]*)"', block)
    lat = re.search(r"lat\s*:\s*(-?\d+(?:\.\d+)?)", block)
    lon = re.search(r"lon\s*:\s*(-?\d+(?:\.\d+)?)", block)
    if name:
        data.location_name = name.group(1)
    if lat:
        data.latitude = float(lat.group(1))
    if lon:
        data.longitude = float(lon.group(1))


def _parse_current(soup: BeautifulSoup, raw: str, data: WeatherData) -> None:
    cur = data.current
    section = soup.select_one("wo-nowcast-card section")
    aria = section.get("aria-label", "") if section else ""
    # "Wetter aktuell 28° , sonnig, schwacher Wind, aus SüdOst in Köln, ...,
    #  Nordrhein-Westfalen, Ortszeit Donnerstag, 18.06., 11:37"
    if aria:
        parts = [p.strip() for p in aria.split(",")]
        # temperature
        mt = re.search(r"(-?\d+)\s*°", aria)
        if mt:
            cur.temperature = float(mt.group(1))
        # condition word is usually the 2nd comma-part
        if len(parts) > 1 and parts[1]:
            cur.condition_text = parts[1]
            cur.condition = _map_condition(parts[1])
        # wind description ("... Wind") and direction ("aus ...")
        for p in parts:
            if "wind" in p.lower():
                cur.wind_description = p
            if p.lower().startswith("aus "):
                cur.wind_bearing = _wind_word_to_bearing(p[4:])
        mtime = re.search(r"(\d{1,2}:\d{2})", aria)
        if mtime:
            cur.observation_time = mtime.group(1)

    if cur.temperature is None:
        at = soup.find(class_="air-temp")
        cur.temperature = _to_float(at.get_text() if at else None)


def _parse_astro(soup: BeautifulSoup, raw: str, data: WeatherData) -> None:
    sun = soup.find("wo-sun-information")
    if sun:
        times = re.findall(r"\d{1,2}:\d{2}", sun.get_text(" ", strip=True))
        if len(times) >= 2:
            data.astro.sunrise, data.astro.sunset = times[0], times[1]
    elev = re.search(r'WO\.solarelevation\s*=\s*"([^"]*)"', raw)
    if elev and elev.group(1):
        data.astro.sun_elevation = _to_float(elev.group(1))


def _parse_hourly(soup: BeautifulSoup, ref: date, data: WeatherData) -> None:
    hours = soup.find_all("wo-forecast-hour")
    current_day = ref
    prev_hour = -1
    for h in hours:
        hr_el = h.find("wo-date-hour")
        if not hr_el:
            continue
        hm = re.search(r"(\d{1,2}):(\d{2})", hr_el.get_text())
        if not hm:
            continue
        hour = int(hm.group(1))
        if hour < prev_hour:  # rolled over midnight
            current_day = current_day + timedelta(days=1)
        prev_hour = hour
        temp_el = h.select_one(".temperature")
        sym = h.find("img", class_="symbol")
        prec = h.find("wo-weather-characteristics-precipitation")
        entry = HourlyForecast(
            datetime=datetime.combine(
                current_day, datetime.min.time()
            ).replace(hour=hour).isoformat(),
            temperature=_to_float(temp_el.get_text() if temp_el else None),
            condition=_map_condition(sym.get("alt") if sym else None, _symbol_code(sym)),
            precipitation_probability=(
                int(_to_float(prec.get_text()) or 0) if prec else None
            ),
        )
        data.hourly.append(entry)


def _parse_daily(
    soup: BeautifulSoup, raw: str, ref: date, data: WeatherData
) -> None:
    # 1) Long-term temperature series: the first cell's SVG text carries all
    #    days as "max max min min" repeated.
    temps: list[tuple[float | None, float | None]] = []
    cell = soup.find("wo-long-term-temperature-cell")
    if cell:
        nums = [int(n) for n in re.findall(r"-?\d+", cell.get_text(" ", strip=True))]
        # groups of 4: max, max, min, min
        for i in range(0, len(nums) - 3, 4):
            temps.append((float(nums[i]), float(nums[i + 2])))

    # 2) Wind + precipitation arrays, keyed by index (day 0 == today).
    winds = _parse_js_array(raw, "ttwind")
    precs = _parse_js_array(raw, "ttprecipitation")

    # 3) Gust km/h from the long-term strip (best effort, aligned to the tail).
    gusts = []
    for g in soup.find_all("wo-long-term-gust"):
        gusts.append(_to_float(g.get_text(" ", strip=True)))

    # 4) Medium-term blocks give condition / sun / precip probability for ~4 days.
    medium = soup.find_all("wo-medium-term-weather")
    mt_info: list[dict] = []
    for mt in medium:
        sun = mt.find("wo-weather-characteristics-sun")
        pre = mt.find("wo-weather-characteristics-precipitation")
        sym = mt.find("img", class_="symbol")
        mt_info.append(
            {
                "sun_hours": _to_float(sun.get_text() if sun else None),
                "precip_prob": (
                    int(_to_float(pre.get_text()) or 0) if pre else None
                ),
                "condition": _map_condition(
                    sym.get("alt") if sym else None, _symbol_code(sym)
                ),
            }
        )

    # The temperature series is the authoritative day count (each forecast day
    # needs a temperature); fall back to the wind/precip arrays if it is absent.
    n_days = len(temps) if temps else max(len(winds), len(precs))
    for i in range(n_days):
        day = DailyForecast()
        # date: prefer the wind/precip label, else offset from today
        label = winds[i] if i < len(winds) else (precs[i] if i < len(precs) else "")
        d = _date_from_label(label, ref) or (ref + timedelta(days=i))
        day.datetime = d.isoformat()

        if i < len(temps):
            day.temperature, day.templow = temps[i]

        if i < len(winds):
            fields = winds[i].split("|")
            if len(fields) >= 3:
                bearing = _to_float(fields[1])
                day.wind_bearing = bearing if bearing != -999 else None
                bf, kmh = _beaufort_to_kmh(fields[2])
                day.wind_speed = kmh
            if len(fields) >= 5:
                gkmh = _to_float(fields[4])
                day.wind_gust_speed = gkmh if gkmh and gkmh != -999 else None

        if i < len(precs):
            fields = precs[i].split("|")
            if len(fields) >= 2:
                day.precipitation = round(
                    sum(_precip_range_to_mm(p) for p in fields[1].split(":")), 1
                )

        if i < len(mt_info):
            day.condition = mt_info[i]["condition"]
            day.precipitation_probability = mt_info[i]["precip_prob"]
            day.sun_hours = mt_info[i]["sun_hours"]

        if day.wind_gust_speed is None and i < len(gusts):
            day.wind_gust_speed = gusts[i]

        data.daily.append(day)

    # Derive the "current" condition from the first hourly entry if the nowcast
    # text did not resolve to a known HA condition.
    if data.current.condition is None and data.hourly:
        data.current.condition = data.hourly[0].condition


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
        """Resolve a free-text query to one or more location slugs.

        Uses ``/autosuggest`` for clean, disambiguated names and ``/search`` to
        map a name onto its ``/wetter/<slug>`` URL.
        """
        query = query.strip()
        if not query:
            return []

        # Primary: the search endpoint already yields the slug directly.
        results = await self._search_slugs(query)
        if results:
            return results

        # Fallback: take the top autosuggest name and resolve that.
        suggestions = await self._autosuggest(query)
        for name in suggestions:
            res = await self._search_slugs(name)
            if res:
                # Prefer the suggestion's (more descriptive) name.
                return [LocationResult(name=name, slug=res[0].slug)]
        return []

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
            # The search fragment's anchor text is often a generic "hier";
            # fall back to a slug-derived display name in that case.
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
        names: list[str] = []
        for item in payload or []:
            if isinstance(item, dict) and item.get("n"):
                names.append(str(item["n"]))
        return names
