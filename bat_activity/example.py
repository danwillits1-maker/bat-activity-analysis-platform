from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo
from io import StringIO

import pandas as pd

from bat_activity.models import (
    COVERAGE_FULL,
    COVERAGE_PARTIAL,
    CoverageRow,
    Detector,
    NightWeather,
    Project,
    WEATHER_SOURCE_PASTED,
)

TZ = ZoneInfo("Europe/London")

# Fictional site. Coordinates are in Oxfordshire only so solar times are realistic.
DEMO_SITE_NAME = "Riverside Copse (synthetic demo)"


def demo_project() -> Project:
    start = date(2024, 5, 6)
    end = date(2024, 5, 12)
    detectors = [
        Detector("RC1", "Hedge line", 51.7522, -1.2550),
        Detector("RC2", "Woodland edge", 51.7515, -1.2572),
    ]
    weather_rows = [
        (date(2024, 5, 6), 4.5, 6.2, "cold, rain"),
        (date(2024, 5, 7), 6.0, 3.0, "cool, showers"),
        (date(2024, 5, 8), 11.0, 0.0, "mild, dry"),
        (date(2024, 5, 9), 12.5, 0.0, "mild, dry"),
        (date(2024, 5, 10), 10.0, 0.5, "mild, light rain"),
        (date(2024, 5, 11), 13.0, 0.0, "mild, dry"),
        (date(2024, 5, 12), 11.5, 0.2, "mild, trace rain"),
    ]
    weather = [
        NightWeather(evening, temp, rain, WEATHER_SOURCE_PASTED, notes)
        for evening, temp, rain, notes in weather_rows
    ]
    # Explicitly synthetic overnight ranges and rain intervals for reporting tests.
    for item in weather:
        item.temp_max_c = item.temp_min_c + 3
        item.cloud_min_pct = 20 if item.rain_mm == 0 else 60
        item.cloud_max_pct = 65 if item.rain_mm == 0 else 100
        item.wind_min_kmh = 4
        item.wind_max_kmh = 12
        item.rain_hours = "23:00-00:00 local" if item.rain_mm > 0 else ""
    coverage: list[CoverageRow] = []
    for evening in [date(2024, 5, d) for d in range(6, 13)]:
        coverage.append(CoverageRow(evening, "RC1", COVERAGE_FULL, None, True))
        if evening == date(2024, 5, 10):
            coverage.append(
                CoverageRow(
                    evening,
                    "RC2",
                    COVERAGE_PARTIAL,
                    datetime(2024, 5, 11, 1, 0, tzinfo=TZ),
                    True,
                )
            )
        else:
            coverage.append(CoverageRow(evening, "RC2", COVERAGE_FULL, None, True))
    return Project(
        site_name=DEMO_SITE_NAME,
        latitude=51.752,
        longitude=-1.256,
        timezone="Europe/London",
        window_before_sunset_min=30,
        window_after_sunrise_min=30,
        methodology=(
            "Synthetic static-detector example for software testing. "
            "Intended recording window is 30 minutes before sunset to 30 minutes after sunrise. "
            "One shared consecutive five-night block is selected for the survey. "
            "This is not a real site and is not an ecological finding."
        ),
        reasoning=(
            "Selected 8–12 May 2024 as the shared five-night block. "
            "6–7 May were colder and wetter, so those evenings were not chosen. "
            "10 May had light rain and RC2 stopped at 01:00; the night is still kept "
            "because a consecutive block was required and the rest of the window was milder."
        ),
        detectors=detectors,
        weather=weather,
        coverage=coverage,
        deployment_start=start,
        deployment_end=end,
        selected_start=date(2024, 5, 8),
        selected_end=date(2024, 5, 12),
        weather_source_default=WEATHER_SOURCE_PASTED,
    )


def demo_csv_text() -> str:
    """Reviewed-looking CSV. Headers follow common BatExplorer-style names plus Detector.

    Row meaning for this demo: one row is one recording-species identification.
    """
    rows = [
        "Timestamp,Species Text,Latitude [WGS84],Longitude [WGS84],Recording,Detector",
        # Night 6 May — outside the selected block; kept for review only.
        "2024-05-06 21:40:00,Pipistrellus pipistrellus,51.7522,-1.2550,rec_offblock_1,RC1",
        # Night 8 May RC1: two species in one recording = two contacts; duplicate row later.
        "2024-05-08 21:45:00,Pipistrellus pipistrellus,51.7522,-1.2550,rec_rc1_001,RC1",
        "2024-05-08 21:45:00,Myotis sp.,51.7522,-1.2550,rec_rc1_001,RC1",
        "2024-05-08 23:10:00,Pipistrellus pipistrellus,51.7522,-1.2550,rec_rc1_002,RC1",
        "2024-05-09 00:18:00,Pipistrellus pygmaeus,51.7522,-1.2550,rec_rc1_003,RC1",
        "2024-05-08 23:10:00,Pipistrellus pipistrellus,51.7522,-1.2550,rec_rc1_002,RC1",
        # Night 8 May RC2
        "2024-05-08 22:05:00,Nyctalus noctula,51.7515,-1.2572,rec_rc2_001,RC2",
        "2024-05-08 22:40:00,Pipistrellus pipistrellus,51.7515,-1.2572,rec_rc2_002,RC2",
        # Afternoon record — outside the recording window.
        "2024-05-09 16:02:00,Pipistrellus pipistrellus,51.7522,-1.2550,rec_daytime_1,RC1",
        # Night 9 May
        "2024-05-09 21:50:00,Pipistrellus pipistrellus,51.7522,-1.2550,rec_rc1_004,RC1",
        "2024-05-09 22:15:00,Pipistrellus pipistrellus,51.7515,-1.2572,rec_rc2_003,RC2",
        "2024-05-09 23:55:00,Myotis sp.,51.7515,-1.2572,rec_rc2_004,RC2",
        # Night 10 May — RC2 partial until 01:00 on 11 May.
        "2024-05-10 22:10:00,Pipistrellus pipistrellus,51.7522,-1.2550,rec_rc1_005,RC1",
        "2024-05-10 22:12:00,Pipistrellus pygmaeus,51.7522,-1.2550,rec_rc1_006,RC1",
        "2024-05-10 22:30:00,Nyctalus noctula,51.7515,-1.2572,rec_rc2_005,RC2",
        "2024-05-11 00:40:00,Pipistrellus pipistrellus,51.7515,-1.2572,rec_rc2_006,RC2",
        "2024-05-11 02:10:00,Pipistrellus pipistrellus,51.7515,-1.2572,rec_rc2_007,RC2",
        # Night 11 May
        "2024-05-11 21:55:00,Pipistrellus pipistrellus,51.7522,-1.2550,rec_rc1_007,RC1",
        "2024-05-11 22:20:00,Nyctalus noctula,51.7515,-1.2572,rec_rc2_008,RC2",
        "2024-05-11 22:21:00,Nyctalus noctula,51.7515,-1.2572,rec_rc2_008,RC2",
        # Night 12 May: no valid contacts. Confirmed zeros when coverage is full.
    ]
    return "\n".join(rows) + "\n"


def demo_records() -> pd.DataFrame:
    return pd.read_csv(StringIO(demo_csv_text()))


METHOD_NOTES = """
Contact rule used in this prototype: one contact is one recording plus one species
within a detector and survey night, after duplicates are removed.
Two species in the same recording are two contacts.
Repeated identical rows are not extra contacts. Contacts are not individual bats.

Effort: solar night length, intended recording window, and confirmed operational
hours are kept separate. Activity rate uses confirmed hours only, and only for
nights in the selected survey blocks. Each block is shared across detectors. A full-coverage night with no contacts
is a confirmed zero (rate 0) only after reviewed-data completeness is confirmed.
Partial coverage currently means recording from the intended start until the
entered stop time. Late starts and interruptions need a later increment.
"""
