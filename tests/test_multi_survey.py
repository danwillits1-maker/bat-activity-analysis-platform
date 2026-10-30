"""One site, several selected periods, one reviewed input file."""
from copy import deepcopy
from datetime import timedelta
from io import BytesIO
from zipfile import ZipFile

import pandas as pd
import pytest
from docx import Document

from bat_activity.analysis import build_analysis
from bat_activity.contacts import classify_records, standardise_records
from bat_activity.example import demo_project, demo_records
from bat_activity.exports import results_zip
from bat_activity.figures import reporting_figures
from bat_activity.models import SurveyPeriod, project_from_plain
from bat_activity.nights import survey_night_table
from bat_activity.word_project import build_project_document, load_project_document
from bat_activity.workflow import synchronise_coverage, selection_errors


def three_survey_dataset():
    original = demo_project()
    project = deepcopy(original)
    project.surveys, project.weather, project.coverage = [], [], []
    files = []
    for offset in (0,31,62):
        delta = timedelta(days=offset)
        project.surveys.append(SurveyPeriod(original.selected_start+delta, original.selected_end+delta, f'Synthetic round shifted by {offset} days'))
        for weather in original.weather:
            row = deepcopy(weather)
            row.evening_date += delta
            project.weather.append(row)
        for coverage in original.coverage:
            row = deepcopy(coverage)
            row.evening_date += delta
            if row.partial_until:
                row.partial_until += delta
            project.coverage.append(row)
        frame = demo_records()
        frame['Timestamp'] = (pd.to_datetime(frame['Timestamp'])+pd.Timedelta(days=offset)).dt.strftime('%Y-%m-%d %H:%M:%S')
        files.append(frame)
    project.deployment_end += timedelta(days=62)
    synchronise_coverage(project)
    project.surveys.reverse()  # Input order must not control labels.
    return project, pd.concat(files, ignore_index=True)


def test_one_combined_file_is_assigned_to_three_selected_surveys():
    project, raw = three_survey_dataset()
    classified = classify_records(standardise_records(raw, 'one_combined_file.csv'), project)
    assert len(classified) == 60
    assert set(classified.source_file) == {'one_combined_file.csv'}
    assert classified.loc[classified.in_analysis].groupby('survey_round').size().to_dict() == {'Survey 1':15,'Survey 2':15,'Survey 3':15}
    midnight = classified.loc[classified.timestamp_raw.str.contains('00:18')]
    assert list(midnight.evening_date) == [period.start for period in project.survey_periods()]
    tables = build_analysis([(project, classified)])
    assert tables['total_contacts'].contacts.sum() == 39
    assert list(tables['survey_key'].survey_round) == ['Survey 1','Survey 2','Survey 3']
    assert list(tables['survey_key'].detector_nights_analysed) == [9,9,9]
    assert tables['report_coverage'].report_included.sum() == 27
    assert set(tables['site_activity'].survey_round) == {'Survey 1','Survey 2','Survey 3'}
    # The silent final night of each block is still part of its survey.
    nightly = survey_night_table(project)
    for period in project.survey_periods():
        assert nightly.loc[nightly.evening_date.eq(period.end)].in_selected_block.all()
        assert period.end in set(tables['nightly_species'].evening_date)


def test_one_word_record_preserves_all_periods_and_legacy_files_still_load():
    project, _ = three_survey_dataset()
    project.surveys = project.survey_periods()
    assert load_project_document(build_project_document(project)) == project
    assert project_from_plain(project.to_plain_dict()) == project
    old = demo_project()
    document = Document(BytesIO(build_project_document(old)))
    table = next(table for table in document.tables if table.cell(0,0).text == 'survey_start')
    table._element.getparent().remove(table._element)
    buffer = BytesIO(); document.save(buffer)
    restored = load_project_document(buffer.getvalue())
    assert restored.surveys == []
    assert restored.selected_dates() == old.selected_dates()


def test_combined_upload_has_one_settings_file_and_full_audit_in_pack():
    project, raw = three_survey_dataset()
    records = classify_records(standardise_records(raw, 'one.csv'), project)
    tables = build_analysis([(project,records)])
    figures = reporting_figures(tables)
    archive = ZipFile(BytesIO(results_zip(tables, figures, project, records)))
    assert [name for name in archive.namelist() if name.endswith('.docx')] == ['project_record.docx']
    assert len(load_project_document(archive.read('project_record.docx')).surveys) == 3
    rows = pd.read_csv(archive.open('checked_records.csv'))
    assert len(rows) == 60
    assert set(rows.survey_round.dropna()) == {'Survey 1','Survey 2','Survey 3'}
    assert 'figures/survey_activity_stacked.png' in archive.namelist()
    assert len([name for name in figures if name != 'detector_locations']) == 4


def test_missing_timestamp_cannot_silently_make_a_whole_round_complete():
    project, raw = three_survey_dataset()
    bad = raw.iloc[[1]].copy()
    bad['Timestamp'] = 'unknown'
    records = classify_records(standardise_records(pd.concat([raw,bad],ignore_index=True)),project)
    tables = build_analysis([(project,records)])
    # Date-unknown RC1 error affects RC1 across all three periods; RC2 remains usable.
    coverage = tables['report_coverage']
    assert not coverage.loc[coverage.detector_id.eq('RC1')].report_included.any()
    assert coverage.loc[coverage.detector_id.eq('RC2')].report_included.sum() == 12


def test_selected_surveys_reject_overlap_and_outside_project_dates():
    project, _ = three_survey_dataset()
    project.surveys.append(deepcopy(project.survey_periods()[0]))
    assert 'overlap' in ' '.join(selection_errors(project))
    with pytest.raises(ValueError,match='overlap'):
        build_analysis([(project,pd.DataFrame())])
    project.surveys = [SurveyPeriod(project.deployment_start-timedelta(days=1), project.deployment_start)]
    assert 'project dates' in ' '.join(selection_errors(project))
