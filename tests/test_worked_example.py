from datetime import date

from bat_activity.contacts import classify_records, contact_counts, nightly_activity, standardise_records
from bat_activity.example import demo_csv_text, demo_project, demo_records
from bat_activity.nights import candidate_blocks, survey_night_table
from bat_activity.word_project import build_project_document, load_project_document


def _classified():
    project = demo_project()
    raw = standardise_records(demo_records(), source_name="demo.csv")
    return project, classify_records(raw, project)


def test_shared_block_is_five_consecutive_nights():
    project = demo_project()
    assert project.selected_dates() == [
        date(2024, 5, 8),
        date(2024, 5, 9),
        date(2024, 5, 10),
        date(2024, 5, 11),
        date(2024, 5, 12),
    ]
    blocks = candidate_blocks(project, length=5)
    assert len(blocks) == 3
    current = blocks.loc[blocks["is_current_selection"]].iloc[0]
    assert current["mean_temp_min_c"] == 11.6
    assert current["total_rain_mm"] == 0.7


def test_word_round_trip_keeps_selection_and_partial_coverage():
    original = demo_project()
    restored = load_project_document(build_project_document(original))
    assert restored.site_name == original.site_name
    assert restored.selected_start == original.selected_start
    assert restored.selected_end == original.selected_end
    assert restored.reasoning.startswith("Selected 8–12 May")
    partial = [
        row
        for row in restored.coverage
        if row.detector_id == "RC2" and row.evening_date == date(2024, 5, 10)
    ][0]
    assert partial.status == "partial"
    assert partial.partial_until.hour == 1


def test_contact_rule_and_exclusions():
    project, classified = _classified()
    reasons = classified.groupby("exclude_reason", dropna=False).size().to_dict()
    assert reasons[("outside_selected_block")] == 1
    assert reasons[("outside_recording_window")] == 1
    assert reasons[("duplicate_recording_species")] == 2
    assert reasons[("outside_confirmed_coverage")] == 1
    counts = contact_counts(classified)
    pairs = {
        (row.evening_date, row.detector_id, row.species): int(row.contacts)
        for row in counts.itertuples()
    }
    assert pairs[(date(2024, 5, 8), "RC1", "Pipistrellus pipistrellus")] == 2
    assert pairs[(date(2024, 5, 8), "RC1", "Myotis sp.")] == 1
    assert pairs[(date(2024, 5, 8), "RC1", "Pipistrellus pygmaeus")] == 1
    assert pairs[(date(2024, 5, 10), "RC2", "Nyctalus noctula")] == 1
    assert pairs[(date(2024, 5, 10), "RC2", "Pipistrellus pipistrellus")] == 1
    assert (date(2024, 5, 12), "RC1", "Pipistrellus pipistrellus") not in pairs
    assert counts["contacts"].sum() == 15


def test_midnight_call_stays_on_evening_date():
    _project, classified = _classified()
    midnight = classified.loc[classified["recording_id"] == "rec_rc1_003"].iloc[0]
    assert midnight["evening_date"] == date(2024, 5, 8)
    assert bool(midnight["in_analysis"]) is True


def test_zero_nights_and_partial_effort():
    project, classified = _classified()
    nights = survey_night_table(project)
    activity = nightly_activity(classified, nights)
    rc2_partial = activity.loc[
        (activity["evening_date"] == date(2024, 5, 10)) & (activity["detector_id"] == "RC2")
    ].iloc[0]
    assert rc2_partial["coverage_status"] == "partial"
    assert rc2_partial["confirmed_hours"] < rc2_partial["intended_hours"]
    assert rc2_partial["confirmed_hours"] > 0
    assert rc2_partial["contacts"] == 2

    rc1_zero = activity.loc[
        (activity["evening_date"] == date(2024, 5, 12)) & (activity["detector_id"] == "RC1")
    ].iloc[0]
    assert rc1_zero["contacts"] == 0
    assert rc1_zero["zero_vs_missing"] == "confirmed_zero_activity"
    assert rc1_zero["activity_rate_per_hour"] == 0

    off_block = activity.loc[
        (activity["evening_date"] == date(2024, 5, 6)) & (activity["detector_id"] == "RC1")
    ].iloc[0]
    assert bool(off_block["in_selected_block"]) is False
    assert bool(off_block["activity_included"]) is False


def test_demo_csv_is_readable():
    assert "Species Text" in demo_csv_text()
    assert len(demo_records()) == 20
