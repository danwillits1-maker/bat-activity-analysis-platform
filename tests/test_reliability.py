from datetime import date, datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from docx import Document

from bat_activity.contacts import classify_records, contact_counts, match_detectors_by_coordinates, nightly_activity, standardise_records
from bat_activity.example import demo_project, demo_records
from bat_activity.exports import excel_bytes
from bat_activity.nights import candidate_blocks, localise_timestamp, survey_night_table, suggested_survey_period
from bat_activity.solar import hours_between
from bat_activity.validation import validation_issues
from bat_activity.weather import parse_weather_csv, weather_template
from bat_activity.word_project import build_project_document, load_project_document
from bat_activity.workflow import coverage_errors, project_errors, synchronise_coverage


def test_original_rows_and_file_name_survive_non_default_index():
    raw = demo_records().iloc[[1, 6]].copy()
    raw['Review notes'] = ['first', 'second']
    standard = standardise_records(raw, 'reviewed.csv')
    assert len(standard) == 2
    assert standard.source_file.tolist() == ['reviewed.csv', 'reviewed.csv']
    assert standard.source_row.tolist() == [2, 3]
    assert standard['raw:Review notes'].tolist() == ['first', 'second']
    assert standard.timestamp.notna().all()


def test_reused_recording_name_survives_across_detectors_and_nights():
    raw = demo_records().iloc[[1, 7, 9, 9]].reset_index(drop=True)
    raw['Recording'] = 'same.wav'
    classified = classify_records(standardise_records(raw), demo_project())
    assert classified.in_analysis.tolist() == [True, True, True, False]
    assert contact_counts(classified).contacts.sum() == 3


def test_incomplete_upload_cannot_produce_zeros_or_rates():
    project = demo_project()
    for row in project.coverage:
        row.data_complete = False
    classified = classify_records(standardise_records(demo_records().iloc[[1]]), project)
    activity = nightly_activity(classified, survey_night_table(project))
    selected = activity.loc[activity.in_selected_block]
    assert selected.activity_rate_per_hour.isna().all()
    assert not selected.activity_included.any()
    assert (selected.zero_vs_missing == 'reviewed_data_not_confirmed_complete').all()
    assert selected.contacts.notna().sum() == 1
    assert 'reviewed_data_not_confirmed_complete' in validation_issues(classified, project).issue.tolist()


def test_independently_worked_two_contacts_over_four_hours():
    # Independently specified arithmetic: two contacts / four operational
    # hours = 0.5 contacts per hour. The third row is an excluded duplicate.
    classified = pd.DataFrame({
        'evening_date': [date(2024, 5, 8)] * 3, 'detector_id': ['A'] * 3,
        'species': ['Myotis sp.', 'Pipistrellus sp.', 'Myotis sp.'],
        'in_analysis': [True, True, False],
    })
    nights = pd.DataFrame({
        'evening_date': [date(2024, 5, 8)] * 3, 'detector_id': ['A', 'B', 'C'],
        'in_selected_block': [True] * 3, 'confirmed_hours': [4.0, 4.0, 0.0],
        'data_complete': [True, True, True],
    })
    activity = nightly_activity(classified, nights).set_index('detector_id')
    assert activity.loc['A', 'contacts'] == 2
    assert activity.loc['A', 'activity_rate_per_hour'] == 0.5
    assert activity.loc['B', 'activity_rate_per_hour'] == 0
    assert pd.isna(activity.loc['C', 'activity_rate_per_hour'])


def test_confirmed_empty_dataset_is_zero_only_for_confirmed_effort():
    project = demo_project()
    project.coverage[-1].status = 'failed'
    activity = nightly_activity(pd.DataFrame(), survey_night_table(project))
    selected = activity.loc[activity.in_selected_block]
    assert (selected.loc[selected.confirmed_hours > 0, 'contacts'] == 0).all()
    assert selected.loc[selected.confirmed_hours == 0, 'contacts'].isna().all()
    assert selected.loc[selected.confirmed_hours == 0, 'activity_rate_per_hour'].isna().all()


def test_rejected_timestamp_cannot_turn_into_confirmed_zero():
    project = demo_project()
    raw = demo_records().iloc[[1]].copy()
    raw.Timestamp = 'not a timestamp'
    classified = classify_records(standardise_records(raw), project)
    activity = nightly_activity(classified, survey_night_table(project))
    selected = activity.loc[activity.in_selected_block & activity.detector_id.eq('RC1')]
    assert selected.contacts.isna().all()
    assert selected.activity_rate_per_hour.isna().all()
    assert (selected.zero_vs_missing == 'unresolved_record_errors').all()


@pytest.mark.parametrize('start,end,expected', [
    ('2024-03-30T20:00', '2024-03-31T07:00', 10),
    ('2024-10-26T20:00', '2024-10-27T07:00', 12),
])
def test_elapsed_hours_match_independent_clock_change_example(start, end, expected):
    tz = ZoneInfo('Europe/London')
    assert hours_between(datetime.fromisoformat(start).replace(tzinfo=tz), datetime.fromisoformat(end).replace(tzinfo=tz)) == expected
    assert 12 / hours_between(datetime.fromisoformat(start).replace(tzinfo=tz), datetime.fromisoformat(end).replace(tzinfo=tz)) == 12 / expected


@pytest.mark.parametrize('timestamp', ['2024-03-31T01:30', '2024-10-27T01:30'])
def test_ambiguous_and_nonexistent_detector_times_require_an_offset(timestamp):
    with pytest.raises(ValueError, match='explicit UTC offset'):
        localise_timestamp(datetime.fromisoformat(timestamp), 'Europe/London')


def test_both_repeated_hours_are_kept_when_offsets_are_explicit():
    project = demo_project()
    project.deployment_start = project.deployment_end = date(2024, 10, 26)
    project.selected_start = project.selected_end = project.deployment_start
    project.coverage = []
    synchronise_coverage(project)
    for row in project.coverage:
        row.status = 'full'
    raw = pd.DataFrame({
        'Timestamp': ['2024-10-27T01:30:00+01:00', '2024-10-27T01:30:00+00:00', '2024-10-27 01:30:00'],
        'Species Text': ['Myotis sp.'] * 3, 'Recording': ['a', 'b', 'c'], 'Detector': ['RC1'] * 3,
    })
    classified = classify_records(standardise_records(raw), project)
    assert classified.in_analysis.tolist() == [True, True, False]
    assert classified.iloc[2].exclude_reason == 'ambiguous_or_nonexistent_local_time'
    assert len(excel_bytes({'rows': classified})) > 1000


def test_mixed_iso_formats_parse_but_day_month_order_is_not_guessed():
    raw = demo_records().iloc[:3].copy()
    raw.Timestamp = ['2024-05-08 21:45:00', '2024-05-08T21:46:00', '08/05/2024 21:47']
    assert standardise_records(raw).timestamp.notna().tolist() == [True, True, False]


def test_unknown_supplied_detector_is_not_silently_reassigned():
    raw = demo_records().iloc[[1]].copy()
    raw.Detector = 'WRONG'
    frame = match_detectors_by_coordinates(standardise_records(raw), demo_project())
    assert frame.iloc[0].detector_id == 'WRONG'
    assert classify_records(frame, demo_project()).iloc[0].exclude_reason == 'unknown_detector'


def test_missing_weather_is_visible_and_does_not_crash():
    project = demo_project()
    project.weather = parse_weather_csv('evening_date,temp_min_c,rain_mm\n2024-05-08,,0.2\n')
    blocks = candidate_blocks(project)
    assert blocks.temperature_nights_supplied.tolist() == [0, 0, 0]
    assert blocks.rainfall_nights_supplied.tolist() == [1, 1, 1]
    assert blocks.mean_temp_min_c.isna().all()
    assert (blocks.total_rain_mm == 0.2).all()


def test_weather_suggestion_prefers_driest_then_warmest_complete_period():
    project = demo_project()
    assert suggested_survey_period(candidate_blocks(project, 5))['start'] == date(2024, 5, 8)
    # 8–10 and 9–11 May both have 0.5 mm; the latter is warmer.
    assert suggested_survey_period(candidate_blocks(project, 3))['start'] == date(2024, 5, 9)
    # An incomplete dry-looking period cannot win through missing rainfall.
    project.weather[4].rain_mm = None
    assert suggested_survey_period(candidate_blocks(project, 5)) is None


def test_weather_suggestion_exact_tie_uses_earliest_start():
    project = demo_project()
    for row in project.weather:
        row.temp_min_c = 10
        row.rain_mm = 0
    assert suggested_survey_period(candidate_blocks(project))['start'] == date(2024, 5, 6)


def test_weather_round_trip_preserves_commas_and_source_notes():
    project = demo_project()
    project.weather[0].source = 'station, example'
    project.weather[0].notes = 'cold, wet\nchecked manually'
    assert parse_weather_csv(weather_template(project)) == project.weather


@pytest.mark.parametrize('csv', [
    'evening_date,temp_min_c\n2024-05-08,1\n2024-05-08,2',
    'evening_date,rain_mm\n2024-05-08,-1',
    'evening_date,rain_mm\n2024-05-08,inf',
])
def test_invalid_weather_is_rejected(csv):
    with pytest.raises(ValueError):
        parse_weather_csv(csv)


def test_word_preserves_all_fields_and_old_files_default_to_unconfirmed():
    project = demo_project()
    payload = build_project_document(project)
    assert load_project_document(payload) == project
    doc = Document(BytesIO(payload))
    table = next(t for t in doc.tables if t.cell(0, 0).text == 'coverage_evening_date')
    # The oldest records had four columns: no confirmation or assumption.
    for row in table.rows:
        while len(row.cells) > 4:
            row._tr.remove(row.cells[-1]._tc)
    buffer = BytesIO()
    doc.save(buffer)
    old_project = load_project_document(buffer.getvalue())
    assert not any(row.data_complete for row in old_project.coverage)


def test_new_detector_nights_are_unknown_not_confirmed_working():
    project = demo_project()
    project.coverage = []
    synchronise_coverage(project)
    assert len(project.coverage) == 14
    assert all(row.status == 'unknown' and not row.data_complete for row in project.coverage)


def test_invalid_setup_and_partial_stop_produce_explainable_errors():
    project = demo_project()
    project.latitude = float('nan')
    project.timezone = 'not-a-timezone'
    project.detectors.append(project.detectors[0])
    assert len(project_errors(project)) == 3
    project = demo_project()
    partial = next(row for row in project.coverage if row.status == 'partial')
    partial.partial_until = datetime(2024, 5, 10, 12, 0)
    assert 'partial stop time' in coverage_errors(project)[0]
