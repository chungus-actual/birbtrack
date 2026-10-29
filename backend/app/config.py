"""birbTrack settings, all from the environment (see .env.example)."""

import ipaddress
import os
from pathlib import Path
from zoneinfo import ZoneInfo

SITE = "birbTrack"
BNG_URL = os.environ.get("BT_BNG_URL", "http://birdnet-go:8080").rstrip("/")
DATA = Path(os.environ.get("BT_DATA", "/data"))
STATIC = Path(os.environ.get("BT_STATIC", "/app/frontend/dist"))
DB_PATH = DATA / "birbtrack.db"
IMAGES = DATA / "images"
# where Discord links and link previews point
PUBLIC_URL = os.environ.get("BT_PUBLIC_URL", "http://localhost:8894").rstrip("/")
TZ = ZoneInfo(os.environ.get("TZ", "UTC"))
# the station: BT_LAT/BT_LON, or BirdNET-Go's own location when unset (place.py). Sunrise, sunset and
# the map only; coordinates are never served.
LAT = float(os.environ["BT_LAT"]) if os.environ.get("BT_LAT") else None
LON = float(os.environ["BT_LON"]) if os.environ.get("BT_LON") else None
# the range map: americas, europe, africa, asia, oceania, or auto (the one holding the station)
REGION = os.environ.get("BT_REGION", "auto")
# how link previews name the place: "a backyard in Tucson"
PLACE = os.environ.get("BT_PLACE", "a backyard")

DISCORD_WEBHOOK = os.environ.get("BT_DISCORD_WEBHOOK", "")
DISCORD_NAME = os.environ.get("BT_DISCORD_NAME", "birbTrack")
NOTIFY = {k.strip() for k in os.environ.get("BT_NOTIFY", "lifer,comeback,weekly").split(",") if k.strip()}
COMEBACK_DAYS = int(os.environ.get("BT_COMEBACK_DAYS", "30"))
# this long with nothing heard at all is the station being off, not the birds being away
OUTAGE_DAYS = int(os.environ.get("BT_OUTAGE_DAYS", "7"))
WEEKLY_DAY = int(os.environ.get("BT_WEEKLY_DAY", "0"))      # 0 = Monday
WEEKLY_HOUR = int(os.environ.get("BT_WEEKLY_HOUR", "1"))
QUIET_START = int(os.environ.get("BT_QUIET_START", "22"))   # posts in quiet hours go out silent
QUIET_END = int(os.environ.get("BT_QUIET_END", "7"))

# requests from these peers may name the real client (a reverse proxy on the docker network, a CDN in front)
TRUSTED_PROXIES = [ipaddress.ip_network(n) for n in
                   os.environ.get("BT_TRUSTED_PROXIES", "172.16.0.0/12 127.0.0.0/8").split()]
RATE_PER_MIN = int(os.environ.get("BT_RATE_PER_MIN", "240"))
LIVE_MAX = int(os.environ.get("BT_LIVE_MAX", "200"))
LIVE_PER_IP = int(os.environ.get("BT_LIVE_PER_IP", "4"))
