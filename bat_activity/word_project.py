from __future__ import annotations

from datetime import datetime
from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.table import Table

from bat_activity.models import (
    CoverageRow,
    Detector,
    NightWeather,
    Project,
    SurveyPeriod,
    parse_iso_date,
    parse_iso_datetime,
)

TABLE_SURVEY = "Field"
TABLE_DETECTORS = "detector_id"
TABLE_NIGHTS = "evening_date"
TABLE_COVERAGE = "coverage_evening_date"


def _set_cell(cell, text: str) -> None:
    cell.text = "" if text is None else str(text)
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.font.name = "Calibri"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")


def _add_kv_table(document: Document, rows: list[tuple[str, str]]) -> None:
    table = document.add_table(rows=1 + len(rows), cols=2)
    table.style = "Table Grid"
    _set_cell(table.cell(0, 0), TABLE_SURVEY)
    _set_cell(table.cell(0, 1), "Value")
    for index, (key, value) in enumerate(rows, start=1):
        _set_cell(table.cell(index, 0), key)
        _set_cell(table.cell(index, 1), value)


def _add_grid(document: Document, headers: list[str], records: list[list[str]]) -> None:
    table = document.add_table(rows=1 + len(records), cols=len(headers))
    table.style = "Table Grid"
    for col, header in enumerate(headers):
        _set_cell(table.cell(0, col), header)
    for row_index, record in enumerate(records, start=1):
        for col, value in enumerate(record):
            _set_cell(table.cell(row_index, col), value)


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


def build_project_document(project: Project) -> bytes:
    document = Document()
    heading = document.add_heading("Bat activity survey — night selection record", level=1)
    heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
    document.add_paragraph(
        "This Word file is the save/reload record for the Bat Activity Analysis Platform. "
        "You can edit values and the reasoning paragraph. Do not rename table headers, "
        "merge cells, or turn this into a different report if you want to upload it again. "
        "This is not the analysis appendix."
    )

    _add_kv_table(
        document,
        [
            ("site_name", project.site_name),
            ("latitude", str(project.latitude)),
            ("longitude", str(project.longitude)),
            ("timezone", project.timezone),
            ("window_before_sunset_min", str(project.window_before_sunset_min)),
            ("window_after_sunrise_min", str(project.window_after_sunrise_min)),
            ("deployment_start", project.deployment_start.isoformat()),
            ("deployment_end", project.deployment_end.isoformat()),
            ("selected_start", "" if project.selected_start is None else project.selected_start.isoformat()),
            ("selected_end", "" if project.selected_end is None else project.selected_end.isoformat()),
            ("weather_source_default", project.weather_source_default),
            ("selection_method", project.selection_method),
            ("methodology", project.methodology),
        ],
    )

    document.add_paragraph(
        "Weather suggestion rule v1 compares periods with temperature and rainfall for every night: "
        "lowest total rainfall, then highest average nightly minimum temperature, then earliest start. "
        "Recording status is reviewed separately. This trial suggestion does not establish ecological suitability."
    )
    document.add_heading("Reasoning", level=2)
    document.add_paragraph(project.reasoning or "")

    document.add_heading("Monitoring periods before weather selection", level=2)
    _add_grid(document, ["monitoring_start", "monitoring_end"], [
        [period.start.isoformat(), period.end.isoformat()] for period in sorted(project.monitoring_periods, key=lambda period: period.start)
    ])

    document.add_heading("Selected survey periods", level=2)
    document.add_paragraph("All survey date blocks for this project are kept in this one file. Activity records are supplied separately as one combined CSV.")
    _add_grid(document, ["survey_start", "survey_end", "reasoning", "selection_method"], [
        [period.start.isoformat(), period.end.isoformat(), period.reasoning, period.selection_method]
        for period in sorted(project.surveys, key=lambda period: period.start)
    ])

    document.add_heading("Detectors", level=2)
    _add_grid(
        document,
        ["detector_id", "label", "latitude", "longitude"],
        [
            [d.detector_id, d.label, str(d.latitude), str(d.longitude)]
            for d in project.detectors
        ],
    )

    document.add_heading("Candidate nights and weather", level=2)
    document.add_paragraph(
        "Weather here is whatever was typed or pasted. It is not automatically a station or modelled source."
    )
    _add_grid(
        document,
        ["evening_date", "selected", "temp_min_c", "rain_mm", "source", "notes"],
        [
            [
                item.evening_date.isoformat(),
                "yes" if item.evening_date in project.selected_dates() else "no",
                "" if item.temp_min_c is None else str(item.temp_min_c),
                "" if item.rain_mm is None else str(item.rain_mm),
                item.source,
                item.notes,
            ]
            for item in project.weather
        ],
    )

    document.add_heading("Additional overnight weather", level=2)
    extra_fields = ["temp_max_c", "cloud_min_pct", "cloud_max_pct", "wind_min_kmh", "wind_max_kmh", "rain_hours"]
    _add_grid(document, ["weather_evening_date", *extra_fields], [
        [item.evening_date.isoformat(), *["" if getattr(item, key) is None else str(getattr(item, key)) for key in extra_fields]]
        for item in project.weather
    ])
    document.add_heading("Coverage", level=2)
    document.add_paragraph(
        "assumed_full = version 1 assumes operation throughout the intended window; effort is not verified, and failures or interruptions may understate rates. full = detector recorded through the intended window. "
        "partial = intended start through partial_until. failed / not_deployed = zero confirmed effort. "
        "completeness_assumed = yes means version 1 assumes the uploaded reviewed data cover all selected nights; missing records may understate activity and affect comparisons. data_complete is reserved for legacy user confirmations. "
        "Operational coverage alone does not establish zero activity."
    )
    _add_grid(
        document,
        ["coverage_evening_date", "detector_id", "status", "partial_until", "data_complete", "completeness_assumed"],
        [
            [
                row.evening_date.isoformat(),
                row.detector_id,
                row.status,
                _fmt_dt(row.partial_until),
                "yes" if row.data_complete else "no",
                "yes" if row.completeness_assumed else "no",
            ]
            for row in project.coverage
        ],
    )

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _table_rows(table: Table) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.rows:
        rows.append([cell.text.strip() for cell in row.cells])
    return rows


def load_project_document(data: bytes) -> Project:
    document = Document(BytesIO(data))
    tables = [_table_rows(table) for table in document.tables]
    survey_rows = next(rows for rows in tables if rows and rows[0] and rows[0][0] == TABLE_SURVEY)
    survey = {row[0]: row[1] if len(row) > 1 else "" for row in survey_rows[1:]}

    detector_rows = next(rows for rows in tables if rows and rows[0] and rows[0][0] == TABLE_DETECTORS)
    detectors = [
        Detector(
            detector_id=row[0],
            label=row[1],
            latitude=float(row[2]),
            longitude=float(row[3]),
        )
        for row in detector_rows[1:]
        if row[0]
    ]

    night_rows = next(rows for rows in tables if rows and rows[0] and rows[0][0] == TABLE_NIGHTS)
    weather = [
        NightWeather(
            evening_date=parse_iso_date(row[0]),
            temp_min_c=None if row[2] == "" else float(row[2]),
            rain_mm=None if row[3] == "" else float(row[3]),
            source=row[4] or survey.get("weather_source_default", "pasted_or_typed"),
            notes=row[5] if len(row) > 5 else "",
        )
        for row in night_rows[1:]
        if row[0]
    ]

    extra_rows = next((rows for rows in tables if rows and rows[0] and rows[0][0] == "weather_evening_date"), [])
    by_date = {item.evening_date.isoformat(): item for item in weather}
    for row in extra_rows[1:]:
        if row[0] in by_date:
            item = by_date[row[0]]
            for index, key in enumerate(("temp_max_c", "cloud_min_pct", "cloud_max_pct", "wind_min_kmh", "wind_max_kmh", "rain_hours"), 1):
                value = row[index] if len(row) > index else ""
                setattr(item, key, value if key == "rain_hours" else float(value) if value else None)

    coverage_rows = next(rows for rows in tables if rows and rows[0] and rows[0][0] == TABLE_COVERAGE)
    coverage = [
        CoverageRow(
            evening_date=parse_iso_date(row[0]),
            detector_id=row[1],
            status=row[2],
            partial_until=parse_iso_datetime(row[3]) if len(row) > 3 and row[3] else None,
            data_complete=len(row) > 4 and row[4].strip().lower() == "yes",
            completeness_assumed=len(row) > 5 and row[5].strip().lower() == "yes",
        )
        for row in coverage_rows[1:]
        if row[0]
    ]

    reasoning = ""
    capture = False
    for paragraph in document.paragraphs:
        style_name = paragraph.style.name if paragraph.style is not None else ""
        if style_name.startswith("Heading") and paragraph.text.strip() == "Reasoning":
            capture = True
            continue
        if capture and style_name.startswith("Heading"):
            break
        if capture:
            reasoning = (reasoning + "\n" + paragraph.text).strip()

    return Project(
        site_name=survey["site_name"],
        latitude=float(survey["latitude"]),
        longitude=float(survey["longitude"]),
        timezone=survey["timezone"],
        window_before_sunset_min=int(survey["window_before_sunset_min"]),
        window_after_sunrise_min=int(survey["window_after_sunrise_min"]),
        methodology=survey.get("methodology", ""),
        reasoning=reasoning,
        detectors=detectors,
        weather=weather,
        coverage=coverage,
        deployment_start=parse_iso_date(survey["deployment_start"]),
        deployment_end=parse_iso_date(survey["deployment_end"]),
        selected_start=parse_iso_date(survey.get("selected_start") or None),
        selected_end=parse_iso_date(survey.get("selected_end") or None),
        weather_source_default=survey.get("weather_source_default", "pasted_or_typed"),
        selection_method=survey.get("selection_method", "manual"),
        monitoring_periods=[SurveyPeriod(parse_iso_date(row[0]), parse_iso_date(row[1]))
                 for rows in tables if rows and rows[0] and rows[0][0] == "monitoring_start"
                 for row in rows[1:] if row[0]],
        surveys=[SurveyPeriod(parse_iso_date(row[0]), parse_iso_date(row[1]),
                              row[2] if len(row) > 2 else "", row[3] if len(row) > 3 else "manual")
                 for rows in tables if rows and rows[0] and rows[0][0] == "survey_start"
                 for row in rows[1:] if row[0]],
    )
