from datetime import date
from copy import deepcopy

from bat_activity.example import demo_project
from bat_activity.models import SurveyPeriod, project_from_plain
from bat_activity.nights import candidate_blocks
from bat_activity.workflow import project_errors, selection_errors, synchronise_coverage
from bat_activity.word_project import build_project_document, load_project_document


def test_monitoring_gaps_are_not_nights_or_candidate_blocks():
    project = demo_project()
    project.monitoring_periods = [SurveyPeriod(date(2024, 5, 6), date(2024, 5, 8)),
                                  SurveyPeriod(date(2024, 5, 10), date(2024, 5, 12))]
    assert date(2024, 5, 9) not in project.evening_dates()
    assert candidate_blocks(project, 3).start.tolist() == [date(2024, 5, 6), date(2024, 5, 10)]
    synchronise_coverage(project)
    assert all(row.evening_date != date(2024, 5, 9) for row in project.coverage)
    project.surveys = [SurveyPeriod(date(2024, 5, 8), date(2024, 5, 10))]
    assert selection_errors(project)


def test_monitoring_dates_roundtrip_and_overlap_validation():
    project = demo_project()
    project.monitoring_periods = [SurveyPeriod(project.deployment_start, project.deployment_end)]
    loaded = load_project_document(build_project_document(project))
    assert loaded.monitoring_periods == project.monitoring_periods
    assert project_from_plain(project.to_plain_dict()).monitoring_periods == project.monitoring_periods
    project.monitoring_periods.append(deepcopy(project.monitoring_periods[0]))
    assert any('overlap' in error for error in project_errors(project))


def test_reviewing_dates_does_not_keep_a_block_implicitly():
    project = demo_project()
    project.monitoring_periods = [SurveyPeriod(project.deployment_start, project.deployment_end)]
    assert project.selected_start is not None
    assert project.selected_dates() == []
    assert project.survey_periods() == []
