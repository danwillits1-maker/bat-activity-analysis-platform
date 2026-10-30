from __future__ import annotations



from copy import deepcopy

from dataclasses import asdict

from datetime import date, datetime

from io import BytesIO

from hashlib import sha256



import pandas as pd

import streamlit as st



from bat_activity.contacts import (

    classify_records,

    contact_counts,

    match_detectors_by_coordinates,

    nightly_activity,

    standardise_records,

    normalise_headers,

)

from bat_activity.analysis import build_analysis, METHOD_NOTE

from bat_activity.figures import reporting_figures, map_caption

from bat_activity.word_results import build_results_document

from bat_activity.models import (

    COVERAGE_STATUSES,

    CoverageRow,

    Detector,

    Project,

    SurveyPeriod,

    parse_iso_datetime,

)

from bat_activity.nights import candidate_blocks, survey_night_table, suggested_survey_period

from bat_activity.validation import validation_issues

from bat_activity.weather import parse_weather_csv, weather_template

from bat_activity.word_project import build_project_document, load_project_document

from bat_activity.workflow import project_errors, selection_errors, coverage_errors, synchronise_coverage



st.set_page_config(page_title="Bat Activity Analysis Platform", page_icon="static/brand/djw-icon-orange.png", layout="wide")

from bat_activity.appearance import apply_brand
apply_brand()





def _init_state() -> None:

    if "project" not in st.session_state:

        st.session_state.project = None

        st.session_state.selection_mode = "manual"

    if "selection_mode" not in st.session_state:

        st.session_state.selection_mode = "saved"

    if "raw_records" not in st.session_state:

        st.session_state.raw_records = None

        st.session_state.raw_name = ""

    if "classified" not in st.session_state:

        st.session_state.classified = None

    if "weather_text" not in st.session_state:

        st.session_state.weather_text = weather_template(st.session_state.project) if st.session_state.project is not None else ""

    if "editor_nonce" not in st.session_state:

        st.session_state.editor_nonce = 0

    if "docx_hash" not in st.session_state:

        st.session_state.docx_hash = None

    if "csv_hash" not in st.session_state:

        st.session_state.csv_hash = None

    if "parsed_ready" not in st.session_state:

        st.session_state.parsed_ready = False

    # Remove a previous version's active sample session once, while preserving

    # personal projects and files that were uploaded by the user.

    if st.session_state.pop("demo_loaded", False):

        _load_project(None)

    st.session_state.pop("demo_setup", None)





def _rebuild_classified() -> pd.DataFrame:

    project: Project = st.session_state.project

    raw = st.session_state.raw_records

    if raw is None or len(raw) == 0:

        st.session_state.classified = pd.DataFrame()

        return st.session_state.classified

    standardised = standardise_records(raw, source_name=st.session_state.get("raw_name", "upload.csv"))

    standardised = match_detectors_by_coordinates(standardised, project)

    st.session_state.classified = classify_records(standardised, project)

    return st.session_state.classified





def _detectors_from_editor(frame: pd.DataFrame) -> list[Detector]:

    detectors: list[Detector] = []

    for _, row in frame.iterrows():

        if pd.isna(row.get("detector_id")) or str(row.get("detector_id")).strip() == "":

            continue

        detectors.append(

            Detector(

                detector_id=str(row["detector_id"]).strip(),

                label="" if pd.isna(row.get("label")) else str(row["label"]),

                latitude=float(row["latitude"]),

                longitude=float(row["longitude"]),

            )

        )

    return detectors





def _coverage_from_editor(frame: pd.DataFrame) -> list[CoverageRow]:

    rows: list[CoverageRow] = []

    for _, row in frame.iterrows():

        if pd.isna(row.get("evening_date")) or pd.isna(row.get("detector_id")):

            continue

        evening = row["evening_date"]

        if hasattr(evening, "date"):

            evening = evening.date()

        elif not isinstance(evening, date):

            evening = date.fromisoformat(str(evening)[:10])

        until = row.get("partial_until")

        partial_until = None

        if pd.notna(until) and str(until).strip() not in {"", "NaT", "None"}:

            parsed = parse_iso_datetime(str(until)) if not isinstance(until, datetime) else until

            partial_until = parsed

        rows.append(

            CoverageRow(

                evening_date=evening,

                detector_id=str(row["detector_id"]).strip(),

                status=str(row["status"]),

                partial_until=partial_until,

                data_complete=bool(row.get("data_complete", False)),

            )

        )

    return rows





def _load_project(project: Project | None) -> None:

    st.session_state.project = project

    st.session_state.raw_records = None

    st.session_state.raw_name = ""

    st.session_state.classified = None

    st.session_state.parsed_ready = False

    st.session_state.selection_mode = "saved" if project is not None else "manual"

    st.session_state.csv_hash = None

    st.session_state.docx_hash = None

    st.session_state.pop("analysis_signature", None)

    st.session_state.weather_text = weather_template(project) if project is not None else ""

    st.session_state.editor_nonce += 1





def _editor_input(key: str, frame: pd.DataFrame) -> pd.DataFrame:

    """Editor changes are offsets against a stable input, not yesterday's edited result.



    Changing the input frame on every rerun can reset the browser's editor state.

    Keys change when a project is loaded or the relevant night/detector set changes.

    """

    baseline_key = "baseline_" + key

    if baseline_key not in st.session_state:

        st.session_state[baseline_key] = frame.copy(deep=True)

    return st.session_state[baseline_key].copy(deep=True)





def _stop_for_errors(errors: list[str]) -> None:

    if errors:

        for error in errors:

            st.error(error)

        st.session_state.classified = None

        st.stop()





def _widget(name: str) -> str:

    return f"{name}_{st.session_state.editor_nonce}"





def _choose_dates_manually() -> None:

    st.session_state.selection_mode = "manual"





def _review_message(value):

    """Plain-language explanations for the internal record-check codes."""

    if pd.isna(value):

        return ""

    messages = {

        "unparseable_timestamp": "Date or time could not be read",

        "ambiguous_or_nonexistent_local_time": "Date or time needs clarification because of a clock change",

        "outside_recording_window": "Outside the planned recording hours",

        "outside_selected_block": "Outside your selected survey dates",

        "unknown_detector": "Static detector could not be identified",

        "outside_confirmed_coverage": "Outside the time the static was confirmed working",

        "missing_species": "Species identification is missing",

        "missing_recording_id": "Recording name is missing",

        "duplicate_recording_species": "Repeated recording and species entry",

        "reviewed_data_not_confirmed_complete": "Confirm that all reviewed data have been supplied for this static and night",

        "zero_under_assumed_effort": "No contacts supplied; zero assumes complete reviewed data and operation throughout the intended window",

        "confirmed_zero_activity": "No contacts in the intended recording window; all reviewed data supplied",

        "excluded_from_activity": "Not included in the activity calculation",

        "confirm_all_reviewed_data_supplied_before_using_rates": "Confirm data completeness before using the activity rate",

        "zero_assumes_intended_effort": "Zero assumes complete reviewed data and operation throughout the intended window",

        "zero_for_confirmed_recording_period_only": "Zero activity applies only to the confirmed recording period",

        "set_coverage_before_using_rates": "Check the recording status before using activity rates",

        "review_data_completeness": "Check whether all reviewed data have been supplied",

    }

    if str(value).startswith(("no_confirmed_coverage:", "coverage_incomplete:")):

        status = str(value).split(":", 1)[1]

        return "Recording status needs checking: " + status.replace("_", " ")

    return messages.get(str(value), value)





_init_state()

project: Project | None = st.session_state.project



st.title("Bat Activity Analysis Platform")

st.caption(

    "Prototype for static-detector surveys. Acoustic identification stays in specialist software. "

    "This first version is for local trial, not a compliance decision."

)



with st.sidebar:

    st.subheader("Project")

    if st.button("Start a new project", width="stretch", help="Start a blank survey. Download any existing results first; this clears the current project and uploaded records."):

        _load_project(None)

        st.session_state.pop("analysis_rounds", None)

        st.rerun()

    uploaded_project = st.file_uploader("Upload saved Word project", type=["docx"], key=_widget("project_upload"))

    if uploaded_project is not None:

        payload = uploaded_project.getvalue()

        digest = sha256(payload).hexdigest()

        if st.session_state.docx_hash != digest:

            try:

                loaded = load_project_document(payload)

                errors = project_errors(loaded) + selection_errors(loaded) + coverage_errors(loaded)

                if errors:

                    raise ValueError(" ".join(errors))

            except Exception as error:

                st.error(f"Could not load that project record: {error}. Use the unchanged table headers in a project file downloaded from this app.")

            else:

                _load_project(loaded)

                st.session_state.docx_hash = digest

                st.rerun()

    st.caption("Contacts are recording-species pairs, not individual bats. Rates assume operation throughout the intended recording hours and that all reviewed data have been supplied for the chosen survey periods.")



setup_tab, nights_tab, import_tab, valid_tab, results_tab, export_tab = st.tabs(

    [

        "1. Survey setup",

        "2. Weather and nights",

        "3. Upload reviewed data",

        "4. Validation",

        "5. Results",

        "6. Export",

    ]

)



with setup_tab:

    st.markdown("Enter your site and detectors, then select **Apply survey setup**. Your changes are saved together, so you can finish entering dates and locations before they are checked.")

    st.subheader("Survey setup")

    st.caption("Enter the survey nights you have already selected. Every night in each period will be analysed.")

    with st.form(_widget("survey_setup")):

        c1, c2, c3 = st.columns(3)

        site_name = c1.text_input("Site name", project.site_name if project else "", key=_widget("site_name"))

        latitude = c2.number_input("Site latitude", value=float(project.latitude) if project else None, format="%.6f", key=_widget("latitude"))

        longitude = c3.number_input("Site longitude", value=float(project.longitude) if project else None, format="%.6f", key=_widget("longitude"))

        c4, c7, c8 = st.columns(3)

        timezone = c4.text_input("Time zone", project.timezone if project else "Europe/London", key=_widget("timezone"))

        before_sunset = int(c7.number_input("Minutes before sunset", value=project.window_before_sunset_min if project else 30, min_value=0, key=_widget("before_sunset")))

        after_sunrise = int(c8.number_input("Minutes after sunrise", value=project.window_after_sunrise_min if project else 30, min_value=0, key=_widget("after_sunrise")))

        methodology = st.text_area("Project methodology notes", project.methodology if project else "", height=120, key=_widget("methodology"))

        st.markdown("**Monitoring periods**")

        st.caption("Dates are evening dates, including the final night. Add a row for each deployment round using the + row control below the table.")

        monitoring_frame = pd.DataFrame([

            {"start": period.start, "end": period.end} for period in project.deployment_periods()

        ] if project else [{"start": None, "end": None}])

        monitoring_frame.index = range(1, len(monitoring_frame)+1)

        monitoring_key = _widget("monitoring_editor")

        edited_monitoring = st.data_editor(

            _editor_input(monitoring_key, monitoring_frame), key=monitoring_key,

            num_rows="dynamic", hide_index=False, width="stretch",

            column_config={

                "_index": st.column_config.NumberColumn("Monitoring period"),

                "start": st.column_config.DateColumn("Start date (first evening)", required=True, format="DD/MM/YYYY"),

                "end": st.column_config.DateColumn("End date (last evening)", required=True, format="DD/MM/YYYY"),

            },

        )

        st.markdown("**Static Detectors**")

        st.caption("Add your detector IDs and coordinates. Use the same IDs as your reviewed CSV.")

        detector_frame = pd.DataFrame([asdict(item) for item in project.detectors] if project else [], columns=["detector_id", "label", "latitude", "longitude"]).astype({"detector_id": "string", "label": "string", "latitude": "float64", "longitude": "float64"})

        detector_key = f"detector_editor_{st.session_state.editor_nonce}"

        edited_detectors = st.data_editor(

            _editor_input(detector_key, detector_frame), num_rows="dynamic", width="stretch", key=detector_key,

            column_config={"detector_id": st.column_config.TextColumn("detector_id"), "label": st.column_config.TextColumn("label"),

                           "latitude": st.column_config.NumberColumn("latitude", format="%.6f"), "longitude": st.column_config.NumberColumn("longitude", format="%.6f")},

        )

        apply_setup = st.form_submit_button("Apply survey setup", type="primary")

    if apply_setup:

        try:

            if not site_name.strip():

                raise ValueError("Enter a site name.")

            if latitude is None or longitude is None:

                raise ValueError("Enter the site coordinates.")

            monitoring = []

            for row in edited_monitoring.to_dict("records"):

                if pd.isna(row.get("start")) or pd.isna(row.get("end")):

                    raise ValueError("Enter both dates for every monitoring period, or remove the unused row.")

                monitoring.append(SurveyPeriod(pd.Timestamp(row["start"]).date(), pd.Timestamp(row["end"]).date()))

            if not monitoring:

                raise ValueError("Add at least one monitoring period.")

            monitoring.sort(key=lambda period: period.start)

            deployment_start = monitoring[0].start

            deployment_end = max(period.end for period in monitoring)

            candidate = deepcopy(project) if project else Project(

                site_name=site_name.strip(), latitude=latitude, longitude=longitude, timezone=timezone,

                window_before_sunset_min=before_sunset, window_after_sunrise_min=after_sunrise,

                methodology=methodology, reasoning="", detectors=[], weather=[], coverage=[],

                deployment_start=deployment_start, deployment_end=deployment_end,

            )

            candidate.site_name = site_name.strip()

            candidate.latitude, candidate.longitude, candidate.timezone = latitude, longitude, timezone

            candidate.deployment_start, candidate.deployment_end = deployment_start, deployment_end

            candidate.window_before_sunset_min, candidate.window_after_sunrise_min = before_sunset, after_sunrise

            candidate.monitoring_periods = monitoring

            candidate.methodology = methodology

            candidate.detectors = _detectors_from_editor(edited_detectors)

            errors = project_errors(candidate)

            if candidate.survey_periods() and selection_errors(candidate):

                candidate.surveys = []

                candidate.selected_start = candidate.selected_end = None

                candidate.reasoning = ""

            if errors:

                raise ValueError(" ".join(errors))

            synchronise_coverage(candidate)

        except (ValueError, TypeError) as error:

            st.error(f"Could not apply survey setup: {error}")

        else:

            st.session_state.project = candidate

            st.session_state.weather_text = weather_template(candidate)

            st.session_state.editor_nonce += 1

            st.session_state.setup_applied = True

            st.rerun()

    if st.session_state.pop("setup_applied", False):

        st.success("Survey setup applied. Your details are saved in this session.")

    st.caption("Download the Word project record on Weather and nights to keep a copy for later.")



# Keep incomplete drafts editable without calculating nights from missing values.

project = st.session_state.project

if project is None:

    st.info("Enter your survey setup above, or load a saved Word project from the sidebar.")

    st.stop()



# Version-one workflow: setup dates are the analysis dates. Coverage is an

# explicit assumption, never a user confirmation of detector operation.

from bat_activity.workflow import apply_v1_assumptions

apply_v1_assumptions(project)



with nights_tab:

    st.subheader("Weather and survey nights")

    st.write("Your survey nights come directly from Survey setup. Add the weather for those nights; no further date selection is needed.")

    st.warning("Version 1 assumes each detector operated throughout the intended recording window. Rates use intended hours, not verified operational effort. Failures, late starts and interruptions are not accounted for and may understate activity rates.")

    st.dataframe(pd.DataFrame([

        {"Survey": f"Survey {index}", "First night": period.start,

         "Last night": period.end, "Nights": len(period.dates())}

        for index, period in enumerate(project.survey_periods(), 1)

    ]), hide_index=True, width="stretch")

    st.text_area("Weather table (CSV)", height=180, key="weather_text")

    if st.button("Apply pasted weather", type="primary"):

        try:

            project.weather = parse_weather_csv(st.session_state.weather_text, project.weather_source_default)

            st.success("Weather applied. Continue to Upload reviewed data.")

        except Exception as error:

            st.error(f"Could not read weather table: {error}")

    with st.expander("Review weather and intended recording hours"):

        try:

            night_table = survey_night_table(project)

            st.dataframe(night_table.loc[night_table.in_selected_block, [

                "evening_date", "detector_id", "intended_hours", "temp_min_c", "rain_mm", "weather_source"

            ]], hide_index=True, width="stretch")

        except (ValueError, OverflowError) as error:

            _stop_for_errors([f"Could not calculate recording times: {error}"])

    st.download_button(

        "Download Word project record", data=build_project_document(project),

        file_name=f"{project.site_name[:40].strip() or 'survey'}_night_selection.docx",

        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",

    )

    st.caption("Optional: keep this record to reload later. Keep its table headers unchanged.")

    st.session_state.project = project



# Settings and uploads identify when to show the completeness reminder again.

analysis_signature = repr((

    project.latitude, project.longitude, project.timezone,

    project.deployment_start, project.deployment_end,

    [(period.start, period.end) for period in project.survey_periods()],

    project.window_before_sunset_min, project.window_after_sunrise_min,

    [asdict(d) for d in project.detectors],

    [(r.evening_date, r.detector_id, r.status, r.partial_until) for r in project.coverage],

))

st.session_state.analysis_signature = analysis_signature



with import_tab:

    st.markdown(

        "Upload one manually reviewed CSV containing records for all chosen survey periods. The application assigns records to surveys by evening date. "

        "Real BatExplorer static exports have not been tested yet."

    )

    st.caption("Trial format: comma-separated UTF-8 CSV, ISO timestamps such as 2024-05-08 21:45:00. Use an explicit UTC offset for repeated clock-change hours. One row is one recording-species identification.")

    st.caption("Required columns: Timestamp, Species Text, Recording, Detector. Coordinates can be supplied instead of Detector when the location can be matched.")

    uploaded_csv = st.file_uploader("Reviewed activity CSV", type=["csv"], key=_widget("csv_upload"))

    if uploaded_csv is not None:

        payload = uploaded_csv.getvalue()

        digest = sha256(uploaded_csv.name.encode() + b"\0" + payload).hexdigest()

        if st.session_state.csv_hash != digest:

            try:

                raw = pd.read_csv(BytesIO(payload))

                headers = normalise_headers(list(raw.columns))

                if not {"timestamp", "species", "recording_id"}.issubset(headers):

                    raise ValueError("Include Timestamp, Species Text and Recording columns.")

                if "detector_id" not in headers and not {"latitude", "longitude"}.issubset(headers):

                    raise ValueError("Include a Detector column, or both latitude and longitude.")

            except Exception as error:

                st.session_state.raw_records = None

                st.session_state.classified = None

                st.session_state.parsed_ready = False

                st.error(f"Could not import this CSV: {error}")

                st.stop()

            st.session_state.raw_records = raw

            st.session_state.raw_name = uploaded_csv.name

            st.session_state.classified = None

            st.session_state.csv_hash = digest

            st.session_state.parsed_ready = False

            for row in project.coverage:

                row.data_complete = False

    if st.session_state.raw_records is not None:

        st.write(f"Loaded **{st.session_state.raw_name}** ({len(st.session_state.raw_records)} rows).")

        st.dataframe(st.session_state.raw_records.head(25), width="stretch")

    if st.button("Apply uploaded data", type="primary", disabled=st.session_state.raw_records is None):

        st.session_state.parsed_ready = True

        st.success("Uploaded data applied. Open Validation to check any issues before reviewing results.")



from bat_activity.workflow import apply_v1_data_assumption

apply_v1_data_assumption(project, st.session_state.parsed_ready)

if st.session_state.parsed_ready:

    _rebuild_classified()



with valid_tab:

    classified = st.session_state.classified

    if classified is None:

        st.info("Upload your reviewed CSV, then select Apply uploaded data on the upload screen.")

    else:

        notice_context = (st.session_state.editor_nonce, analysis_signature,

                          st.session_state.csv_hash, st.session_state.raw_name)

        if st.session_state.get("review_notice_context") != notice_context:

            st.session_state.review_notice_context = notice_context

            st.session_state.review_notice_dismissed = False

        if not st.session_state.get("review_notice_dismissed", False):

            notice = st.container()

            with notice:

                st.warning("Include all reviewed data for your selected survey nights. Missing records can understate activity and affect comparisons.")

                if st.button("Understood — hide reminder", key="dismiss_review_notice"):

                    st.session_state.review_notice_dismissed = True

                    st.rerun()

        st.session_state.project = project

        issues = validation_issues(classified, project)

        in_analysis = int(classified["in_analysis"].sum()) if not classified.empty else 0

        st.metric("Rows kept for activity", in_analysis)

        st.metric("Rows excluded or flagged", 0 if classified.empty else int((~classified["in_analysis"]).sum()))

        st.markdown("**Checks to review** - records left out of the calculation stay visible.")

        displayed_issues = issues.copy()

        for column in ("issue", "action"):

            if column in displayed_issues:

                displayed_issues[column] = displayed_issues[column].map(_review_message)

        st.dataframe(displayed_issues.rename(columns={

            "severity": "Importance", "issue": "What needs checking", "action": "What to do",

            "source_file": "Uploaded file", "source_row": "Row in file", "recording_id": "Recording",

            "evening_date": "Survey night", "detector_id": "Static detector",

            "timestamp": "Date and time", "species": "Species",

        }), width="stretch")

        st.markdown("**Uploaded records and checks**")

        displayed_records = classified.reindex(columns=[

            "source_file", "source_row", "timestamp_raw", "species", "recording_id",

            "detector_id", "evening_date", "survey_round", "in_analysis", "exclude_reason",

        ]).copy()

        displayed_records["exclude_reason"] = displayed_records["exclude_reason"].map(_review_message)

        st.dataframe(displayed_records.rename(columns={

            "source_file": "Uploaded file", "source_row": "Row in file",

            "timestamp_raw": "Date and time supplied", "species": "Species",

            "recording_id": "Recording", "detector_id": "Static detector",

            "evening_date": "Survey night", "survey_round": "Survey", "in_analysis": "Included in analysis",

            "exclude_reason": "Reason if left out",

        }), width="stretch")



report_tables = None

report_figures = {}

with results_tab:

    st.subheader("Analysis for reporting")

    st.caption("One project, all selected survey periods, one reviewed CSV. Records are assigned automatically to the chosen dates; no separate uploads or retained rounds are needed.")

    classified = st.session_state.classified

    if classified is None:

        st.info("Upload your combined reviewed CSV, then select Apply uploaded data on the upload screen.")

    else:

        try:

            report_tables = build_analysis([(project, classified)])

        except ValueError as error:

            st.error(str(error))

        if report_tables is not None:

            st.caption("Rates assume operation throughout the intended recording window. Missing reviewed records can understate activity and affect comparisons. Nights with blocking record errors are excluded.")

            with st.expander("Calculation notes and species groups"):

                st.write(METHOD_NOTE)

                st.dataframe(report_tables['species_group_key'].rename(columns={'species': 'Original identification', 'activity_group': 'Stacked chart group'}), hide_index=True, width="stretch")

            audit = report_tables['report_coverage']

            included_count = int(audit.report_included.sum())

            contacts_total = int(report_tables['total_contacts'].contacts.sum())

            c1, c2, c3 = st.columns(3)

            c1.metric("Contacts included", contacts_total)

            c2.metric("Detector-nights included", included_count)

            c3.metric("Detector-nights excluded", len(audit)-included_count)

            st.subheader("Survey dates and recording coverage")

            st.caption("Surveys 1-8 follow the selected date blocks in chronological order. Adding an earlier survey updates the numbering. These are not inferred from gaps in detections.")

            st.dataframe(report_tables['survey_key'].rename(columns={

                'survey_round': 'Survey', 'first_evening': 'First evening', 'last_evening': 'Last evening',

                'selected_nights': 'Selected nights', 'detector_nights_analysed': 'Detector-nights analysed',

                'detector_nights_excluded': 'Detector-nights excluded', 'locations_analysed': 'Locations analysed',

            }), hide_index=True, width="stretch")

            with st.expander("Review included and excluded nights", expanded=False):

                st.dataframe(audit[["survey_round", "evening_date", "detector_id", "coverage_status", "intended_hours", "contacts", "activity_rate_per_hour", "report_included", "report_exclusion"]], width="stretch")

                st.caption("Counts on excluded nights are retained for review only and do not contribute to reporting totals.")

            st.subheader("Weather during the selected survey periods")

            st.caption("Use overnight measurements for the adopted survey window, not whole-calendar-day ranges. Cloud cover is percent; wind is km/h. Rain hours use local project time and should identify intervals, including the following morning. Source and measurement details belong in the source/notes fields.")

            weather_names = {"survey_round": "Survey round", "evening_date": "Evening date", "temp_min_c": "Temperature min (°C)", "temp_max_c": "Temperature max (°C)", "cloud_min_pct": "Cloud min (%)", "cloud_max_pct": "Cloud max (%)", "wind_min_kmh": "Wind min (km/h)", "wind_max_kmh": "Wind max (km/h)", "precipitation": "Precipitation", "source": "Source", "notes": "Source / measurement notes"}

            st.dataframe(report_tables['weather'][list(weather_names)].rename(columns=weather_names), width="stretch", hide_index=True)

            missing = report_tables['weather'][['temp_min_c', 'temp_max_c', 'cloud_min_pct', 'cloud_max_pct', 'wind_min_kmh', 'wind_max_kmh', 'rain_mm']].isna().any().any()

            if missing:

                st.info("Some weather measurements are not supplied. Add them in Weather and nights; blank values are unknown, not zero.")

            st.subheader("Activity summary by monitoring location and species")

            st.caption("Minimum, maximum, mean, median and IQR are nightly contacts/hour. Statistics use unrounded rates; displayed values are rounded to three decimal places.")

            names = {'detector_id': 'Monitoring location', 'species': 'Species / group', 'minimum': 'Minimum', 'maximum': 'Maximum', 'mean': 'Mean', 'median': 'Median', 'iqr': 'IQR', 'total_contacts': 'Total contacts', 'nights_analysed': 'Nights analysed'}

            st.dataframe(report_tables['summary'][list(names)].rename(columns=names).round(3), width="stretch", hide_index=True)

            if included_count == 0:

                st.warning("No nights qualify for reporting. Review the selected dates and any record errors shown on Validation.")

            elif report_tables['nightly_species'].empty:

                st.info("Eligible nights contain no contacts. There are no recorded species to plot; the coverage table retains the confirmed zero nights.")

            report_figures = reporting_figures(report_tables, imagery=True)

            for name, figure in report_figures.items():

                st.image(figure['png'], caption=name.replace('_', ' ').capitalize(), width="stretch")
                if name == 'detector_locations':
                    st.caption(map_caption(figure))

            st.caption("The stacked survey chart combines monitoring locations. Each eligible detector-night has equal weight; different recording coverage can change how much each location contributes. Survey columns describe the sampled periods, not continuous monitoring across the year.")



with export_tab:
    classified = st.session_state.classified
    if classified is None:
        st.info("Upload your reviewed CSV, then select Apply uploaded data on the upload screen.")
    elif report_tables is not None:
        st.subheader("Download results")
        st.write("One Word document with editable tables and embedded charts, ready to copy into your report.")
        st.download_button(
            "Download Word results", type="primary", data=build_results_document(report_tables, report_figures, project),
            file_name="bat_activity_results.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        with st.expander("Source records for reference"):
            st.caption("Optional: every uploaded record with its survey assignment and any exclusion reason.")
            st.download_button("Download checked records CSV", data=classified.to_csv(index=False).encode("utf-8"), file_name="checked_records.csv", mime="text/csv")
