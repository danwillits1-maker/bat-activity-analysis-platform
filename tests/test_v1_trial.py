"""Independent supplied 1,000-contact trial for the simplified workflow."""
from datetime import date
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
import pandas as pd
from bat_activity.example import demo_project
from bat_activity.models import SurveyPeriod
from bat_activity.workflow import apply_v1_assumptions, apply_v1_data_assumption
from bat_activity.contacts import standardise_records, classify_records
from bat_activity.analysis import build_analysis
from bat_activity.exports import results_zip
from bat_activity.word_project import build_project_document, load_project_document


def test_willow_beck_preselected_periods_and_assumed_effort_roundtrip():
    folder = Path(__file__).resolve().parent / 'data/willow_beck'
    project = demo_project()
    project.site_name = 'Willow Beck Farm (synthetic)'
    project.deployment_end = date(2024,9,12)
    project.monitoring_periods = [SurveyPeriod(date(2024,m,8), date(2024,m,12)) for m in (5,7,9)]
    # Old unknown/partial entries must no longer block intended-window analysis.
    apply_v1_assumptions(project)
    assert len(project.selected_dates()) == 15
    assert len(project.coverage) == 30
    assert {r.status for r in project.coverage} == {'assumed_full'}
    raw = pd.read_csv(folder / 'all_1000_contacts_REFERENCE_ONLY.csv')
    records = classify_records(standardise_records(raw, 'combined.csv'), project)
    assert len(records) == 1000
    assert records.in_analysis.all(), records.exclude_reason.value_counts().to_dict()
    # Before an applied upload the legacy completeness gate remains available.
    for row in project.coverage:
        row.data_complete = False
    assert not build_analysis([(project, records)])['report_coverage'].report_included.any()
    apply_v1_data_assumption(project, upload_applied=True)
    assert all(r.completeness_assumed and not r.data_complete for r in project.coverage)
    tables = build_analysis([(project, records)])
    assert tables['total_contacts'].contacts.sum() == 1000
    assert tables['report_coverage'].report_included.sum() == 30
    by_round = records.groupby('survey_round').size().tolist()
    assert by_round == [402,333,265]
    expected = pd.read_csv(folder / 'expected_species_totals.csv')
    actual = tables['total_contacts'].set_index('species').contacts.sort_index()
    pd.testing.assert_series_equal(actual, expected.set_index('species').contacts.sort_index(), check_names=False, check_dtype=False)
    restored = load_project_document(build_project_document(project))
    assert {r.status for r in restored.coverage} == {'assumed_full'}
    assert len(restored.selected_dates()) == 15
    assert all(r.completeness_assumed and not r.data_complete for r in restored.coverage)
    archive = ZipFile(BytesIO(results_zip(tables, {}, project, records)))
    exported = pd.read_csv(archive.open('tables/report_coverage.csv'))
    assert exported.completeness_assumed.all()
    assert not exported.data_complete.any()
    assert 'confirmed_hours' not in exported
    assert set(exported.effort_basis) == {'assumed_intended_window'}
    assert 'not verified operational effort' in archive.read('calculation_notes.txt').decode()


def test_assumed_completeness_does_not_bypass_blocking_record_errors():
    from bat_activity.example import demo_records
    project = demo_project()
    apply_v1_assumptions(project)
    apply_v1_data_assumption(project, upload_applied=True)
    raw = demo_records()
    raw.loc[0, 'Timestamp'] = 'invalid'
    records = classify_records(standardise_records(raw, 'bad.csv'), project)
    audit = build_analysis([(project, records)])['report_coverage']
    affected = raw.loc[0, 'Detector']
    assert not audit.loc[audit.detector_id.eq(affected), 'report_included'].any()
