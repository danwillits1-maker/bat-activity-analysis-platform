# Bat Activity Analysis Platform

A Python/Streamlit portfolio project that turns reviewed static-detector survey records into checked contact summaries, charts and editable Word results.

Built from experience of repetitive ecological data preparation and reporting, it brings survey settings, weather, source-record checks and reporting into one workflow. It analyses reviewed identifications; it does not identify audio or count individual bats.

Version one is a portfolio prototype. There is no in-app demo, account system or project database. The recording-effort and upload-completeness assumptions below are part of its method.

## Project structure

`app.py` contains the screens, `bat_activity/` the processing and exports, `tests/` the checks and synthetic fixtures, and `static/brand/` the visual assets. See [the folder guide](docs/FOLDER_GUIDE.md).

## Run locally

From the project folder, create an environment and install the packages:

```shell
python -m venv .venv
```

On Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

On macOS/Linux, use `.venv/bin/python` in place of `.\.venv\Scripts\python.exe`. Keep the terminal running and open the printed local address. Use a Python version compatible with the pinned packages in `requirements.txt`.

## Workflow

1. **Survey setup:** site, time zone, recording offsets, already-selected survey periods and detectors. Apply once. All evenings in these periods are analysed; up to eight non-overlapping periods.
2. **Weather and nights:** paste weather CSV, apply, review the date summary. Optional Word project download is here; reload from the sidebar later. There is no weather ranking or further night selection.
3. **Upload reviewed data:** one combined UTF-8 comma-separated CSV for all periods; Apply uploaded data.
4. **Validation:** review exclusions. Analysis assumes all reviewed data have been supplied; a short reminder can be dismissed with Understood. It returns for a new upload or changed survey settings, without blocking results.
5. **Results:** weather, contact totals, location/species nightly-rate statistics, boxplots, one stacked survey chart and an automatic satellite detector map.
6. **Export:** one Word results document with editable tables, embedded charts and calculation notes, ready to copy into a report. The checked-record CSV remains available under Source records for reference. The separate reloadable project record is on Weather and nights.

## Recording-effort limitation

Version one assumes every detector operated throughout the intended recording window: sunset/sunrise plus setup offsets. Rates use intended elapsed hours, including clock changes, **not verified operational effort**. Detector failures, late starts and interruptions are not accounted for and may understate rates. There is no recording-status entry. Saved records use `assumed_full`, distinct from legacy confirmed `full`. Exported assumed hours use `hours_used_for_rate`. Version one also assumes the uploaded reviewed data cover every selected night. Missing records can understate activity and affect comparisons. This is saved as `completeness_assumed`, separate from legacy user-confirmed `data_complete`. No individual confirmations are required. Absent contacts become zero under these assumptions; blocking record errors still withhold affected rates.

Existing projects with monitoring periods now analyse all nights entered on setup, replacing old kept sub-blocks. Older records without monitoring rows retain their saved selected blocks. Keep Word table headers unchanged for reload. Original reviewed CSVs must be retained separately.

## CSV and calculation rules

Required activity headers: `Timestamp,Species Text,Recording,Detector`. Coordinates may replace Detector if matched; inferred assignments are visible. Example: `2024-05-08 21:45:00,Myotis sp.,recording_001.wav,RC1`.

Use ISO timestamps; unambiguous naive timestamps use the project time zone. Repeated clock-change hours need explicit UTC offsets. Impossible local times are flagged. Calls after midnight belong to the preceding evening. Outside-period/window rows and duplicates remain available for audit.

One recording-species pair within a detector-night is a contact, not an individual bat. Preserve uncertain identifications. Mean rates are unweighted means of nightly rates, including complete zero nights under the effort assumption. Quartiles use linear interpolation; boxplot whiskers use 1.5 IQR. Survey numbering follows entered periods chronologically, never gaps in calls.

Weather CSV: `evening_date,temp_min_c,rain_mm,source,notes`, with optional `temp_max_c,cloud_min_pct,cloud_max_pct,wind_min_kmh,wind_max_kmh,rain_hours`. Measurements describe the overnight window. Missing rainfall is unknown; explicit zero is dry. Sources/notes preserve observed, station or modelled provenance. Rain intervals are user supplied with following-morning dates where needed.

## Local trial and checks

Tests cover counting, exclusions, date/time handling, reporting, Word save/reload and Streamlit interactions. Synthetic fixtures in `tests/data/willow_beck/` also check 1,000 contacts across 30 detector-nights. They provide software checks, not ecological validation.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Real BatExplorer export compatibility and representative-size performance remain unverified. Weather is supplied manually. Word results provide factual material for an ecologist's template, not compliance certification or automatic ecological interpretation.

## Satellite detector map

Results fetches a free EOX cloudless 2024 satellite background for the detector coordinates entered on Survey setup, including new UK locations. Chosen detector labels are overlaid automatically. The identical figure is embedded in Word, with north, approximate scale, imagery year and credits. No key or billing account is needed. Approximately 10 m imagery can look soft at site scale. If imagery cannot load, a clearly labelled plain map is used instead. Successful backgrounds are cached in memory; changing coordinates requests a new extent.

This personal portfolio uses EOX's non-commercial service. The map figure includes modified Copernicus Sentinel data and is shared under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/), with the detector overlay identified as a modification. See [EOX terms](https://cloudless.eox.at/pricing). Other results/calculations are unchanged.

## Brand styling

The app uses a light workspace with pale teal form/table surfaces and orange actions, framed by a matching dark navy DJW logo banner and sidebar. Plus Jakarta Sans is served locally from static/brand. This is a fixed appearance with no theme switch. The bundled font licence and source are in that folder. Streamlit theme settings are in .streamlit/config.toml. Restart the local server after changing server/static-serving settings. Exported results use white pages for easy copying into company templates.
