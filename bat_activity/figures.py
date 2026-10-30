"""Reporting figures with an optional online satellite background."""
import base64
from html import escape
from pathlib import Path
from io import BytesIO
import math
from PIL import Image, ImageDraw, ImageFont
from bat_activity.analysis import ACTIVITY_GROUPS
from bat_activity.basemap import map_geometry, fetch_background, MAP_NOTE, ATTRIBUTION

COLOURS = ['#5497A7', '#E9631A', '#02111B', '#316371', '#B54B15', '#8DBBC6', '#687C86', '#C6A381']
FONT_PATH = Path(__file__).resolve().parents[1] / 'static/brand/PlusJakartaSans.ttf'


class Canvas:
    def __init__(self, width, height, title):
        self.width, self.height = width, height
        self.im = Image.new('RGB', (width, height), 'white')
        self.draw = ImageDraw.Draw(self.im)
        self.svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><title>{escape(title)}</title><rect width="100%" height="100%" fill="white"/>']
        self.text(25, 24, title, size=20)

    def text(self, x, y, text, size=14, fill='#24343c', centre=False):
        text = str(text)
        try:
            font = ImageFont.truetype(str(FONT_PATH), size)
        except OSError:
            font = ImageFont.load_default(size=size)
        if centre:
            x -= self.draw.textlength(text, font=font)/2
        self.draw.text((x, y), text, font=font, fill=fill)
        self.svg.append(f'<text x="{x}" y="{y+size}" font-family="Plus Jakarta Sans, sans-serif" font-size="{size}" fill="{fill}">{escape(text)}</text>')

    def line(self, x1, y1, x2, y2, fill='#8a969c', width=1):
        self.draw.line((x1, y1, x2, y2), fill=fill, width=width)
        self.svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{fill}" stroke-width="{width}"/>')

    def rect(self, x, y, w, h, fill):
        self.draw.rectangle((x, y, x+w, y+h), fill=fill)
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"/>')

    def dot(self, x, y, fill='#24343c', radius=3):
        self.draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=fill)
        self.svg.append(f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{fill}"/>')

    def image(self, payload, x, y):
        with Image.open(BytesIO(payload)) as im:
            self.im.paste(im, (x, y))
            w, h = im.size
        encoded = base64.b64encode(payload).decode('ascii')
        self.svg.append(f'<image x="{x}" y="{y}" width="{w}" height="{h}" href="data:image/png;base64,{encoded}"/>')

    def output(self):
        buffer = BytesIO()
        self.im.save(buffer, format='PNG')
        return {'png': buffer.getvalue(), 'svg': ('\n'.join(self.svg) + '</svg>').encode()}


def columns(frame, category, value, title, ylabel):
    """One labelled column per category; rows are already aggregated."""
    width = max(1000, 160 * len(frame) + 120)
    c = Canvas(width, 540, title)
    c.text(25, 58, ylabel)
    top, bottom, left, right = 100, 400, 90, width-35
    maximum = max(float(frame[value].max()), 0.01)
    for i in range(5):
        y = bottom - (bottom-top)*i/4
        c.line(left, y, right, y, '#e0e6e9')
        c.text(15, y-8, f'{maximum*i/4:.3g}')
    step = (right-left)/max(len(frame), 1)
    for i, row in enumerate(frame.to_dict('records')):
        x = left + step*(i+.2)
        h = float(row[value])/maximum*(bottom-top)
        c.rect(x, bottom-h, step*.6, h, COLOURS[0])
        c.text(x, bottom-h-22, f'{row[value]:.3g}')
        words = str(row[category]).split()
        for j in range(0, len(words), 2):
            c.text(left+step*i+4, bottom+15+j//2*18, ' '.join(words[j:j+2]), size=12)
    return c.output()


def boxplots(nightly, title):
    groups = list(nightly.groupby(['detector_id', 'species'], sort=True))
    c = Canvas(1200, 130+46*len(groups), title)
    maximum = max(float(nightly.activity_rate_per_hour.max()), .01)
    left, right = 330, 1145
    x = lambda value: left + float(value)/maximum*(right-left)
    for i in range(5):
        c.line(x(maximum*i/4), 80, x(maximum*i/4), c.height-50, '#e0e6e9')
        c.text(x(maximum*i/4), c.height-40, f'{maximum*i/4:.3g}')
    for i, ((detector, species), rows) in enumerate(groups):
        values = rows.activity_rate_per_hour
        q1, median, q3 = values.quantile([.25, .5, .75])
        iqr = q3-q1
        inside = values[(values >= q1-1.5*iqr) & (values <= q3+1.5*iqr)]
        y = 95+46*i
        c.text(18, y-9, f'{detector} | {species} (n={len(values)})', size=12)
        c.line(x(inside.min()), y, x(inside.max()), y, '#24343c', 2)
        for v in (inside.min(), inside.max()):
            c.line(x(v), y-7, x(v), y+7, '#24343c', 2)
        c.rect(x(q1), y-11, max(1, x(q3)-x(q1)), 22, COLOURS[0])
        c.line(x(median), y-12, x(median), y+12, '#17262f', 3)
        for v in values[(values < q1-1.5*iqr) | (values > q3+1.5*iqr)]:
            c.dot(x(v), y)
    c.text(500, c.height-20, 'Nightly contacts per recording hour (see effort assumption)', size=12)
    return c.output()


def seasonal_chart(frame):
    """One site-wide stacked column per selected survey, not one figure per location."""
    surveys = frame[['survey_round', 'first_evening', 'last_evening', 'detector_nights_analysed', 'locations_analysed']].drop_duplicates().sort_values('first_evening')
    groups = [name for name in ACTIVITY_GROUPS
              if frame.loc[frame.activity_group.eq(name)].total_contacts.sum() > 0]
    colours = dict(zip(ACTIVITY_GROUPS, COLOURS[:5]))
    legend_height = max(len(groups), 1)*22
    c = Canvas(max(1100, len(surveys)*140+120), 575+legend_height+len(surveys)*22,
               'Site-wide bat activity by survey')
    c.text(25, 58, 'Mean contacts per recording hour across eligible detector-nights; species pooled into groups')
    left, right, top, bottom = 90, c.width-40, 105, 415
    totals = frame.groupby('survey_round').mean_rate.sum(min_count=1)
    maximum = max(float(totals.max()) if totals.notna().any() else 0, .01)
    magnitude = 10**math.floor(math.log10(maximum))
    maximum = next(step for step in (1, 2, 2.5, 4, 5, 8, 10)
                   if step >= maximum/magnitude)*magnitude
    for i in range(5):
        y = bottom-(bottom-top)*i/4
        c.line(left, y, right, y, '#e0e6e9')
        c.text(15, y-8, f'{maximum*i/4:.3g}')
    step = (right-left)/len(surveys)
    bar = min(step*.55, 100)
    for i, row in enumerate(surveys.itertuples()):
        x = left+step*(i+.5)-bar/2
        base = bottom
        if row.detector_nights_analysed:
            for group in groups:
                value = float(frame.loc[frame.survey_round.eq(row.survey_round) & frame.activity_group.eq(group)].iloc[0].mean_rate)
                h = value/maximum*(bottom-top)
                if h > 0:
                    c.rect(x, base-h, bar, h, colours[group])
                base -= h
            if not groups:
                c.text(x, bottom-24, '0')
        else:
            c.text(x-10, bottom-24, 'Not analysed', size=12)
        c.text(x+bar/2, bottom+15, row.survey_round, size=14, centre=True)
        c.text(x+bar/2, bottom+37, f'{row.detector_nights_analysed} detector-nights', size=12, centre=True)
        c.text(x+bar/2, bottom+55, f'{row.locations_analysed} locations', size=12, centre=True)
    for j, name in enumerate(groups):
        c.rect(90, 510+j*22, 14, 14, colours[name])
        c.text(114, 508+j*22, name, size=13)
    if not groups:
        c.text(90, 510, 'No contacts recorded on eligible detector-nights.', size=13)
    key_y = 535+legend_height
    for i, row in enumerate(surveys.itertuples()):
        c.text(90, key_y+i*22, f'{row.survey_round}: {row.first_evening:%d %b %Y} - {row.last_evening:%d %b %Y} (evening dates)', size=12)
    c.text(25, c.height-24, 'Intended hours and complete data assumed. Equal weight per eligible detector-night. Sampled periods only.', size=12)
    return c.output()


def satellite_map(locations):
    points, bounds = map_geometry(locations)
    background = fetch_background(bounds)
    c = Canvas(1000, 760, 'Static monitoring locations')
    c.text(25, 58, 'Satellite imagery with supplied detector locations | 2024 mosaic, approximately 10 m detail')
    c.image(background, 40, 100)
    xmin, ymin, xmax, ymax = bounds
    occupied = []
    for name, label, x, y in points:
        px = 40 + (x-xmin)/(xmax-xmin)*920
        py = 100 + (ymax-y)/(ymax-ymin)*500
        text = str(label).strip() or str(name)
        font = ImageFont.truetype(str(FONT_PATH), 14)
        # Wrap long setup labels rather than clipping them at the map edge.
        lines, current = [], ''
        for word in text.split():
            trial = (current + ' ' + word).strip()
            if current and c.draw.textlength(trial, font=font) > 240:
                lines.append(current)
                current = word
            else:
                current = trial
        lines.append(current)
        tw = max(c.draw.textlength(line, font=font) for line in lines) + 12
        th = 20 * len(lines) + 8
        lx = max(42, min(px+14, 958-tw))
        ly = max(102, min(py-24, 598-th))
        for _ in range(len(points)+1):
            if not any(lx < r and lx+tw > l and ly < b and ly+th > t
                       for l, t, r, b in occupied):
                break
            ly += th+4
            if ly+th > 598:
                ly = 102
                lx = max(42, lx-tw-12)
        occupied.append((lx, ly, lx+tw, ly+th))
        c.line(px, py, lx+tw/2, ly+th/2, '#ffffff', 2)
        c.dot(px, py, '#ffffff', 9)
        c.dot(px, py, COLOURS[1], 6)
        c.rect(lx, ly, tw, th, '#ffffff')
        for i, line in enumerate(lines):
            c.text(lx+6, ly+4+i*20, line, size=14)
    c.text(930, 610, 'N', size=16)
    c.line(937, 660, 937, 637, '#24343c', 3)
    c.line(937, 637, 930, 648, '#24343c', 3)
    c.line(937, 637, 944, 648, '#24343c', 3)
    ground_per_pixel = (xmax-xmin)/920 * math.cos(math.radians(float(locations.latitude.mean())))
    target = ground_per_pixel*150
    power = 10**math.floor(math.log10(target))
    metres = max(v*power for v in (0.1, 0.2, 0.5, 1, 2, 5) if v*power <= target)
    c.line(40, 622, 40+metres/ground_per_pixel, 622, '#24343c', 3)
    c.text(40, 630, f'{metres:g} m (approx.)', size=13)
    c.text(25, 670, ATTRIBUTION, size=12)
    c.text(25, 691, 'Contains modified Copernicus Sentinel data 2024 | CC BY-NC-SA 4.0', size=12)
    c.text(25, 712, 'https://creativecommons.org/licenses/by-nc-sa/4.0/ | Detector overlay added; map shared under this licence.', size=11)
    c.text(25, 735, 'Detector positions only; no site boundary. Activity between locations is not inferred.', size=12)
    return c.output()


def location_map(locations, imagery=False):
    if imagery:
        try:
            return satellite_map(locations)
        except (OSError, ValueError):
            # Network/decoding failures must not prevent results or Word downloads.
            return plain_location_map(locations, unavailable=True)
    return plain_location_map(locations)


def plain_location_map(locations, unavailable=False):
    c = Canvas(1000, 720, 'Static monitoring locations')
    c.text(25, 58, 'Satellite imagery unavailable; showing supplied detector locations.' if unavailable else 'Local coordinate map from supplied WGS84 locations; no basemap or site boundary')
    lat0, lon0 = locations.latitude.mean(), locations.longitude.mean()
    points = [(row.detector_id, row.label, (row.longitude-lon0)*111320*math.cos(math.radians(lat0)), (row.latitude-lat0)*111320) for row in locations.itertuples()]
    xs, ys = [p[2] for p in points], [p[3] for p in points]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    scale = min(650/max(xmax-xmin, 100), 420/max(ymax-ymin, 100))
    for name, label, x, y in points:
        px, py = 430+(x-(xmin+xmax)/2)*scale, 360-(y-(ymin+ymax)/2)*scale
        c.dot(px, py, COLOURS[0], 7)
        c.text(px+12, py-20, name)
        c.text(px+12, py+2, label, size=12)
    c.line(900, 180, 900, 110, '#24343c', 3)
    c.line(900, 110, 891, 125, '#24343c', 3)
    c.line(900, 110, 909, 125, '#24343c', 3)
    c.text(893, 85, 'N')
    metres = 100/scale
    c.line(70, 620, 170, 620, '#24343c', 3)
    c.text(70, 635, f'{metres:.0f} m (approx.)')
    c.text(25, 685, 'Points show detector positions only. Activity between locations is not inferred.', size=13)
    return c.output()


def map_caption(formats):
    if b'<image ' in formats['svg']:
        return MAP_NOTE
    prefix = 'Satellite imagery unavailable. ' if b'Satellite imagery unavailable' in formats['svg'] else ''
    return prefix + 'Approximate local coordinate map without a basemap or site boundary. Activity between detectors is not inferred.'


def reporting_figures(tables, imagery=False):
    figures = {'detector_locations': location_map(tables['locations'], imagery=imagery)}
    figures['survey_activity_stacked'] = seasonal_chart(tables['site_activity'])
    if tables['nightly_species'].empty:
        return figures
    figures['total_contacts'] = columns(tables['total_contacts'], 'species', 'contacts', 'Total bat contacts by species / group', 'Contacts (recording-species pairs)')
    nightly = tables['nightly_species']
    pip = nightly.species.str.contains('pipistrel', case=False)
    for name, subset in [('pipistrelles', nightly.loc[pip]), ('other_species', nightly.loc[~pip])]:
        if not subset.empty:
            figures[f'nightly_activity_{name}'] = boxplots(subset, 'Nightly bat activity | '+name.replace('_', ' '))
    # Keep the single survey comparison after the detailed species charts.
    figures['survey_activity_stacked'] = figures.pop('survey_activity_stacked')
    return figures
