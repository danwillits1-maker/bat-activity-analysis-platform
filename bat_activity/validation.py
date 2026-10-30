from __future__ import annotations

import pandas as pd

from bat_activity.models import Project
from bat_activity.nights import survey_night_table


def validation_issues(classified: pd.DataFrame, project: Project) -> pd.DataFrame:
    issues: list[dict] = []
    if classified.empty:
        issues.append(
            {
                "severity": "info",
                "issue": "No activity rows supplied. Missing reviewed records can understate activity.",
                "source_file": None,
                "source_row": None,
                "recording_id": None,
                "action": "review_data_completeness",
            }
        )

    for _, row in classified.iterrows():
        if pd.notna(row.get("exclude_reason")):
            issues.append(
                {
                    "severity": "warning" if row["exclude_reason"] != "unparseable_timestamp" else "error",
                    "issue": str(row["exclude_reason"]),
                    "source_file": row.get("source_file"),
                    "source_row": row.get("source_row"),
                    "recording_id": row.get("recording_id"),
                    "evening_date": row.get("evening_date"),
                    "detector_id": row.get("detector_id"),
                    "timestamp": row.get("timestamp"),
                    "species": row.get("species"),
                    "action": "excluded_from_activity",
                }
            )

    night_table = survey_night_table(project)
    selected = night_table.loc[night_table["in_selected_block"]]
    analysis = classified.loc[classified.get("in_analysis", False)] if "in_analysis" in classified else classified
    for _, night in selected.iterrows():
        has_records = False
        if not analysis.empty:
            has_records = (
                (analysis["evening_date"] == night["evening_date"])
                & (analysis["detector_id"] == night["detector_id"])
            ).any()
        if night["confirmed_hours"] > 0 and not (night["data_complete"] or night.get("completeness_assumed", False)):
            issues.append({
                "severity": "warning",
                "issue": "reviewed_data_not_confirmed_complete",
                "evening_date": night["evening_date"],
                "detector_id": night["detector_id"],
                "action": "confirm_all_reviewed_data_supplied_before_using_rates",
            })
        elif night["confirmed_hours"] > 0 and not has_records:
            issues.append(
                {
                    "severity": "info",
                    "issue": "zero_under_assumed_effort" if night["coverage_status"] == "assumed_full" else "confirmed_zero_activity",
                    "source_file": None,
                    "source_row": None,
                    "recording_id": None,
                    "evening_date": night["evening_date"],
                    "detector_id": night["detector_id"],
                    "timestamp": None,
                    "species": None,
                    "action": "zero_assumes_intended_effort" if night["coverage_status"] == "assumed_full" else "zero_for_confirmed_recording_period_only",
                }
            )
        if night["coverage_status"] in {"unknown", "partial_missing_end"}:
            issues.append(
                {
                    "severity": "error",
                    "issue": f"coverage_incomplete:{night['coverage_status']}",
                    "source_file": None,
                    "source_row": None,
                    "recording_id": None,
                    "evening_date": night["evening_date"],
                    "detector_id": night["detector_id"],
                    "timestamp": None,
                    "species": None,
                    "action": "set_coverage_before_using_rates",
                }
            )
    return pd.DataFrame(issues)
