"""Small checks shared by the screens and saved-project loader."""
from __future__ import annotations

import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bat_activity.models import COVERAGE_STATUSES, CoverageRow, Project
from bat_activity.nights import localise_timestamp
from bat_activity.solar import hours_between, recording_window


def project_errors(project: Project) -> list[str]:
    errors = []
    for label, latitude, longitude in [
        ("Site", project.latitude, project.longitude),
        *[(f"Detector {d.detector_id}", d.latitude, d.longitude) for d in project.detectors],
    ]:
        if not math.isfinite(latitude) or not -90 <= latitude <= 90:
            errors.append(f"{label}: latitude must be between -90 and 90.")
        if not math.isfinite(longitude) or not -180 <= longitude <= 180:
            errors.append(f"{label}: longitude must be between -180 and 180.")
    try:
        ZoneInfo(project.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        errors.append("Enter a recognised time zone, for example Europe/London.")
    if project.deployment_end < project.deployment_start:
        errors.append("Last evening date must be on or after the first evening date.")
    elif (project.deployment_end - project.deployment_start).days >= 366:
        errors.append("This local trial supports up to 366 deployment nights at a time.")
    monitoring = project.deployment_periods()
    if len(monitoring) > 8:
        errors.append("Enter up to eight monitoring periods.")
    for index, period in enumerate(monitoring):
        if not project.deployment_start <= period.start <= period.end <= project.deployment_end:
            errors.append("Each monitoring period needs a start date on or before its end date, within the project dates.")
        if index and period.start <= monitoring[index-1].end:
            errors.append("Monitoring periods must not overlap.")
    ids = [d.detector_id for d in project.detectors]
    if not ids or any(not value.strip() for value in ids):
        errors.append("Enter at least one detector with an identifier.")
    if len(set(ids)) != len(ids):
        errors.append("Each detector needs a different identifier.")
    if project.window_before_sunset_min < 0 or project.window_after_sunrise_min < 0:
        errors.append("Recording offsets cannot be negative.")
    return errors


def selection_errors(project: Project) -> list[str]:
    periods = project.survey_periods()
    if not periods:
        return ["Choose at least one survey date block before continuing."]
    if len(periods) > 8:
        return ["This prototype supports up to eight survey periods."]
    for index, period in enumerate(periods):
        if not (project.deployment_start <= period.start <= period.end <= project.deployment_end):
            return ["Every selected block must fit entirely within the project dates."]
        if not any(window.start <= period.start <= period.end <= window.end for window in project.deployment_periods()):
            return ["Every selected block must fit entirely within one monitoring period."]
        if index and period.start <= periods[index-1].end:
            return ["Survey date blocks must not overlap."]
    if project.monitoring_periods:
        for window in project.deployment_periods():
            if sum(window.start <= period.start <= period.end <= window.end for period in periods) > 1:
                return ["Keep one consecutive analysis block per monitoring period."]
    return []


def coverage_errors(project: Project) -> list[str]:
    errors = []
    seen = set()
    ids = {d.detector_id for d in project.detectors}
    for row in project.coverage:
        key = (row.evening_date, row.detector_id)
        label = f"{row.evening_date}, {row.detector_id}"
        if key in seen:
            errors.append(f"{label}: more than one coverage entry.")
        seen.add(key)
        if row.detector_id not in ids or row.evening_date not in set(project.evening_dates()):
            errors.append(f"{label}: coverage is outside this deployment or uses an unknown detector.")
        if row.status not in COVERAGE_STATUSES:
            errors.append(f"{label}: choose a valid coverage status.")
        if row.status == "partial" and row.partial_until is not None:
            try:
                until = localise_timestamp(row.partial_until, project.timezone)
                start, end, _, _ = recording_window(project, row.evening_date)
                if hours_between(start, until) <= 0 or hours_between(until, end) < 0:
                    errors.append(f"{label}: partial stop time must be after the intended start and no later than its end.")
            except ValueError as error:
                errors.append(f"{label}: {error}")
    return errors


def synchronise_coverage(project: Project) -> None:
    """New detector-nights start unconfirmed; retain existing valid entries."""
    existing = {(row.evening_date, row.detector_id): row for row in project.coverage}
    project.coverage = [
        existing.get((evening, detector.detector_id), CoverageRow(evening, detector.detector_id, "unknown"))
        for evening in project.evening_dates()
        for detector in project.detectors
    ]


def apply_v1_assumptions(project):
    """Use user-selected setup dates and explicitly assumed intended effort."""
    from bat_activity.models import SurveyPeriod
    if project.monitoring_periods:
        project.surveys = [SurveyPeriod(period.start, period.end, project.methodology,
                                       "user_preselected_v1")
                           for period in project.deployment_periods()]
    elif not project.survey_periods():
        project.surveys = [SurveyPeriod(project.deployment_start, project.deployment_end,
                                       project.reasoning, "user_preselected_v1")]
    synchronise_coverage(project)
    for row in project.coverage:
        row.status = "assumed_full"
        row.partial_until = None


def apply_v1_data_assumption(project, upload_applied):
    """Assume upload completeness explicitly, without recording user confirmation."""
    for row in project.coverage:
        row.data_complete = False
        row.completeness_assumed = bool(upload_applied)
