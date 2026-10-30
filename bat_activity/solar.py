from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import sunrise, sunset

from bat_activity.models import Project


def observer_for(project: Project) -> Observer:
    return Observer(latitude=project.latitude, longitude=project.longitude)


def solar_times(project: Project, on_date: date) -> dict[str, datetime]:
    tz = ZoneInfo(project.timezone)
    return {
        "sunrise": sunrise(observer_for(project), date=on_date, tzinfo=tz),
        "sunset": sunset(observer_for(project), date=on_date, tzinfo=tz),
    }


def recording_window(
    project: Project, evening_date: date
) -> tuple[datetime, datetime, datetime, datetime]:
    """Return intended window and the sunset/sunrise used to build it.

    Survey night of evening_date runs from sunset minus offset on that date
    through sunrise plus offset on the following morning.
    """
    evening = solar_times(project, evening_date)
    morning = solar_times(project, evening_date + timedelta(days=1))
    sunset = evening["sunset"]
    sunrise = morning["sunrise"]
    start = sunset - timedelta(minutes=project.window_before_sunset_min)
    end = sunrise + timedelta(minutes=project.window_after_sunrise_min)
    return start, end, sunset, sunrise


def hours_between(start: datetime, end: datetime) -> float:
    """Elapsed hours, including the hour gained or lost at a clock change."""
    return (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() / 3600.0
