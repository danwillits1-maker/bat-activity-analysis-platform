from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any


COVERAGE_FULL = "full"
COVERAGE_PARTIAL = "partial"
COVERAGE_FAILED = "failed"
COVERAGE_NOT_DEPLOYED = "not_deployed"
COVERAGE_UNKNOWN = "unknown"
COVERAGE_STATUSES = (
    COVERAGE_UNKNOWN,
    "assumed_full",
    COVERAGE_FULL,
    COVERAGE_PARTIAL,
    COVERAGE_FAILED,
    COVERAGE_NOT_DEPLOYED,
)

WEATHER_SOURCE_PASTED = "pasted_or_typed"
WEATHER_SOURCE_OBSERVED = "observed_on_site"
WEATHER_SOURCE_STATION = "weather_station"
WEATHER_SOURCE_MODELLED = "modelled"


@dataclass
class Detector:
    detector_id: str
    label: str
    latitude: float
    longitude: float


@dataclass
class NightWeather:
    evening_date: date
    temp_min_c: float | None
    rain_mm: float | None
    source: str
    notes: str = ""
    temp_max_c: float | None = None
    cloud_min_pct: float | None = None
    cloud_max_pct: float | None = None
    wind_min_kmh: float | None = None
    wind_max_kmh: float | None = None
    rain_hours: str = ""


@dataclass
class CoverageRow:
    evening_date: date
    detector_id: str
    status: str
    partial_until: datetime | None = None
    data_complete: bool = False
    completeness_assumed: bool = False


@dataclass
class SurveyPeriod:
    start: date
    end: date
    reasoning: str = ""
    selection_method: str = "manual"

    def dates(self) -> list[date]:
        return [date.fromordinal(day) for day in range(self.start.toordinal(), self.end.toordinal()+1)]


@dataclass
class Project:
    site_name: str
    latitude: float
    longitude: float
    timezone: str
    window_before_sunset_min: int
    window_after_sunrise_min: int
    methodology: str
    reasoning: str
    detectors: list[Detector]
    weather: list[NightWeather]
    coverage: list[CoverageRow]
    deployment_start: date
    deployment_end: date
    selected_start: date | None = None
    selected_end: date | None = None
    weather_source_default: str = WEATHER_SOURCE_PASTED
    selection_method: str = "manual"
    surveys: list[SurveyPeriod] = field(default_factory=list)

    monitoring_periods: list[SurveyPeriod] = field(default_factory=list)

    def deployment_periods(self) -> list[SurveyPeriod]:
        return sorted(self.monitoring_periods, key=lambda period: period.start) or [SurveyPeriod(self.deployment_start, self.deployment_end)]

    def evening_dates(self) -> list[date]:
        return sorted({day for period in self.deployment_periods() for day in period.dates()})

    def selected_dates(self) -> list[date]:
        if self.surveys or self.monitoring_periods:
            return sorted({day for survey in self.surveys for day in survey.dates()})
        if self.selected_start is None or self.selected_end is None:
            return []
        if self.selected_end < self.selected_start:
            return []
        dates: list[date] = []
        current = self.selected_start
        while current <= self.selected_end:
            dates.append(current)
            current = date.fromordinal(current.toordinal() + 1)
        return dates

    def survey_periods(self) -> list[SurveyPeriod]:
        if self.surveys:
            return sorted(self.surveys, key=lambda period: period.start)
        if not self.monitoring_periods and self.selected_start is not None and self.selected_end is not None:
            return [SurveyPeriod(self.selected_start, self.selected_end, self.reasoning, self.selection_method)]
        return []

    def survey_label(self, evening: date) -> str | None:
        for index, survey in enumerate(self.survey_periods(), 1):
            if survey.start <= evening <= survey.end:
                return f"Survey {index}"
        return None

    def to_plain_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_iso_date(value: str | date | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])


def parse_iso_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def project_from_plain(data: dict[str, Any]) -> Project:
    detectors = [Detector(**row) for row in data.get("detectors", [])]
    weather = [
        NightWeather(
            evening_date=parse_iso_date(row["evening_date"]),
            temp_min_c=row.get("temp_min_c"),
            rain_mm=row.get("rain_mm"),
            source=row.get("source", WEATHER_SOURCE_PASTED),
            notes=row.get("notes", "") or "",
            **{key: row.get(key) for key in ("temp_max_c", "cloud_min_pct", "cloud_max_pct", "wind_min_kmh", "wind_max_kmh")},
            rain_hours=row.get("rain_hours", "") or "",
        )
        for row in data.get("weather", [])
    ]
    coverage = [
        CoverageRow(
            evening_date=parse_iso_date(row["evening_date"]),
            detector_id=row["detector_id"],
            status=row["status"],
            partial_until=parse_iso_datetime(row.get("partial_until")),
            data_complete=row.get("data_complete") is True,
            completeness_assumed=row.get("completeness_assumed") is True,
        )
        for row in data.get("coverage", [])
    ]
    return Project(
        site_name=data["site_name"],
        latitude=float(data["latitude"]),
        longitude=float(data["longitude"]),
        timezone=data["timezone"],
        window_before_sunset_min=int(data["window_before_sunset_min"]),
        window_after_sunrise_min=int(data["window_after_sunrise_min"]),
        methodology=data.get("methodology", ""),
        reasoning=data.get("reasoning", ""),
        detectors=detectors,
        weather=weather,
        coverage=coverage,
        deployment_start=parse_iso_date(data["deployment_start"]),
        deployment_end=parse_iso_date(data["deployment_end"]),
        selected_start=parse_iso_date(data.get("selected_start")),
        selected_end=parse_iso_date(data.get("selected_end")),
        weather_source_default=data.get("weather_source_default", WEATHER_SOURCE_PASTED),
        selection_method=data.get("selection_method", "manual"),
        monitoring_periods=[SurveyPeriod(parse_iso_date(row["start"]), parse_iso_date(row["end"]))
                            for row in data.get("monitoring_periods", [])],
        surveys=[SurveyPeriod(parse_iso_date(row["start"]), parse_iso_date(row["end"]),
                              row.get("reasoning", ""), row.get("selection_method", "manual"))
                 for row in data.get("surveys", [])],
    )
