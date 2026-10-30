"""One editable Word download for copying factual results into a report."""
from io import BytesIO

import pandas as pd
from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from PIL import Image

from bat_activity.method_notes import METHOD_NOTE


def _value(value):
    if pd.isna(value):
        return "Not supplied"
    if hasattr(value, "strftime"):
        return value.strftime("%d %b %Y")
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _table(document, headers, rows, widths):
    """Editable tables with repeating headers and readable column widths."""
    available = 18.59
    widths = [width * available / sum(widths) for width in widths]
    table = document.add_table(rows=1, cols=len(headers))
    table.autofit = False
    for column, width in zip(table.columns, widths):
        column.width = Cm(width)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border = OxmlElement("w:" + edge)
        for key, val in (("val", "single"), ("sz", "4"), ("color", "D9D9D9")):
            border.set(qn("w:" + key), val)
        borders.append(border)
    table._tbl.tblPr.append(borders)
    table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
    for index, values in enumerate([headers, *rows]):
        row = table.rows[0] if index == 0 else table.add_row()
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        for cell, value, width in zip(row.cells, values, widths):
            cell.width = Cm(width)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cell.text = _value(value)
            paragraph = cell.paragraphs[0]
            if len(rows) <= 8:
                paragraph.paragraph_format.keep_with_next = index < len(rows)
            paragraph.paragraph_format.space_after = Pt(3)
            paragraph.paragraph_format.space_before = Pt(3)
            for run in paragraph.runs:
                run.font.size = Pt(10)
                run.bold = index == 0
            if index == 0:
                shade = OxmlElement("w:shd")
                shade.set(qn("w:fill"), "DCEAF0")
                cell._tc.get_or_add_tcPr().append(shade)
    document.add_paragraph().paragraph_format.space_after = Pt(2)
    return table


def build_results_document(tables, figures, project):
    """Use existing calculated tables/figures without changing their methodology."""
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21.59), Cm(27.94)
    section.top_margin = section.bottom_margin = Cm(1.5)
    section.left_margin = section.right_margin = Cm(1.5)
    for name in ("Normal", "Title", "Subtitle", "Caption", "Heading 1", "Heading 2"):
        style = document.styles[name]
        style.font.name = "Calibri"
        style.font.color.rgb = RGBColor(0, 0, 0)
    for border in list(document.styles["Title"].element.iter(qn("w:pBdr"))):
        border.getparent().remove(border)
    document.styles["Subtitle"].font.italic = False
    document.styles["Caption"].font.italic = False
    document.styles["Normal"].font.size = Pt(11)
    document.styles["Normal"].paragraph_format.space_after = Pt(6)
    document.add_paragraph("Static bat activity results", "Title")
    document.add_paragraph(project.site_name, "Subtitle")
    document.add_paragraph("Tables and figures for copying into an ecological report. Contacts are recording-species pairs, not individual bats. These are factual outputs for the ecologist to interpret.")
    document.add_paragraph("Version 1 assumes operation throughout the intended recording window and that all reviewed data have been supplied. Failures, interruptions or missing records can understate activity and affect comparisons.")
    audit = tables["report_coverage"]
    document.add_paragraph(
        f"{int(tables['total_contacts'].contacts.sum()):,} contacts included; "
        f"{int(audit.report_included.sum())} detector-nights analysed; "
        f"{int((~audit.report_included).sum())} detector-nights excluded. "
        f"Time zone: {project.timezone}. Recording window: {project.window_before_sunset_min} minutes before sunset to {project.window_after_sunrise_min} minutes after sunrise."
    )
    document.add_heading("Survey periods", level=1)
    key = tables["survey_key"]
    _table(document, ["Survey", "First evening", "Last evening", "Nights", "Detector-nights analysed", "Detector-nights excluded"],
           key[["survey_round", "first_evening", "last_evening", "selected_nights", "detector_nights_analysed", "detector_nights_excluded"]].values.tolist(),
           [3, 4.5, 4.5, 2.3, 6.2, 6.2])

    document.add_heading("Weather during survey nights", level=1)
    document.add_paragraph("Overnight values supplied by the user. Missing measurements remain Not supplied. Rain intervals use local time; following-morning dates are retained.")
    for survey, frame in tables["weather"].groupby("survey_round", sort=False):
        document.add_heading(survey, level=2)
        rows = []
        for row in frame.itertuples():
            span = lambda low, high: f"{_value(low)} to {_value(high)}"
            rows.append([row.evening_date, row.temp_min_c, row.temp_max_c,
                         span(row.cloud_min_pct, row.cloud_max_pct),
                         span(row.wind_min_kmh, row.wind_max_kmh), row.precipitation])
        _table(document, ["Evening", "Min temp C", "Max temp C", "Cloud %", "Wind km/h", "Rainfall and affected hours"], rows,
               [3.5, 2.5, 2.5, 4, 4, 10.2])

    document.add_heading("Weather sources", level=2)
    weather = tables["weather"]
    _table(document, ["Survey", "Evening", "Source", "Measurement notes"],
           weather[["survey_round", "evening_date", "source", "notes"]].values.tolist(), [3, 3.5, 6, 14.2])

    document.add_heading("Total contacts by identification", level=1)
    _table(document, ["Species or identification group", "Contacts"],
           tables["total_contacts"][["species", "contacts"]].values.tolist(), [20.7, 6])
    document.add_heading("Nightly activity by monitoring location", level=1)
    document.add_paragraph("Minimum, maximum, mean, median and IQR are contacts per recording hour. Rates use intended hours under the version-one assumption. Displayed values are rounded to three decimal places; calculations use full precision.")
    for detector_id, frame in tables["summary"].groupby("detector_id", sort=False):
        detector = next(d for d in project.detectors if d.detector_id == detector_id)
        document.add_heading(f"{detector_id} {detector.label}", level=2)
        cols = ["species", "minimum", "maximum", "mean", "median", "iqr", "total_contacts", "nights_analysed"]
        _table(document, ["Species or group", "Min", "Max", "Mean", "Median", "IQR", "Contacts", "Nights"],
               frame[cols].values.tolist(), [8.5, 2.4, 2.4, 2.4, 2.4, 2.4, 3.2, 3.0])

    titles = {
        "detector_locations": "Detector locations",
        "total_contacts": "Total contacts by identification",
        "nightly_activity_pipistrelles": "Nightly pipistrelle activity by location",
        "nightly_activity_other_species": "Other nightly activity by location",
        "survey_activity_stacked": "Site activity across survey periods",
    }
    for name, formats in figures.items():
        document.add_heading(titles.get(name, name.replace("_", " ")), level=1)
        payload = formats["png"]
        with Image.open(BytesIO(payload)) as image:
            width, height = image.size
        # Fit even tall multi-location charts on one page, without distortion.
        scale = min(18.59 / width, 19.5 / height)
        shape = document.add_picture(BytesIO(payload), width=Cm(width * scale))
        document.paragraphs[-1].paragraph_format.keep_with_next = True
        shape._inline.docPr.set("descr", titles.get(name, name))
        caption = "Rates use intended recording hours and assume all reviewed data have been supplied."
        if name == "detector_locations":
            from bat_activity.figures import map_caption
            caption = map_caption(formats)
        elif name == "survey_activity_stacked":
            caption += " Each eligible detector-night has equal weight. Columns describe sampled periods, not continuous monitoring."
        elif name == "total_contacts":
            caption = "One recording-species pair within a detector-night is one contact. Contacts are not counts of individual bats."
        document.add_paragraph(caption, "Caption")

    document.add_heading("Calculation notes", level=1)
    notes = METHOD_NOTE.replace(" Activity rates describe ", "\n\nActivity rates describe ").replace(" Surveys 1-8", "\n\nSurveys 1-8")
    for text in notes.split("\n\n"):
        document.add_paragraph(text).paragraph_format.keep_together = True
    document.add_heading("Stacked chart identification groups", level=2)
    _table(document, ["Original identification", "Chart group"],
           tables["species_group_key"][["species", "activity_group"]].values.tolist(), [15, 11.7])
    excluded = audit.loc[~audit.report_included]
    document.add_heading("Excluded detector nights", level=2)
    if excluded.empty:
        document.add_paragraph("No detector-nights excluded from reporting.")
    else:
        _table(document, ["Survey", "Evening", "Detector", "Reason"],
               excluded[["survey_round", "evening_date", "detector_id", "report_exclusion"]].values.tolist(),
               [3, 4.5, 3, 16.2])
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()
