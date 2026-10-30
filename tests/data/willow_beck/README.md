# Synthetic regression inputs

These fictional records support `tests/test_v1_trial.py`; they are not ecological evidence or an in-app demo.

- `all_1000_contacts_REFERENCE_ONLY.csv`: 1,000 invented recording-species rows across two detectors and three five-night periods.
- `expected_species_totals.csv`: the expected contact totals by identification.

The test checks 1,000 accepted contacts, 30 detector-nights, period totals of 402 / 333 / 265, version-one assumptions, and Word save/reload. The original manual trial package remains in the local-only `outputs/` folder.
