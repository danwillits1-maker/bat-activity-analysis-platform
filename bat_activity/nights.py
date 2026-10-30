from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from bat_activity.models import (
    COVERAGE_FAILED,
    COVERAGE_FULL,
    COVERAGE_NOT_DEPLOYED,
    COVERAGE_PARTIAL,
    CoverageRow,
    Project,
)
from bat_activity.solar import hours_between, recording_window


def localise_timestamp(ts: datetime, timezone_name: str) -> datetime:
    tz = ZoneInfo(timezone_name)
    if ts.tzinfo is None:
        # Never guess which repeated hour a detector meant, or accept a time
        # that did not exist when clocks moved forward.
        try:
            return pd.Timestamp(ts).tz_localize(tz, ambiguous="raise", nonexistent="raise").to_pydatetime()
        except Exception as error:
            raise ValueError("Ambiguous or nonexistent local time; supply an explicit UTC offset.") from error
    return ts.astimezone(tz)


def windows_for_project(project: Project) -> dict[date, tuple[datetime, datetime, datetime, datetime]]:
    return {evening: recording_window(project, evening) for evening in project.evening_dates()}


def assign_evening_date(
    ts: datetime, project: Project, windows: dict[date, tuple[datetime, datetime, datetime, datetime]]
) -> date | None:
    ts = localise_timestamp(ts, project.timezone)
    for evening, (start, end, _sunset, _sunrise) in windows.items():
        if start.astimezone(timezone.utc) <= ts.astimezone(timezone.utc) <= end.astimezone(timezone.utc):
            return evening
    return None


def coverage_for(project: Project, evening: date, detector_id: str) -> CoverageRow | None:
    for row in project.coverage:
        if row.evening_date == evening and row.detector_id == detector_id:
            return row
    return None


def confirmed_window(
    project: Project,
    evening: date,
    detector_id: str,
    intended_start: datetime,
    intended_end: datetime,
) -> tuple[datetime | None, datetime | None, str, float]:
    """Return confirmed recording start/end, status and confirmed hours.

    Failed and undeployed nights have zero confirmed effort.
    Partial nights use intended start through partial_until, clipped to the
    intended window. Confirmed effort is never inferred from call times.
    """
    row = coverage_for(project, evening, detector_id)
    if row is None:
        return None, None, "unknown", 0.0
    if row.status in {COVERAGE_FAILED, COVERAGE_NOT_DEPLOYED}:
        return None, None, row.status, 0.0
    if row.status in {COVERAGE_FULL, "assumed_full"}:
        return intended_start, intended_end, row.status, hours_between(intended_start, intended_end)
    if row.status == COVERAGE_PARTIAL:
        if row.partial_until is None:
            return None, None, "partial_missing_end", 0.0
        until = localise_timestamp(row.partial_until, project.timezone)
        start = intended_start
        end = min(intended_end, until, key=lambda value: value.astimezone(timezone.utc))
        if hours_between(start, end) <= 0:
            return start, end, row.status, 0.0
        return start, end, row.status, hours_between(start, end)
    return None, None, row.status, 0.0


def survey_night_table(project: Project) -> pd.DataFrame:
    rows: list[dict] = []
    selected = set(project.selected_dates())
    weather_by_date = {item.evening_date: item for item in project.weather}
    for evening in project.evening_dates():
        start, end, sunset, sunrise = recording_window(project, evening)
        intended = hours_between(start, end)
        weather = weather_by_date.get(evening)
        for detector in project.detectors:
            coverage = coverage_for(project, evening, detector.detector_id)
            conf_start, conf_end, status, confirmed = confirmed_window(
                project, evening, detector.detector_id, start, end
            )
            rows.append(
                {
                    "evening_date": evening,
                    "detector_id": detector.detector_id,
                    "detector_label": detector.label,
                    "survey_round": project.survey_label(evening),
                    "in_selected_block": evening in selected,
                    "sunset": sunset,
                    "sunrise": sunrise,
                    "intended_start": start,
                    "intended_end": end,
                    "intended_hours": round(intended, 4),
                    "coverage_status": status,
                    "effort_basis": "assumed_intended_window" if status == "assumed_full" else "user_supplied_coverage",
                    "confirmed_start": conf_start,
                    "confirmed_end": conf_end,
                    "confirmed_hours": round(confirmed, 4),
                    "data_complete": bool(coverage.data_complete) if coverage else False,
                    "completeness_assumed": bool(coverage.completeness_assumed) if coverage else False,
                    "temp_min_c": None if weather is None else weather.temp_min_c,
                    "rain_mm": None if weather is None else weather.rain_mm,
                    "weather_source": None if weather is None else weather.source,
                    "weather_notes": None if weather is None else weather.notes,
                    "solar_hours": round(hours_between(sunset, sunrise), 4),
                }
            )
    return pd.DataFrame(rows)


def candidate_blocks(project: Project, length: int = 5) -> pd.DataFrame:
    evenings = project.evening_dates()
    weather_by_date = {item.evening_date: item for item in project.weather}
    rows: list[dict] = []
    if length < 1:
        return pd.DataFrame(rows)
    for index in range(0, len(evenings) - length + 1):
        block = evenings[index : index + length]
        if not any(period.start <= block[0] <= block[-1] <= period.end for period in project.deployment_periods()):
            continue
        temps = [weather_by_date[d].temp_min_c for d in block
                 if d in weather_by_date and pd.notna(weather_by_date[d].temp_min_c)]
        rains = [weather_by_date[d].rain_mm for d in block
                 if d in weather_by_date and pd.notna(weather_by_date[d].rain_mm)]
        coverage_issues = 0
        for evening in block:
            for detector in project.detectors:
                row = coverage_for(project, evening, detector.detector_id)
                if row is None or row.status != COVERAGE_FULL:
                    coverage_issues += 1
        rows.append(
            {
                "start": block[0],
                "end": block[-1],
                "nights": length,
                "mean_temp_min_c": None if not temps else round(sum(temps) / len(temps), 2),
                "total_rain_mm": None if not rains else round(sum(rains), 2),
                "nights_with_rain": sum(1 for rain in rains if rain is not None and rain > 0),
                "temperature_nights_supplied": len(temps),
                "rainfall_nights_supplied": len(rains),
                "detector_nights_not_full": coverage_issues,
                "is_current_selection": project.selected_start == block[0]
                and project.selected_end == block[-1],
            }
        )
    return pd.DataFrame(rows)


def suggested_survey_period(periods: pd.DataFrame) -> dict | None:
    """Trial weather rule v1, not an ecological suitability assessment.

    Compare only periods with temperature and rainfall for every night.
    Prefer the lowest total rainfall, then the warmest average nightly minimum
    temperature; an exact tie uses the earliest start. Coverage stays visible
    for the ecologist to review separately.
    """
    if periods.empty:
        return None
    complete = periods.loc[
        periods.temperature_nights_supplied.eq(periods.nights)
        & periods.rainfall_nights_supplied.eq(periods.nights)
    ]
    if complete.empty:
        return None
    return complete.sort_values(
        ["total_rain_mm", "mean_temp_min_c", "start"], ascending=[True, False, True]
    ).iloc[0].to_dict()
