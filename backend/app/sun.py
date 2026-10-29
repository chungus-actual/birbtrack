"""Sunrise and sunset by the standard sunrise equation (good to a minute or two)."""

import math
from datetime import date, datetime, timedelta, timezone

J2000 = 2451545.0
_EPOCH = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)


def sun_times(d: date, lat: float, lon: float, tz):
    """(sunrise, sunset) as aware datetimes in tz, or (None, None) in polar day or night."""
    n = d.toordinal() - date(2000, 1, 1).toordinal()
    j_star = n - lon / 360.0                       # mean solar noon (lon: east positive)
    m = math.radians((357.5291 + 0.98560028 * j_star) % 360)
    c = 1.9148 * math.sin(m) + 0.0200 * math.sin(2 * m) + 0.0003 * math.sin(3 * m)
    lam = math.radians((math.degrees(m) + c + 180 + 102.9372) % 360)
    transit = J2000 + j_star + 0.0053 * math.sin(m) - 0.0069 * math.sin(2 * lam)
    sin_d = math.sin(lam) * math.sin(math.radians(23.4397))
    cos_d = math.cos(math.asin(sin_d))
    cos_w = ((math.sin(math.radians(-0.833)) - math.sin(math.radians(lat)) * sin_d)
             / (math.cos(math.radians(lat)) * cos_d))
    if not -1.0 <= cos_w <= 1.0:
        return None, None
    w = math.degrees(math.acos(cos_w)) / 360.0

    def at(j):
        return (_EPOCH + timedelta(days=j - J2000)).astimezone(tz)

    return at(transit - w), at(transit + w)
