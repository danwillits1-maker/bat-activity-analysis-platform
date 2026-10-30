"""Free non-commercial EOX imagery, requested for the actual detector extent.

WMS 1.1.1 uses east/north order in EPSG:3857. No site coordinates are fixed.
"""
from functools import lru_cache
from io import BytesIO
import math
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image

RADIUS = 6378137.0
ATTRIBUTION = 'EOxCloudless https://cloudless.eox.at by EOX IT Services GmbH'
LICENCE = 'https://creativecommons.org/licenses/by-nc-sa/4.0/'
MAP_NOTE = (
    'Satellite background: EOxCloudless 2024, EOX IT Services GmbH '
    '(contains modified Copernicus Sentinel data 2024). '
    'https://cloudless.eox.at | CC BY-NC-SA 4.0: ' + LICENCE +
    ' Detector points, labels and map furniture added. '
    'The map figure is shared under CC BY-NC-SA 4.0 for non-commercial use. '
    'Imagery is approximately 10 m resolution; no site boundary is shown. '
    'Activity between detectors is not inferred.'
)


def mercator(longitude, latitude):
    if not (math.isfinite(longitude) and math.isfinite(latitude)
            and -180 <= longitude <= 180 and -85 <= latitude <= 85):
        raise ValueError('Location is outside the supported map coordinates.')
    return (RADIUS * math.radians(longitude),
            RADIUS * math.log(math.tan(math.pi / 4 + math.radians(latitude) / 2)))


def map_geometry(locations, width=920, height=500):
    points = [(row.detector_id, row.label, *mercator(row.longitude, row.latitude))
              for row in locations.itertuples()]
    xs, ys = [p[2] for p in points], [p[3] for p in points]
    lat0 = float(locations.latitude.mean())
    # Minimum 600 ground metres vertically; room for labels around edge points.
    span_y = max((max(ys) - min(ys)) * 1.7,
                 (max(xs) - min(xs)) * 1.7 * height / width,
                 600 / math.cos(math.radians(lat0)))
    span_x = span_y * width / height
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    return points, (cx-span_x/2, cy-span_y/2, cx+span_x/2, cy+span_y/2)


@lru_cache(maxsize=32)
def fetch_background(bounds, width=920, height=500):
    """Cache successful images only. Failures can be retried on the next rerun."""
    query = urlencode(dict(service='WMS', version='1.1.1', request='GetMap',
                          layers='s2cloudless-2024_3857', styles='', srs='EPSG:3857',
                          bbox=','.join(str(v) for v in bounds), width=width,
                          height=height, format='image/jpeg'))
    request = Request('https://tiles.maps.eox.at/map?' + query,
                      headers={'User-Agent': 'BatActivityPortfolio/1.0'})
    with urlopen(request, timeout=12) as response:
        payload = response.read(8_000_001)
    if len(payload) > 8_000_000:
        raise ValueError('Imagery response is too large.')
    with Image.open(BytesIO(payload)) as image:
        if image.size != (width, height):
            raise ValueError('Unexpected imagery dimensions.')
        image.load()
        # Return normalised bytes; service error/XML responses fail image decoding.
        output = BytesIO()
        image.convert('RGB').save(output, format='PNG')
    return output.getvalue()
