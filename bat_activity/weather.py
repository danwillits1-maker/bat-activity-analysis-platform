from __future__ import annotations

from io import StringIO
import csv
import math

import pandas as pd

from bat_activity.models import NightWeather, WEATHER_SOURCE_PASTED, parse_iso_date


def parse_weather_csv(text: str, source: str = WEATHER_SOURCE_PASTED) -> list[NightWeather]:
    frame = pd.read_csv(StringIO(text.strip()))
    frame.columns = [str(col).strip().lower() for col in frame.columns]
    required = {"evening_date"}
    if not required.issubset(set(frame.columns)):
        raise ValueError("Weather table must include an evening_date column.")
    records: list[NightWeather] = []
    seen = set()
    for _, row in frame.iterrows():
        evening = parse_iso_date(str(row["evening_date"]))
        if evening in seen:
            raise ValueError(f"Weather includes more than one row for {evening}.")
        seen.add(evening)
        temp = None if pd.isna(row.get("temp_min_c")) else float(row["temp_min_c"])
        rain = None if pd.isna(row.get("rain_mm")) else float(row["rain_mm"])
        if any(value is not None and not math.isfinite(value) for value in (temp, rain)):
            raise ValueError("Weather measurements must be finite numbers or blank.")
        if rain is not None and rain < 0:
            raise ValueError("Rainfall cannot be negative.")
        extra = {key: None if pd.isna(row.get(key)) else float(row[key])
                 for key in ("temp_max_c", "cloud_min_pct", "cloud_max_pct", "wind_min_kmh", "wind_max_kmh")}
        if any(v is not None and not math.isfinite(v) for v in extra.values()):
            raise ValueError("Weather measurements must be finite numbers or blank.")
        for key in ("cloud_min_pct", "cloud_max_pct"):
            if extra[key] is not None and not 0 <= extra[key] <= 100:
                raise ValueError("Cloud cover must be between 0 and 100 percent.")
        for key in ("wind_min_kmh", "wind_max_kmh"):
            if extra[key] is not None and extra[key] < 0:
                raise ValueError("Wind speed cannot be negative.")
        for low, high in ((temp, extra["temp_max_c"]), (extra["cloud_min_pct"], extra["cloud_max_pct"]), (extra["wind_min_kmh"], extra["wind_max_kmh"])):
            if low is not None and high is not None and low > high:
                raise ValueError("Weather minimum cannot exceed maximum.")
        records.append(
            NightWeather(
                **extra,
                rain_hours="" if pd.isna(row.get("rain_hours")) else str(row["rain_hours"]),
                evening_date=evening,
                temp_min_c=temp,
                rain_mm=rain,
                source=source if pd.isna(row.get("source")) else str(row["source"]),
                notes="" if pd.isna(row.get("notes")) else str(row.get("notes")),
            )
        )
    return records


def weather_template(project) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer)
    fields = ["temp_min_c", "temp_max_c", "cloud_min_pct", "cloud_max_pct", "wind_min_kmh", "wind_max_kmh", "rain_mm", "rain_hours", "source", "notes"]
    writer.writerow(["evening_date", *fields])
    by_date = {item.evening_date: item for item in project.weather}
    for evening in project.evening_dates():
        item = by_date.get(evening)
        writer.writerow([evening.isoformat(), *[(getattr(item, key) if getattr(item, key) is not None else "") if item else (project.weather_source_default if key == "source" else "") for key in fields]])
    return buffer.getvalue()
