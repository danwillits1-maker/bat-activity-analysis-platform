from __future__ import annotations

from datetime import datetime, timezone
import re

import pandas as pd

from bat_activity.models import Project
from bat_activity.nights import (
    assign_evening_date,
    confirmed_window,
    localise_timestamp,
    windows_for_project,
)

REQUIRED_COLUMNS = ("timestamp", "species", "recording_id", "detector_id")

COLUMN_ALIASES = {
    "timestamp": ("timestamp", "datetime", "date/time", "date time"),
    "species": ("species text", "species", "auto id", "id"),
    "recording_id": ("recording_id", "recording", "recording id", "filename", "file", "file name"),
    "detector_id": ("detector_id", "detector", "detector id", "static", "static id", "location"),
    "latitude": ("latitude [wgs84]", "latitude", "lat"),
    "longitude": ("longitude [wgs84]", "longitude", "lon", "lng"),
    "source_row": ("source_row",),
}


def normalise_headers(columns: list[str]) -> dict[str, str]:
    lookup = {str(col).strip().lower(): col for col in columns}
    mapping: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lookup:
                mapping[canonical] = lookup[alias]
                break
    return mapping


def standardise_records(raw: pd.DataFrame, source_name: str = "upload") -> pd.DataFrame:
    raw = raw.reset_index(drop=True)
    if raw.empty:
        return pd.DataFrame(
            columns=[
                "source_file",
                "source_row",
                "timestamp_raw",
                "timestamp",
                "species",
                "recording_id",
                "detector_id",
                "latitude",
                "longitude",
            ]
        )
    mapping = normalise_headers(list(raw.columns))
    frame = pd.DataFrame(index=raw.index)
    frame["source_file"] = source_name
    frame["source_row"] = range(2, len(raw) + 2)
    # Retain every supplied field alongside the standardised fields.
    for column in raw.columns:
        frame[f"raw:{column}"] = raw[column]
    if "timestamp" in mapping:
        frame["timestamp_raw"] = raw[mapping["timestamp"]].astype(str)
        frame["timestamp"] = pd.Series(
            [_parse_timestamp(value) for value in raw[mapping["timestamp"]]], dtype=object
        )
    else:
        frame["timestamp_raw"] = None
        frame["timestamp"] = pd.NaT
    frame["species"] = raw[mapping["species"]].astype("string").str.strip() if "species" in mapping else None
    if "recording_id" in mapping:
        frame["recording_id"] = raw[mapping["recording_id"]].astype("string").str.strip()
    else:
        frame["recording_id"] = pd.NA
    if "detector_id" in mapping:
        frame["detector_id"] = raw[mapping["detector_id"]].astype("string").str.strip()
    else:
        frame["detector_id"] = pd.NA
    frame["latitude"] = pd.to_numeric(raw[mapping["latitude"]], errors="coerce") if "latitude" in mapping else pd.NA
    frame["longitude"] = pd.to_numeric(raw[mapping["longitude"]], errors="coerce") if "longitude" in mapping else pd.NA
    return frame


def _parse_timestamp(value):
    """The trial CSV contract uses ISO dates; never guess day/month order."""
    if pd.isna(value) or not re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", str(value).strip()):
        return pd.NaT
    return pd.to_datetime(value, errors="coerce")


def match_detectors_by_coordinates(frame: pd.DataFrame, project: Project, max_metres: float = 80) -> pd.DataFrame:
    """Fill missing detector_id from the nearest deployed detector, if close enough."""
    out = frame.copy()
    known_ids = {detector.detector_id for detector in project.detectors}

    def nearest(row: pd.Series) -> object:
        current = row.get("detector_id")
        if pd.notna(current) and str(current).strip():
            return current
        if pd.isna(row.get("latitude")) or pd.isna(row.get("longitude")):
            return current
        best_id = None
        best_distance = None
        for detector in project.detectors:
            distance = _approx_metres(
                float(row["latitude"]),
                float(row["longitude"]),
                detector.latitude,
                detector.longitude,
            )
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_id = detector.detector_id
        if best_distance is not None and best_distance <= max_metres:
            return best_id
        return current

    out["detector_id"] = out.apply(nearest, axis=1)
    out["detector_assignment"] = "supplied_or_unmatched"
    inferred = frame["detector_id"].isna() | frame["detector_id"].eq("").fillna(False)
    out.loc[inferred & out["detector_id"].isin(known_ids), "detector_assignment"] = "inferred_from_coordinates"
    return out


def _approx_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat_m = (lat1 - lat2) * 111_320
    lon_m = (lon1 - lon2) * 111_320 * 0.62
    return (lat_m**2 + lon_m**2) ** 0.5


def classify_records(frame: pd.DataFrame, project: Project) -> pd.DataFrame:
    windows = windows_for_project(project)
    selected = set(project.selected_dates())
    rows: list[dict] = []
    for _, record in frame.iterrows():
        classified = record.to_dict()
        classified["parse_ok"] = pd.notna(record["timestamp"])
        classified["evening_date"] = None
        classified["survey_round"] = None
        classified["in_recording_window"] = False
        classified["in_selected_block"] = False
        classified["in_confirmed_coverage"] = False
        classified["exclude_reason"] = None
        if not classified["parse_ok"]:
            classified["exclude_reason"] = "unparseable_timestamp"
            rows.append(classified)
            continue
        ts: datetime = record["timestamp"].to_pydatetime()
        try:
            evening = assign_evening_date(ts, project, windows)
        except ValueError:
            classified["exclude_reason"] = "ambiguous_or_nonexistent_local_time"
            rows.append(classified)
            continue
        classified["evening_date"] = evening
        classified["survey_round"] = project.survey_label(evening) if evening is not None else None
        classified["in_recording_window"] = evening is not None
        if evening is None:
            classified["exclude_reason"] = "outside_recording_window"
            rows.append(classified)
            continue
        classified["in_selected_block"] = evening in selected
        if evening not in selected:
            classified["exclude_reason"] = "outside_selected_block"
            rows.append(classified)
            continue
        detector_id = record.get("detector_id")
        if pd.isna(detector_id) or detector_id not in {d.detector_id for d in project.detectors}:
            classified["exclude_reason"] = "unknown_detector"
            rows.append(classified)
            continue
        start, end, _sunset, _sunrise = windows[evening]
        conf_start, conf_end, status, _hours = confirmed_window(
            project, evening, str(detector_id), start, end
        )
        if conf_start is None or conf_end is None or status in {"failed", "not_deployed", "unknown", "partial_missing_end"}:
            classified["exclude_reason"] = f"no_confirmed_coverage:{status}"
            rows.append(classified)
            continue
        local_ts = localise_timestamp(ts, project.timezone)
        in_coverage = conf_start.astimezone(timezone.utc) <= local_ts.astimezone(timezone.utc) <= conf_end.astimezone(timezone.utc)
        classified["in_confirmed_coverage"] = in_coverage
        if not in_coverage:
            classified["exclude_reason"] = "outside_confirmed_coverage"
        species = record.get("species")
        if pd.isna(species) or str(species).strip() in {"", "nan", "None"}:
            classified["exclude_reason"] = "missing_species"
        recording_id = record.get("recording_id")
        if pd.isna(recording_id) or str(recording_id).strip() in {"", "nan", "None"}:
            classified["exclude_reason"] = classified["exclude_reason"] or "missing_recording_id"
        rows.append(classified)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["is_duplicate"] = False
    valid_mask = out["exclude_reason"].isna()
    duplicated = out.loc[valid_mask].duplicated(
        subset=["detector_id", "evening_date", "recording_id", "species"], keep="first"
    )
    duplicate_index = out.loc[valid_mask].index[duplicated]
    out.loc[duplicate_index, "is_duplicate"] = True
    out.loc[duplicate_index, "exclude_reason"] = "duplicate_recording_species"
    out["in_analysis"] = out["exclude_reason"].isna()
    return out


def contact_counts(classified: pd.DataFrame) -> pd.DataFrame:
    """Count a contact as one recording-species pair in the analysis set.

    Two species in one recording are two contacts. Repeated rows of the same
    recording and species are not extra contacts. This is not a count of bats.
    """
    if classified.empty:
        return pd.DataFrame(columns=["evening_date", "detector_id", "species", "contacts"])
    analysis = classified.loc[classified["in_analysis"]].copy()
    if analysis.empty:
        return pd.DataFrame(columns=["evening_date", "detector_id", "species", "contacts"])
    grouped = (
        analysis.groupby(["evening_date", "detector_id", "species"], dropna=False)
        .size()
        .reset_index(name="contacts")
    )
    return grouped


def nightly_activity(classified: pd.DataFrame, night_table: pd.DataFrame) -> pd.DataFrame:
    counts = contact_counts(classified)
    totals = (
        counts.groupby(["evening_date", "detector_id"], dropna=False)["contacts"]
        .sum()
        .reset_index()
        if not counts.empty
        else pd.DataFrame(columns=["evening_date", "detector_id", "contacts"])
    )
    merged = night_table.merge(totals, on=["evening_date", "detector_id"], how="left")
    selected = merged["in_selected_block"]
    effort = merged["confirmed_hours"] > 0
    complete = merged["data_complete"].fillna(False).astype(bool) | merged.get(
        "completeness_assumed", pd.Series(False, index=merged.index)
    ).fillna(False).astype(bool)
    unresolved = pd.Series(False, index=merged.index)
    if not classified.empty:
        serious = classified["exclude_reason"].isin([
            "unparseable_timestamp", "ambiguous_or_nonexistent_local_time",
            "unknown_detector", "missing_species", "missing_recording_id",
        ]) if "exclude_reason" in classified else pd.Series(False, index=classified.index)
        for record in classified.loc[serious].itertuples():
            affected = selected.copy()
            if pd.notna(record.evening_date):
                affected &= merged["evening_date"].eq(record.evening_date)
            if pd.notna(record.detector_id) and record.detector_id in set(merged.detector_id):
                affected &= merged["detector_id"].eq(record.detector_id)
            unresolved |= affected
    usable = complete & ~unresolved
    merged["contacts"] = merged["contacts"].astype("Int64")
    merged.loc[selected & effort & usable, "contacts"] = merged.loc[selected & effort & usable, "contacts"].fillna(0)
    merged["activity_included"] = selected & effort & usable
    merged["activity_rate_per_hour"] = pd.Series(pd.NA, index=merged.index, dtype="Float64")
    include = merged["activity_included"]
    merged.loc[include, "activity_rate_per_hour"] = (
        merged.loc[include, "contacts"] / merged.loc[include, "confirmed_hours"]
    )
    merged["zero_vs_missing"] = "not_in_selected_block"
    merged.loc[selected & effort & ~complete, "zero_vs_missing"] = "reviewed_data_not_confirmed_complete"
    merged.loc[selected & effort & usable & (merged["contacts"] == 0), "zero_vs_missing"] = (
        "confirmed_zero_activity"
    )
    merged.loc[selected & effort & usable & (merged["contacts"] > 0), "zero_vs_missing"] = (
        "activity_recorded"
    )
    merged.loc[selected & effort & usable & merged["contacts"].eq(0) & merged.get("coverage_status", pd.Series("", index=merged.index)).eq("assumed_full"), "zero_vs_missing"] = "zero_under_assumed_effort"
    merged.loc[selected & (merged["confirmed_hours"] <= 0), "zero_vs_missing"] = "no_confirmed_effort"
    merged.loc[selected & effort & unresolved, "zero_vs_missing"] = "unresolved_record_errors"
    return merged
