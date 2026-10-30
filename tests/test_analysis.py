from copy import deepcopy
from datetime import date, timedelta
from io import BytesIO
from zipfile import ZipFile
import pandas as pd
import pytest
from bat_activity.analysis import build_analysis
from bat_activity.contacts import classify_records, standardise_records
from bat_activity.example import demo_project, demo_records
from bat_activity.figures import reporting_figures
from bat_activity.exports import results_zip
from bat_activity.models import project_from_plain
from bat_activity.weather import parse_weather_csv, weather_template
from bat_activity.word_project import build_project_document, load_project_document


def demo():
    project = demo_project()
    return project, classify_records(standardise_records(demo_records()), project)


def test_reporting_excludes_partial_and_keeps_species_zeros():
    tables = build_analysis([demo()])
    assert tables['total_contacts'].contacts.sum() == 13
    assert tables['report_coverage'].report_included.sum() == 9
    summary = tables['summary']
    assert set(summary.loc[summary.detector_id.eq('RC1')].nights_analysed) == {5}
    assert set(summary.loc[summary.detector_id.eq('RC2')].nights_analysed) == {4}
    zeros = tables['nightly_species'].query("detector_id == 'RC1' and species == 'Nyctalus noctula'")
    assert len(zeros) == 5 and zeros.contacts.sum() == 0
    assert summary.total_contacts.sum() == tables['total_contacts'].contacts.sum()


def test_independent_statistics_and_unweighted_nightly_mean(monkeypatch):
    # Four full nights: counts 0, 2, 6, 8; hours 1, 2, 2, 2 => rates 0, 1, 3, 4.
    # Mean/median 2, Q1 .75, Q3 3.25, IQR 2.5. Pooled 16/7 is deliberately different.
    project, _ = demo()
    dates = project.selected_dates()[:4]
    audit = pd.DataFrame({'evening_date': dates, 'detector_id': 'RC1', 'confirmed_hours': [1,2,2,2], 'in_selected_block': True, 'data_complete': True, 'coverage_status': 'full'})
    monkeypatch.setattr('bat_activity.analysis.survey_night_table', lambda p: audit)
    records = pd.DataFrame([{'evening_date': day, 'detector_id': 'RC1', 'species': 'Myotis sp.', 'in_analysis': True, 'exclude_reason': None} for day,n in zip(dates,[0,2,6,8]) for _ in range(n)])
    result = build_analysis([(project, records)])['summary'].iloc[0]
    assert (result.minimum,result.maximum,result['mean'],result['median'],result.q1,result.q3,result.iqr,result.total_contacts,result.nights_analysed) == (0,4,2,2,.75,3.25,2.5,16,4)


def test_multiple_rounds_combine_and_overlaps_rejected():
    p, records = demo()
    later = deepcopy(p)
    delta = timedelta(days=31)
    later.deployment_start += delta; later.deployment_end += delta
    later.selected_start += delta; later.selected_end += delta
    for row in later.coverage:
        row.evening_date += delta
        if row.partial_until:
            row.partial_until += delta
    for row in later.weather:
        row.evening_date += delta
    moved = records.copy()
    moved['evening_date'] = moved.evening_date.map(lambda value: value+delta if value else None)
    tables = build_analysis([(p,records),(later,moved)])
    assert tables['total_contacts'].contacts.sum() == 26
    assert tables['round_activity'].survey_round.nunique() == 2
    with pytest.raises(ValueError, match='Overlapping'):
        build_analysis([(p,records),(p,records)])
    later.detectors[0].latitude += .001
    with pytest.raises(ValueError, match='different coordinates'):
        build_analysis([(p,records),(later,moved)])


def test_missing_data_and_empty_review_do_not_invent_species():
    p, records = demo()
    for row in p.coverage:
        row.data_complete = False
    result = build_analysis([(p, records)])
    assert result['summary'].empty and not result['report_coverage'].report_included.any()
    p = demo_project()
    result = build_analysis([(p,pd.DataFrame())])
    assert result['summary'].empty
    assert result['report_coverage'].report_included.sum() == 9
    assert result['report_coverage'].loc[result['report_coverage'].report_included].contacts.sum() == 0


def test_extended_weather_persistence_and_unknown_vs_dry():
    project = demo_project()
    for restored in (load_project_document(build_project_document(project)), project_from_plain(project.to_plain_dict())):
        assert restored.weather[0] == project.weather[0]
    assert parse_weather_csv(weather_template(project)) == project.weather
    project.weather[2].rain_mm = None
    project.weather[3].rain_mm = 0
    table = build_analysis([(project,demo()[1])])['weather']
    assert table.iloc[0].precipitation == 'Not supplied'
    assert table.iloc[1].precipitation == 'None'
    assert 'hours' not in table.iloc[2].precipitation


@pytest.mark.parametrize('fields', ['cloud_min_pct,cloud_max_pct\n-1,20', 'temp_min_c,temp_max_c\n20,10', 'wind_min_kmh,wind_max_kmh\n1,-3'])
def test_weather_rejects_invalid_ranges(fields):
    header, values = fields.splitlines()
    with pytest.raises(ValueError):
        parse_weather_csv('evening_date,'+header+'\n2024-05-08,'+values)


def test_reporting_pack_contains_all_round_sources_and_figures():
    pair = demo()
    tables = build_analysis([pair])
    figures = reporting_figures(tables)
    archive = ZipFile(BytesIO(results_zip(tables, figures, *pair)))
    assert 'tables/summary.csv' in archive.namelist()
    assert 'checked_records.csv' in archive.namelist()
    assert 'figures/detector_locations.png' in archive.namelist()
    assert 'figures/total_contacts.svg' in archive.namelist()
    assert b'<svg' in archive.read('figures/total_contacts.svg')
    assert pd.read_csv(archive.open('tables/total_contacts.csv')).contacts.sum() == 13


def shifted_round(pair, days):
    project, records = pair
    project = deepcopy(project)
    delta = timedelta(days=days)
    project.deployment_start += delta
    project.deployment_end += delta
    project.selected_start += delta
    project.selected_end += delta
    for row in project.coverage:
        row.evening_date += delta
        if row.partial_until:
            row.partial_until += delta
    for row in project.weather:
        row.evening_date += delta
    records = records.copy()
    records['evening_date'] = records.evening_date.map(lambda value: value+delta if value else None)
    return project, records


def test_site_stacks_average_detector_nights_not_location_means(monkeypatch):
    project, _ = demo()
    days = project.selected_dates()
    # RC1 rates: Pipistrellus 1 and 2. RC2 rate: Myotis 6.
    # Equal detector-night mean stack: Pipistrellus 1 + Myotis 2 = 3.
    # A mean of location means would be (1.5+6)/2 = 3.75; pooled hours is 29/7.
    audit = pd.DataFrame({'evening_date': [days[0],days[1],days[0]], 'detector_id': ['RC1','RC1','RC2'], 'confirmed_hours': [1,2,4], 'in_selected_block': True, 'data_complete': True, 'coverage_status': 'full'})
    monkeypatch.setattr('bat_activity.analysis.survey_night_table', lambda p: audit)
    records = pd.DataFrame([
        {'evening_date': day, 'detector_id': detector, 'species': species, 'in_analysis': True, 'exclude_reason': None}
        for day, detector, species, number in [(days[0],'RC1','Pipistrellus pipistrellus',1),(days[1],'RC1','Pipistrellus pipistrellus',2),(days[1],'RC1','Pipistrellus pygmaeus',2),(days[0],'RC2','Myotis sp.',24)]
        for _ in range(number)
    ])
    tables = build_analysis([(project,records)])
    stacked = tables['site_activity'].set_index('activity_group')
    assert stacked.loc['Pipistrellus spp.'].mean_rate == 1
    assert stacked.loc['Myotis spp.'].mean_rate == 2
    assert stacked.mean_rate.sum() == 3
    assert set(tables['site_activity'].detector_nights_analysed) == {3}
    assert tables['survey_key'].iloc[0].locations_analysed == 2
    assert set(tables['summary'].species) == {'Pipistrellus pipistrellus','Pipistrellus pygmaeus','Myotis sp.'}


def test_labels_follow_selected_dates_not_upload_order_and_keep_unknown_effort():
    pair = demo()
    later = shifted_round(pair,31)
    for coverage in later[0].coverage:
        coverage.data_complete = False
    tables = build_analysis([later,pair])
    key = tables['survey_key']
    assert list(key.survey_round) == ['Survey 1','Survey 2']
    assert key.iloc[0].first_evening == pair[0].selected_start
    assert key.iloc[1].first_evening == later[0].selected_start
    missing = tables['site_activity'].query("survey_round == 'Survey 2'")
    assert missing.mean_rate.isna().all()
    assert set(missing.detector_nights_analysed) == {0}
    svg = reporting_figures(tables)['survey_activity_stacked']['svg'].decode()
    assert 'Not analysed' in svg
    assert 'Survey 1' in svg and 'Survey 2' in svg


def test_eight_surveys_four_locations_still_produce_four_activity_charts():
    from bat_activity.models import Detector
    project, records = demo()
    project.detectors.extend([Detector('RC3','Stream',51.7524,-1.255),Detector('RC4','Field edge',51.7526,-1.255)])
    extra = []
    for row in project.coverage:
        clone = deepcopy(row)
        clone.detector_id = 'RC3' if row.detector_id == 'RC1' else 'RC4'
        extra.append(clone)
    project.coverage.extend(extra)
    rounds = [shifted_round((project,records),i*31) for i in range(8)]
    tables = build_analysis(list(reversed(rounds)))
    assert list(tables['survey_key'].survey_round) == [f'Survey {i}' for i in range(1,9)]
    figures = reporting_figures(tables)
    assert set(figures) == {'detector_locations','total_contacts','nightly_activity_pipistrelles','nightly_activity_other_species','survey_activity_stacked'}
    assert tables['site_activity'].survey_round.nunique() == 8
    assert set(tables['survey_key'].locations_analysed) == {4}
    with pytest.raises(ValueError, match='eight'):
        build_analysis(rounds + [shifted_round((project,records),8*31)])
    from xml.etree import ElementTree
    ElementTree.fromstring(figures['survey_activity_stacked']['svg'])


@pytest.mark.parametrize('species, expected', [
    ('Pipistrellus pipistrellus','Pipistrellus spp.'),
    ('Common pipistrelle','Pipistrellus spp.'),
    ('Rhinolophus hipposideros','Rhinolophus spp.'),
    ('Myotis sp.','Myotis spp.'),
    ('Nyctalus/Eptesicus sp.','Nyctalus/Eptesicus spp.'),
    ('Nyctalus noctula','Nyctalus/Eptesicus spp.'),
    ('Serotine','Nyctalus/Eptesicus spp.'),
    ('Myotis/Plecotus sp.','Other / uncertain'),
    ('Pipistrellus/Myotis sp.','Other / uncertain'),
    ('Unidentified bat','Other / uncertain'),
    ('Barbastella barbastellus','Other / uncertain'),
])
def test_stacked_groups_preserve_mixed_and_unrecognised_identifications(species, expected):
    from bat_activity.analysis import activity_group
    assert activity_group(species) == expected
