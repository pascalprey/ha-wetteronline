"""Constants for the WetterOnline integration."""

from __future__ import annotations

DOMAIN = "wetteronline"

# Configuration / option keys
CONF_SLUG = "slug"
CONF_LOCATION_NAME = "location_name"
CONF_SCAN_INTERVAL = "scan_interval"

# Update cadence (minutes).  WetterOnline refreshes forecasts only a few times a
# day, so polling more often than this is pointless and impolite.
DEFAULT_SCAN_INTERVAL_MIN = 30
MIN_SCAN_INTERVAL_MIN = 10
MAX_SCAN_INTERVAL_MIN = 360

ATTRIBUTION = "Wetterdaten von wetteronline.de"
MANUFACTURER = "WetterOnline"
