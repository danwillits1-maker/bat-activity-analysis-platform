from io import BytesIO
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import pandas as pd
import pytest
from PIL import Image

from bat_activity import basemap, figures


def locations(latitude=52, longitude=-1):
    return pd.DataFrame([
        dict(detector_id='RC1', label='North hedge', latitude=latitude, longitude=longitude),
        dict(detector_id='RC2', label='South field', latitude=latitude-.002, longitude=longitude+.003),
    ])


@pytest.mark.parametrize('latitude,longitude', [(50.2, -5.3), (52, -1), (55, -7), (60.2, -1.3)])
def test_new_uk_locations_are_inside_automatically_framed_extent(latitude, longitude):
    points, (left, bottom, right, top) = basemap.map_geometry(locations(latitude, longitude))
    assert (right-left)/(top-bottom) == pytest.approx(920/500)
    for _, _, x, y in points:
        assert left < x < right
        assert bottom < y < top
    _, old = basemap.map_geometry(locations())
    if latitude != 52:
        assert old != (left, bottom, right, top)


def test_projection_known_origin_and_single_point_extent():
    assert basemap.mercator(0, 0) == pytest.approx((0, 0), abs=1e-8)
    _, bounds = basemap.map_geometry(locations().iloc[:1])
    assert bounds[2] > bounds[0]
    assert bounds[3] > bounds[1]


def test_actual_request_axes_decoding_and_success_cache(monkeypatch):
    output = BytesIO()
    Image.new('RGB', (920, 500), '#556633').save(output, format='JPEG')
    calls = []

    def fake_open(request, timeout):
        calls.append(request.full_url)
        query = parse_qs(urlparse(request.full_url).query)
        assert query['srs'] == ['EPSG:3857']
        assert query['version'] == ['1.1.1']
        assert query['bbox'] == ['1,2,3,4']
        assert timeout == 12
        return BytesIO(output.getvalue())

    monkeypatch.setattr(basemap, 'urlopen', fake_open)
    basemap.fetch_background.cache_clear()
    try:
        image = basemap.fetch_background((1, 2, 3, 4))
        assert image == basemap.fetch_background((1, 2, 3, 4))
        assert len(calls) == 1
        assert Image.open(BytesIO(image)).size == (920, 500)
    finally:
        basemap.fetch_background.cache_clear()


def test_background_overlay_labels_licence_and_self_contained_svg(monkeypatch):
    output = BytesIO()
    Image.new('RGB', (920, 500), '#556633').save(output, format='PNG')
    monkeypatch.setattr(figures, 'fetch_background', lambda bounds: output.getvalue())
    result = figures.location_map(locations(), imagery=True)
    svg = result['svg'].decode()
    ElementTree.fromstring(svg)
    assert 'data:image/png;base64,' in svg
    assert 'North hedge' in svg and 'South field' in svg
    assert 'CC BY-NC-SA 4.0' in svg
    assert '2024' in figures.map_caption(result)
    assert Image.open(BytesIO(result['png'])).getpixel((41, 101)) == (85, 102, 51)


def test_service_failure_preserves_plain_map_and_explanation(monkeypatch):
    def fail(bounds):
        raise OSError('Service unavailable')
    monkeypatch.setattr(figures, 'fetch_background', fail)
    result = figures.location_map(locations(), imagery=True)
    assert b'<image ' not in result['svg']
    assert 'Satellite imagery unavailable' in figures.map_caption(result)
    assert b'North hedge' in result['svg']
