from datetime import datetime
from io import BytesIO

import pandas as pd


def export_frame(frame):
    """Keep assumed effort explicit; never export it under confirmed-hour labels."""
    assumed = 'coverage_status' in frame and frame.coverage_status.eq('assumed_full').any()
    if not assumed:
        return frame.copy()
    return frame.rename(columns={'confirmed_hours': 'hours_used_for_rate',
                                 'confirmed_start': 'recording_start_used',
                                 'confirmed_end': 'recording_end_used'}).copy()


def excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    """Use ISO strings so Excel preserves offsets, including mixed DST offsets."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            export = export_frame(frame)
            for column in export.columns:
                if pd.api.types.is_datetime64_any_dtype(export[column]):
                    export[column] = export[column].astype(str)
                elif export[column].dtype == object:
                    export[column] = export[column].map(
                        lambda value: value.isoformat() if isinstance(value, datetime) else value
                    )
            export.to_excel(writer, sheet_name=name[:31], index=False)
    return buffer.getvalue()


def results_zip(tables, figures, project, classified):
    from zipfile import ZipFile, ZIP_DEFLATED
    from bat_activity.analysis import METHOD_NOTE
    from bat_activity.word_project import build_project_document
    buffer = BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        from bat_activity.figures import map_caption
        location_note = map_caption(figures['detector_locations']) if 'detector_locations' in figures else 'No location figure supplied.'
        archive.writestr('calculation_notes.txt', METHOD_NOTE + "\n\nWeather uses supplied overnight summaries, not automatically fetched observations. Missing is not zero. Rainfall timing is user-supplied. " + location_note + "\nTables use full calculation precision. PNG and SVG figures are supplied for insertion into company templates.\n")
        archive.writestr('reporting_tables.xlsx', excel_bytes(tables))
        for name, frame in tables.items():
            archive.writestr(f'tables/{name}.csv', export_frame(frame).to_csv(index=False))
        for name, formats in figures.items():
            for suffix, data in formats.items():
                archive.writestr(f'figures/{name}.{suffix}', data)
        archive.writestr('project_record.docx', build_project_document(project))
        archive.writestr('checked_records.csv', classified.to_csv(index=False))
    return buffer.getvalue()
