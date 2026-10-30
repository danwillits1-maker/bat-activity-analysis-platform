"""Reporting calculations, kept separate from exploratory/import review counts."""
from dataclasses import asdict, replace
import re
import pandas as pd
from bat_activity.contacts import contact_counts, nightly_activity
from bat_activity.nights import survey_night_table

from bat_activity.method_notes import METHOD_NOTE


ACTIVITY_GROUPS = (
    'Pipistrellus spp.', 'Rhinolophus spp.', 'Myotis spp.',
    'Nyctalus/Eptesicus spp.', 'Other / uncertain',
)


def activity_group(species):
    """Broad chart groups only. Mixed groups and unrecognised labels stay uncertain."""
    text = str(species).casefold()
    patterns = (
        r'\bpipistrell\w*\b',
        r'\brhinolophus\b|\bhorseshoe\b',
        r'\bmyotis\b',
        r'\bnyctalus\b|\beptesicus\b|\bnoctule\b|\bserotine\b|\bleisler\w*\b',
        r'\bplecotus\b|\bbarbastell\w*\b|\blong[ -]eared\b|\bunidentified\b',
    )
    matches = [group for group, pattern in zip(ACTIVITY_GROUPS, patterns)
               if re.search(pattern, text)]
    return matches[0] if len(matches) == 1 else ACTIVITY_GROUPS[-1]


def survey_labels(rounds):
    """Use explicit selected blocks; do not infer survey boundaries from call gaps."""
    blocks = {(p.selected_start, p.selected_end) for p, _ in rounds}
    if not blocks or any(start is None or end is None or end < start for start, end in blocks):
        raise ValueError('Choose a valid date block for each survey before combining results.')
    if len(blocks) > 8:
        raise ValueError('This prototype supports up to eight selected survey blocks. Remove a retained survey before adding another.')
    return {block: f'Survey {index}' for index, block in enumerate(sorted(blocks), 1)}


def site_activity(eligible, counts, survey_key):
    """One observation per broad group and eligible detector-night, including zeros."""
    keys = ['survey_round', 'evening_date', 'detector_id']
    grouped = counts.copy()
    grouped['activity_group'] = grouped.species.map(activity_group)
    grouped = grouped.groupby([*keys, 'activity_group'], as_index=False).contacts.sum()
    grid = eligible.merge(pd.DataFrame({'activity_group': ACTIVITY_GROUPS}), how='cross')
    grid = grid.merge(grouped, on=[*keys, 'activity_group'], how='left')
    grid['contacts'] = grid.contacts.fillna(0)
    grid['rate'] = grid.contacts / grid.confirmed_hours
    means = grid.groupby(['survey_round', 'activity_group'], as_index=False).agg(
        mean_rate=('rate', 'mean'), total_contacts=('contacts', 'sum'))
    # Retain surveys with no eligible effort as missing, never as zero activity.
    return survey_key.merge(pd.DataFrame({'activity_group': ACTIVITY_GROUPS}), how='cross').merge(
        means, on=['survey_round', 'activity_group'], how='left')


def round_key(project):
    return f"{project.selected_start} to {project.selected_end}"


def build_analysis(rounds):
    """Analyse (Project, classified dataframe) pairs; the UI supplies one whole project.

    Reject overlapping detector-nights and inconsistent location identities instead of
    silently double-counting or treating different locations as the same detector.
    """
    # The interface supplies one project and its one combined upload. Split only
    # inside the calculation, using confirmed periods rather than gaps in calls.
    expanded = []
    for project, classified in rounds:
        if project.surveys:
            from bat_activity.workflow import selection_errors
            errors = selection_errors(project)
            if errors:
                raise ValueError(' '.join(errors))
            for period in project.survey_periods():
                scoped = replace(project, surveys=[], monitoring_periods=[], selected_start=period.start,
                                 selected_end=period.end, deployment_start=period.start,
                                 deployment_end=period.end, reasoning=period.reasoning,
                                 selection_method=period.selection_method)
                rows = classified
                if not classified.empty:
                    rows = classified.loc[classified.evening_date.isna() |
                                          classified.evening_date.isin(period.dates())].copy()
                expanded.append((scoped, rows))
        else:
            expanded.append((project, classified))
    rounds = expanded
    audits, count_frames, weather_rows, locations = [], [], [], {}
    labels = survey_labels(rounds)
    seen = set()
    site = None
    for project, classified in sorted(rounds, key=lambda pair: str(pair[0].selected_start)):
        identity = (project.site_name, project.latitude, project.longitude, project.timezone)
        if site is not None and identity != site:
            raise ValueError("All survey periods must belong to the same site and time zone.")
        site = identity
        label = labels[(project.selected_start, project.selected_end)]
        for detector in project.detectors:
            values = asdict(detector)
            old = locations.get(detector.detector_id)
            if old and (old['latitude'], old['longitude']) != (detector.latitude, detector.longitude):
                raise ValueError(f"Location {detector.detector_id} has different coordinates between rounds. Use distinct location IDs for moved detectors.")
            locations[detector.detector_id] = values
        audit = nightly_activity(classified, survey_night_table(project))
        audit = audit.loc[audit.in_selected_block].copy()
        for row in audit.itertuples():
            key = (row.detector_id, row.evening_date)
            if key in seen:
                raise ValueError(f"Overlapping survey periods repeat {row.detector_id} on {row.evening_date}. Check the chosen survey dates.")
            seen.add(key)
        audit['survey_round'] = label
        audit['report_included'] = audit.activity_included & audit.coverage_status.isin(['full', 'assumed_full'])
        audit['report_exclusion'] = audit.zero_vs_missing.where(~audit.activity_included, '')
        audit.loc[~audit.coverage_status.isin(['full', 'assumed_full']), 'report_exclusion'] = 'coverage:' + audit.coverage_status
        # Do not present exploratory partial-night rates as reporting rates.
        audit.loc[~audit.report_included, 'activity_rate_per_hour'] = pd.NA
        audits.append(audit)
        counts = contact_counts(classified)
        counts['survey_round'] = label
        count_frames.append(counts)
        by_date = {w.evening_date: w for w in project.weather}
        for evening in project.selected_dates():
            w = by_date.get(evening)
            values = asdict(w) if w else {'evening_date': evening}
            rain = values.get('rain_mm')
            hours = values.get('rain_hours', '')
            values['precipitation'] = ('Not supplied' if rain is None else 'None' if rain == 0 else f"{rain:g} mm; {hours or 'hours not supplied'}")
            values['survey_round'] = label
            weather_rows.append(values)
    audit = pd.concat(audits, ignore_index=True)
    counts = pd.concat(count_frames, ignore_index=True)
    eligible_columns = ['survey_round', 'evening_date', 'detector_id', 'confirmed_hours', 'coverage_status']
    if 'effort_basis' in audit:
        eligible_columns.append('effort_basis')
    eligible = audit.loc[audit.report_included, eligible_columns]
    counts = counts.merge(eligible[['survey_round', 'evening_date', 'detector_id']], on=['survey_round', 'evening_date', 'detector_id'], how='inner')
    species = sorted(counts.species.unique())
    nightly = eligible.merge(pd.DataFrame({'species': pd.Series(species, dtype='str')}), how='cross').merge(counts, on=['survey_round', 'evening_date', 'detector_id', 'species'], how='left')
    nightly['contacts'] = nightly.contacts.fillna(0).astype(int)
    nightly['activity_rate_per_hour'] = nightly.contacts / nightly.confirmed_hours
    summary_cols = ['detector_id', 'species', 'minimum', 'maximum', 'mean', 'median', 'q1', 'q3', 'iqr', 'total_contacts', 'nights_analysed']
    if nightly.empty:
        summary = pd.DataFrame(columns=summary_cols)
        seasonal = pd.DataFrame(columns=['survey_round', 'detector_id', 'species', 'mean_rate', 'nights_analysed'])
    else:
        summary = nightly.groupby(['detector_id', 'species']).agg(
            minimum=('activity_rate_per_hour', 'min'), maximum=('activity_rate_per_hour', 'max'),
            mean=('activity_rate_per_hour', 'mean'), median=('activity_rate_per_hour', 'median'),
            q1=('activity_rate_per_hour', lambda s: s.quantile(.25)), q3=('activity_rate_per_hour', lambda s: s.quantile(.75)),
            total_contacts=('contacts', 'sum'), nights_analysed=('contacts', 'size')).reset_index()
        summary['iqr'] = summary.q3 - summary.q1
        summary = summary[summary_cols]
        seasonal = nightly.groupby(['survey_round', 'detector_id', 'species']).agg(mean_rate=('activity_rate_per_hour', 'mean'), nights_analysed=('contacts', 'size')).reset_index()
    totals = counts.groupby('species', as_index=False).contacts.sum()
    weather = pd.DataFrame(weather_rows).reindex(columns=['survey_round', 'evening_date', 'temp_min_c', 'temp_max_c', 'cloud_min_pct', 'cloud_max_pct', 'wind_min_kmh', 'wind_max_kmh', 'rain_mm', 'rain_hours', 'precipitation', 'source', 'notes'])
    survey_key = pd.DataFrame([
        {'survey_round': label, 'first_evening': start, 'last_evening': end,
         'selected_nights': (end-start).days+1,
         'detector_nights_analysed': int(audit.loc[audit.survey_round.eq(label)].report_included.sum()),
         'detector_nights_excluded': int((~audit.loc[audit.survey_round.eq(label)].report_included).sum()),
         'locations_analysed': eligible.loc[eligible.survey_round.eq(label)].detector_id.nunique()}
        for (start, end), label in labels.items()
    ])
    grouping = pd.DataFrame({'species': pd.Series(species, dtype='str')})
    grouping['activity_group'] = grouping.species.map(activity_group)
    return {'weather': weather, 'summary': summary, 'nightly_species': nightly,
            'round_activity': seasonal, 'site_activity': site_activity(eligible, counts, survey_key),
            'survey_key': survey_key, 'species_group_key': grouping,
            'total_contacts': totals, 'report_coverage': audit, 'locations': pd.DataFrame(locations.values())}
