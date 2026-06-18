"""Offline sanity check: run the parser against a saved wetteronline.de page."""

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "wetteronline"))

import api  # noqa: E402

SAMPLE = Path.home() / "ha-wetteronline-recon" / "wetter_koeln.html"


def main() -> None:
    raw = SAMPLE.read_text(encoding="utf-8", errors="ignore")
    data = api.parse_weather(raw, now=date(2026, 6, 18))

    print("LOCATION:", data.location_name, "| lat/lon:", data.latitude, data.longitude)
    c = data.current
    print(
        "\nCURRENT:",
        f"temp={c.temperature} cond={c.condition!r}({c.condition_text!r})",
        f"wind={c.wind_description!r} bearing={c.wind_bearing} time={c.observation_time}",
    )
    a = data.astro
    print("ASTRO:", f"sunrise={a.sunrise} sunset={a.sunset} elevation={a.sun_elevation}")

    print(f"\nHOURLY: {len(data.hourly)} entries (first 6):")
    for h in data.hourly[:6]:
        print(
            f"  {h.datetime}  {h.temperature:>4}°  {str(h.condition):14}"
            f"  precip%={h.precipitation_probability}"
        )

    print(f"\nDAILY: {len(data.daily)} entries:")
    for d in data.daily:
        print(
            f"  {d.datetime}  max={d.temperature} min={d.templow}"
            f"  cond={str(d.condition):14} pop={d.precipitation_probability}"
            f"  mm={d.precipitation} sun={d.sun_hours}h"
            f"  windDir={d.wind_bearing} windKmh={d.wind_speed} gust={d.wind_gust_speed}"
        )

    # Basic assertions
    assert c.temperature is not None, "current temp missing"
    assert len(data.hourly) >= 24, "too few hourly entries"
    assert len(data.daily) >= 4, "too few daily entries"
    assert data.daily[0].temperature is not None, "day0 max missing"
    print("\nOK: basic assertions passed.")


if __name__ == "__main__":
    main()
