"""Check that the copy-ready Word output contains calculated values and charts."""
from io import BytesIO

import pandas as pd
from docx import Document
from docx.oxml.ns import qn

from bat_activity.analysis import build_analysis
from bat_activity.contacts import classify_records, standardise_records
from bat_activity.example import demo_project, demo_records
from bat_activity.figures import reporting_figures
from bat_activity.word_results import build_results_document
from bat_activity.workflow import apply_v1_assumptions, apply_v1_data_assumption


def test_satellite_figure_and_credits_survive_word_export(monkeypatch):
    from PIL import Image
    from zipfile import ZipFile
    output = BytesIO()
    Image.new('RGB', (920, 500), '#556633').save(output, format='PNG')
    monkeypatch.setattr('bat_activity.figures.fetch_background', lambda bounds: output.getvalue())
    project = demo_project()
    rows = classify_records(standardise_records(demo_records()), project)
    tables = build_analysis([(project, rows)])
    figures = reporting_figures(tables, imagery=True)
    payload = build_results_document(tables, figures, project)
    document = Document(BytesIO(payload))
    text = '\n'.join(p.text for p in document.paragraphs)
    assert 'EOxCloudless 2024' in text and 'CC BY-NC-SA 4.0' in text
    with ZipFile(BytesIO(payload)) as archive:
        images = [archive.read(n) for n in archive.namelist() if n.startswith('word/media/')]
    assert figures['detector_locations']['png'] in images


def test_word_has_editable_tables_embedded_charts_and_method_limits():
    project = demo_project()
    apply_v1_assumptions(project)
    apply_v1_data_assumption(project, True)
    rows = classify_records(standardise_records(demo_records()), project)
    tables = build_analysis([(project, rows)])
    figures = reporting_figures(tables)
    original = tables['summary'].copy(deep=True)
    document = Document(BytesIO(build_results_document(tables, figures, project)))
    text = '\n'.join(p.text for p in document.paragraphs)
    assert '16 contacts included' in text
    assert 'missing records can understate activity' in text
    assert len(document.inline_shapes) == 5
    totals = next(t for t in document.tables if t.cell(0, 0).text == 'Species or identification group')
    assert sum(int(r.cells[1].text) for r in totals.rows[1:]) == 16
    assert not list(document.styles['Title'].element.iter(qn('w:pBdr')))
    for shape in document.inline_shapes:
        assert shape.width <= document.sections[0].page_width - document.sections[0].left_margin - document.sections[0].right_margin
    pd.testing.assert_frame_equal(original, tables['summary'])


def test_empty_activity_and_missing_weather_remain_explicit_in_word():
    project = demo_project()
    project.weather = []
    apply_v1_assumptions(project)
    apply_v1_data_assumption(project, True)
    rows = classify_records(standardise_records(demo_records().iloc[:0]), project)
    tables = build_analysis([(project, rows)])
    document = Document(BytesIO(build_results_document(tables, reporting_figures(tables), project)))
    assert len(document.inline_shapes) == 2  # Map and empty survey comparison.
    cells = [c.text for t in document.tables for r in t.rows for c in r.cells]
    assert 'Not supplied' in cells
    assert not {'nan', '<NA>', 'None'}.intersection(cells)
