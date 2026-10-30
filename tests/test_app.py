"""Exercise real Streamlit reruns, rather than only calculation functions."""

from datetime import date

from pathlib import Path



import pytest

from streamlit.testing.v1 import AppTest



from bat_activity.example import demo_csv_text, demo_project, demo_records

from bat_activity.word_project import build_project_document, load_project_document



APP = str(Path(__file__).resolve().parents[1] / 'app.py')


@pytest.fixture(autouse=True)
def offline_imagery(monkeypatch):
    # UI regression tests are deterministic; live imagery is checked separately.
    def unavailable(bounds):
        raise OSError('Offline UI test')
    monkeypatch.setattr('bat_activity.figures.fetch_background', unavailable)





def widget(widgets, label):

    return next(w for w in widgets if w.label == label)





def start():

    # Synthetic fixtures are test inputs only; there is no demo mode in the app.

    at = AppTest.from_file(APP, default_timeout=15)

    project = demo_project()

    from bat_activity.models import SurveyPeriod

    project.monitoring_periods = [SurveyPeriod(project.selected_start, project.selected_end)]

    at.session_state['project'] = project

    at.session_state['raw_records'] = demo_records()

    at.session_state['raw_name'] = 'reviewed_fixture.csv'

    at.session_state['selection_mode'] = 'suggested'

    at.run()

    assert not at.exception

    return at





def parse(at):

    widget(at.button, 'Apply uploaded data').click().run()

    assert not at.exception

    return at





def test_fixture_runs_to_results_and_exports_and_recalculates_selection():

    at = parse(start())

    assert at.session_state['classified'].in_analysis.sum() == 16

    assert 'Download Word results' in [button.label for button in at.get('download_button')]

    edit_table(at, 'monitoring_editor_', {0: {'start': '2024-05-09', 'end': '2024-05-11'}})

    widget(at.button, 'Apply survey setup').click().run()

    assert not at.exception

    classified = at.session_state['classified']

    assert not classified.loc[classified.evening_date == date(2024, 5, 8), 'in_analysis'].any()

    assert not any(row.data_complete for row in at.session_state['project'].coverage)

    assert all(row.completeness_assumed for row in at.session_state['project'].coverage)





def test_short_deployment_stays_inside_dates_and_does_not_crash():

    at = start()

    edit_table(at, 'monitoring_editor_', {0: {'end': '2024-05-08'}})

    widget(at.button, 'Apply survey setup').click().run()

    assert not at.exception

    project = at.session_state['project']

    assert project.selected_dates() == [date(2024, 5, 8)]





def test_loading_saved_selection_refreshes_existing_widgets_and_clears_old_data():

    at = parse(start())

    saved = demo_project()

    saved.site_name = 'Loaded site'

    saved.selected_start = date(2024, 5, 9)

    saved.selected_end = date(2024, 5, 11)

    widget(at.get('file_uploader'), 'Upload saved Word project').upload('saved.docx', build_project_document(saved)).run()

    assert not at.exception

    assert widget(at.text_input, 'Site name').value == 'Loaded site'

    assert at.session_state['project'].selected_end == date(2024, 5, 11)

    assert len(at.session_state['project'].selected_dates()) == 3

    assert at.session_state['raw_records'] is None

    assert at.session_state['classified'] is None





def test_upload_clears_completeness_and_new_project_clears_uploaded_data():

    at = start()

    widget(at.get('file_uploader'), 'Reviewed activity CSV').upload('uploaded.csv', demo_csv_text().encode()).run()

    parse(at)

    assert not any(row.data_complete for row in at.session_state['project'].coverage)

    assert all(row.completeness_assumed for row in at.session_state['project'].coverage)

    assert at.session_state['classified'].source_file.unique().tolist() == ['uploaded.csv']

    widget(at.button, 'Start a new project').click().run()

    assert not at.exception

    assert at.session_state['project'] is None

    assert at.session_state['raw_records'] is None

    assert at.session_state['classified'] is None

    assert at.session_state['raw_name'] == ''

    assert widget(at.text_input, 'Site name').value == ''





def test_blank_weather_values_work_in_the_screen():

    at = start()

    widget(at.text_area, 'Weather table (CSV)').set_value('evening_date,temp_min_c,rain_mm\n2024-05-08,,\n')

    widget(at.button, 'Apply pasted weather').click().run()

    assert not at.exception





def test_weather_entry_does_not_change_preselected_dates():

    at = start()

    before = at.session_state['project'].selected_dates()

    widget(at.text_area, 'Weather table (CSV)').set_value('evening_date,temp_min_c,rain_mm\n2024-05-08,10,0\n')

    widget(at.button, 'Apply pasted weather').click().run()

    assert not at.exception

    assert at.session_state['project'].selected_dates() == before





def test_complex_selection_and_save_tab_are_absent():

    at = start()

    assert len(at.tabs) == 6

    assert not any('Save progress' in t.label for t in at.tabs)

    assert not any(w.label in {'Use suggested dates', 'Apply recording status', 'Apply all survey periods'} for w in at.button)

    assert all(row.status == 'assumed_full' for row in at.session_state['project'].coverage)





def edit_table(at, prefix, rows):

    table = next(d for d in at.dataframe if d.key and d.key.startswith(prefix))

    at.session_state[table.key] = {'edited_rows': rows, 'added_rows': [], 'deleted_rows': []}

    at.run()

    assert not at.exception





def test_analysis_runs_without_confirmations_and_reminder_is_optional():

    at = start()

    widget(at.get('file_uploader'), 'Reviewed activity CSV').upload('uploaded.csv', demo_csv_text().encode()).run()

    parse(at)

    assert not any(d.key and d.key.startswith('data_confirmation_') for d in at.dataframe)

    assert not any(b.label == 'Apply validation choices' for b in at.button)

    assert next(m for m in at.metric if m.label == 'Contacts included').value == '16'

    assert all(r.completeness_assumed and not r.data_complete for r in at.session_state['project'].coverage)

    assert any('Missing records can understate activity' in w.value for w in at.warning)

    widget(at.button, 'Understood — hide reminder').click().run()

    assert not at.exception

    assert not any('Missing records can understate activity' in w.value for w in at.warning)

    assert next(m for m in at.metric if m.label == 'Contacts included').value == '16'

    at.run()

    assert not any('Missing records can understate activity' in w.value for w in at.warning)

    widget(at.get('file_uploader'), 'Reviewed activity CSV').upload('new.csv', demo_csv_text().encode()).run()

    parse(at)

    assert any('Missing records can understate activity' in w.value for w in at.warning)

    widget(at.button, 'Understood — hide reminder').click().run()

    widget(at.number_input, 'Minutes before sunset').set_value(20)

    widget(at.button, 'Apply survey setup').click().run()

    assert not at.exception

    assert any('Missing records can understate activity' in w.value for w in at.warning)





def test_recording_assumption_remains_explicit_after_rerun():

    at = parse(start())

    at.run()

    assert not at.exception

    assert all(r.status == 'assumed_full' for r in at.session_state['project'].coverage)

    assert any('not verified operational effort' in w.value for w in at.warning)





def test_header_only_csv_uses_explicit_assumptions_without_clicks():

    at = start()

    payload = demo_csv_text().splitlines()[0].encode()

    widget(at.get('file_uploader'), 'Reviewed activity CSV').upload('empty.csv', payload).run()

    parse(at)

    assert next(m for m in at.metric if m.label == 'Contacts included').value == '0'

    assert next(m for m in at.metric if m.label == 'Detector-nights included').value == '10'

    assert any('Missing records can understate activity' in w.value for w in at.warning)

    assert not any(d.key and d.key.startswith('data_confirmation_') for d in at.dataframe)





@pytest.mark.parametrize('label,value', [('Time zone', 'invalid-zone'), ('Site latitude', 100.0)])
def test_invalid_setup_shows_a_message_instead_of_a_traceback(label, value):

    at = start()

    inputs = at.text_input if isinstance(value, str) else at.number_input

    widget(inputs, label).set_value(value)

    widget(at.button, 'Apply survey setup').click().run()

    assert not at.exception

    assert at.error





@pytest.mark.parametrize('label,name,payload', [

    ('Reviewed activity CSV', 'bad.csv', b'not,a,supported,header\n1,2,3,4'),

    ('Upload saved Word project', 'bad.docx', b'not a Word document'),

])

def test_bad_upload_is_explained_without_crashing(label, name, payload):

    at = start()

    widget(at.get('file_uploader'), label).upload(name, payload).run()

    assert not at.exception

    assert at.error







def test_simplified_survey_results_and_downloads():

    at = parse(start())

    key = next(d.value for d in at.dataframe if 'First evening' in d.value.columns)

    assert list(key['Survey']) == ['Survey 1']

    assert key.iloc[0]['Detector-nights analysed'] == 10

    assert widget(at.get('download_button'), 'Download Word results')
    assert not any('Excel' in b.label or 'pack' in b.label for b in at.get('download_button'))

    # The same four activity figures plus the plain location map are displayed.

    captions = [element.proto.imgs[0].caption for element in at.get('image')]

    assert captions == ['Detector locations', 'Total contacts', 'Nightly activity pipistrelles',

                        'Nightly activity other species', 'Survey activity stacked']

    assert not at.exception





def test_new_session_starts_blank_and_does_not_automatically_load_demo():

    at = AppTest.from_file(APP, default_timeout=15).run()

    assert not at.exception

    assert at.session_state['project'] is None

    assert at.session_state['raw_records'] is None

    assert widget(at.text_input, 'Site name').value == ''

    assert widget(at.number_input, 'Site latitude').value is None

    assert next(d for d in at.dataframe if d.key and d.key.startswith('monitoring_editor_')).value['start'].isna().all()

    at.run()

    assert at.session_state['project'] is None





def test_own_survey_setup_applies_atomically_and_persists():

    at = parse(start())

    widget(at.button, 'Start a new project').click().run()

    assert not at.exception

    assert at.session_state['project'] is None

    assert at.session_state['raw_records'] is None

    widget(at.text_input, 'Site name').set_value('My test site')

    widget(at.number_input, 'Site latitude').set_value(52.0)

    widget(at.number_input, 'Site longitude').set_value(-1.0)

    monitoring_table = next(d for d in at.dataframe if d.key and d.key.startswith('monitoring_editor_'))

    at.session_state[monitoring_table.key] = {'edited_rows': {0: {'start': '2025-06-01', 'end': '2025-06-07'}}, 'added_rows': [], 'deleted_rows': []}

    table = next(d for d in at.dataframe if d.key and d.key.startswith('detector_editor_'))

    at.session_state[table.key] = {'edited_rows': {}, 'deleted_rows': [], 'added_rows': [{'detector_id':'MY1','label':'My hedge','latitude':52.0,'longitude':-1.0}]}

    widget(at.button, 'Apply survey setup').click().run()

    assert not at.exception

    project = at.session_state['project']

    assert project.site_name == 'My test site'

    assert project.deployment_start == date(2025,6,1)

    assert [d.detector_id for d in project.detectors] == ['MY1']

    assert not project.weather

    assert all(row.status == 'assumed_full' and not row.data_complete for row in project.coverage)

    at.run()

    assert widget(at.text_input, 'Site name').value == 'My test site'

    assert next(d for d in at.dataframe if d.key and d.key.startswith('monitoring_editor_')).value.iloc[0]['start'] == date(2025,6,1)

    assert at.session_state['raw_records'] is None





def test_invalid_draft_does_not_overwrite_existing_applied_setup():

    at = start()

    original_start = at.session_state['project'].deployment_start

    edit_table(at, 'monitoring_editor_', {0: {'start': '2025-06-01'}})

    assert at.session_state['project'].deployment_start == original_start

    widget(at.button, 'Apply survey setup').click().run()

    assert not at.exception

    assert at.error

    assert at.session_state['project'].deployment_start == original_start

    assert at.session_state['project'].deployment_start == original_start

    edit_table(at, 'monitoring_editor_', {0: {'start': '2025-06-01', 'end': '2025-06-07'}})

    widget(at.button, 'Apply survey setup').click().run()

    assert not at.exception

    assert at.session_state['project'].deployment_start == date(2025,6,1)

    assert len(at.session_state['raw_records']) == 20

    assert at.session_state['raw_name'] == 'reviewed_fixture.csv'





def test_changing_setup_keeps_personal_uploaded_csv():

    at = start()

    widget(at.get('file_uploader'), 'Reviewed activity CSV').upload('my_test.csv', demo_csv_text().encode()).run()

    widget(at.text_input, 'Site name').set_value('My uploaded survey')

    widget(at.button, 'Apply survey setup').click().run()

    assert not at.exception

    assert at.session_state['raw_name'] == 'my_test.csv'

    assert len(at.session_state['raw_records']) == 20

    assert 'demo_setup' not in at.session_state





def test_one_project_all_periods_one_upload_produces_three_surveys():

    from test_multi_survey import three_survey_dataset

    project, raw = three_survey_dataset()

    periods = project.survey_periods()

    project.monitoring_periods = periods

    from bat_activity.workflow import apply_v1_assumptions

    apply_v1_assumptions(project)

    at = AppTest.from_file(APP, default_timeout=60).run()

    widget(at.get('file_uploader'), 'Upload saved Word project').upload('one_project.docx', build_project_document(project)).run()

    assert not at.exception

    assert len(at.session_state['project'].surveys) == 3

    assert len(at.session_state['project'].selected_dates()) == 15

    # A single upload covers all three chosen blocks.

    widget(at.get('file_uploader'), 'Reviewed activity CSV').upload('all_calls.csv', raw.to_csv(index=False).encode()).run()

    parse(at)

    assert next(m for m in at.metric if m.label == 'Contacts included').value == '48'

    key = next(d.value for d in at.dataframe if 'First evening' in d.value.columns)

    assert list(key['Survey']) == ['Survey 1','Survey 2','Survey 3']

    assert len(at.session_state['raw_records']) == 60

    assert set(at.session_state['classified'].source_file) == {'all_calls.csv'}

    restored = load_project_document(build_project_document(at.session_state['project']))

    assert len(restored.surveys) == 3

    assert len(restored.selected_dates()) == 15





def test_demo_controls_are_absent_and_legacy_demo_session_is_cleared_once():

    at = start()

    assert not any('demo' in button.label.lower() for button in at.button)

    assert not any('synthetic' in button.label.lower() for button in at.get('download_button'))

    assert not any('demo' in item.value.lower() for item in at.info)

    at.session_state['demo_loaded'] = True

    at.session_state['demo_setup'] = True

    at.run()

    assert not at.exception

    assert at.session_state['project'] is None

    assert at.session_state['raw_records'] is None

    assert 'demo_loaded' not in at.session_state

    assert 'demo_setup' not in at.session_state

    at.run()

    assert widget(at.text_input, 'Site name').value == ''





def test_setup_periods_are_used_directly_without_further_selection():

    from bat_activity.models import SurveyPeriod

    project = demo_project()

    project.monitoring_periods = [SurveyPeriod(date(2024,5,6), date(2024,5,8)),

                                  SurveyPeriod(date(2024,5,10), date(2024,5,12))]

    at = AppTest.from_file(APP, default_timeout=60)

    at.session_state['project'] = project

    at.run()

    assert not at.exception

    assert [(p.start,p.end) for p in at.session_state['project'].surveys] == [

        (date(2024,5,6),date(2024,5,8)), (date(2024,5,10),date(2024,5,12))]



