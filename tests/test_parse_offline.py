"""Offline sanity check: run the parser against a saved wetteronline.de page."""

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "wetteronline"))

import api  # noqa: E402

SAMPLE = Path.home() / "ha-wo-audit" / "bb.html"


def main() -> None:
    raw = SAMPLE.read_text(encoding="utf-8", errors="ignore")
    data = api.parse_weather(raw, now=date(2026, 6, 18))

    print("LOCATION:", data.location_name, "| lat/lon:", data.latitude, data.longitude)
    c = data.current
    print("\nCURRENT:")
    print(f"  temp={c.temperature} apparent={c.apparent_temperature} dewpoint={c.dew_point}")
    print(f"  humidity={c.humidity}% pressure={c.pressure}hPa tendency={c.pressure_tendency}")
    print(f"  cond={c.condition!r}({c.condition_text!r}) precip%={c.precipitation_probability}")
    print(f"  wind={c.wind_speed}km/h gust={c.wind_gust_speed} bearing={c.wind_bearing}")
    print(f"  visibility={c.visibility}km smog={c.smog_level} solar_elev={c.solar_elevation}")

    a = data.astro
    print(f"\nASTRO: sunrise={a.sunrise} sunset={a.sunset} daylen={a.day_length}"
          f" moonphase={a.moon_phase_age} moonrise={a.moonrise}")

    print(f"\nHOURLY: {len(data.hourly)} entries (first 3):")
    for h in data.hourly[:3]:
        print(f"  {h.datetime} {h.temperature}° app={h.apparent_temperature} "
              f"dp={h.dew_point} hum={h.humidity}% p={h.pressure} {h.condition} "
              f"pop={h.precipitation_probability} wind={h.wind_speed} vis={h.visibility}")

    print(f"\nDAILY: {len(data.daily)} entries (first 4):")
    for d in data.daily[:4]:
        print(f"  {d.datetime} max={d.temperature} min={d.templow} app={d.apparent_temperature} "
              f"hum={d.humidity} p={d.pressure} uv={d.uv_index} sun={d.sunshine_hours}h "
              f"({d.sunshine_relative}%) {d.condition} pop={d.precipitation_probability} "
              f"mm={d.precipitation} wind={d.wind_speed} gust={d.wind_gust_speed}")

    print(f"\nPOLLEN: {len(data.pollen)} days; today levels:")
    if data.pollen:
        for name, lvl in data.pollen[0].levels.items():
            if lvl:
                print(f"  {name}: {lvl} ({api.POLLEN_LEVELS.get(lvl)})")

    print(f"\nWARNINGS: {len(data.warnings)}")
    print(f"WATER TEMP: {data.water_temperature} °C")
    print(f"UV DESC (today): {getattr(data.daily[0], 'uv_description', None)}")
    print(f"CONVECTION (h0): {data.hourly[0].convection_probability}%")
    print(f"PRECIP TYPE (now): {data.current.precipitation_type}")
    print(f"SIG WEATHER (today): {data.daily[0].significant_weather}")
    print(f"FORECAST TEXT: {(data.forecast_text or '')[:90]}...")

    assert c.temperature is not None, "current temp missing"
    assert c.pressure is not None, "pressure missing"
    assert c.humidity is not None, "humidity missing"
    assert c.apparent_temperature is not None, "apparent temp missing"
    assert c.dew_point is not None, "dew point missing"
    assert len(data.hourly) >= 24, "too few hourly entries"
    assert len(data.daily) >= 7, "too few daily entries"
    assert data.daily[0].uv_index is not None, "uv missing"
    assert len(data.pollen) >= 1, "pollen missing"
    print("\nOK: assertions passed.")


if __name__ == "__main__":
    main()
