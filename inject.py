"""
inject.py
Reads Timesheet.csv, processes it into the same JSON structure
the dashboard expects, and replaces the EMBEDDED constant in index.html.
"""

import csv
import json
import re
from datetime import datetime
from collections import defaultdict

CSV_PATH  = 'Timesheet.csv'
HTML_PATH = 'index.html'

# ── helpers ───────────────────────────────────────────────────────────────

def parse_dt(s):
    if not s:
        return None
    s = s.strip()
    for fmt in ('%m/%d/%Y %I:%M %p', '%m/%d/%Y %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None

def fmt_date(d):
    return d.strftime('%Y-%m-%d') if d else ''

def fmt_month(d):
    return d.strftime('%Y-%m') if d else ''

def fmt_time(d):
    return d.strftime('%H:%M') if d else ''

def get_dow(d):
    return d.strftime('%A') if d else ''

def is_we(dow):
    return dow in ('Saturday', 'Sunday')

def month_label(m):
    try:
        return datetime.strptime(m, '%Y-%m').strftime('%B %Y')
    except Exception:
        return m

# ── read CSV ──────────────────────────────────────────────────────────────

records = []
MAP = {
    'name':      ['name'],
    'task':      ['task'],
    'category':  ['category'],
    'challenge': ['level of challenge', 'challenge'],
    'start':     ['start'],
    'end':       ['end'],
}

with open(CSV_PATH, newline='', encoding='utf-8-sig') as f:
    reader = csv.reader(f)
    headers = [h.strip().lower() for h in next(reader)]
    idx = {}
    for key, variants in MAP.items():
        for i, h in enumerate(headers):
            if any(v in h for v in variants):
                idx[key] = i
                break

    for row in reader:
        def col(k):
            i = idx.get(k)
            return row[i].strip() if i is not None and i < len(row) else ''

        name = col('name')
        if not name:
            continue
        start = parse_dt(col('start'))
        end   = parse_dt(col('end'))
        if not start:
            continue
        dur = round((end - start).total_seconds() / 3600, 2) if end and end > start else None

        # categories can be JSON-array-like: ["Cat1","Cat2"]
        cat_raw = col('category')
        cats = re.findall(r'"([^"]+)"', cat_raw)
        if not cats:
            cats = [cat_raw.strip('[]" ')]
        cat = ', '.join(c for c in cats if c)

        records.append({
            'name':      name,
            'task':      col('task')[:200],
            'category':  cat,
            'challenge': col('challenge'),
            'start':     start,
            'end':       end,
            'date':      fmt_date(start),
            'month':     fmt_month(start),
            'dow':       get_dow(start),
            'dur':       dur,
        })

# ── aggregate per-person / per-month / per-day ────────────────────────────

by_pmd = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
for r in records:
    by_pmd[r['name']][r['month']][r['date']].append(r)

per_person = {}
for emp, months in by_pmd.items():
    per_person[emp] = {}
    for mo, days in months.items():
        per_person[emp][mo] = []
        for date in sorted(days):
            tasks = days[date]
            valid = [t for t in tasks if t['dur'] and t['dur'] > 0]
            total = round(sum(t['dur'] for t in valid), 2)
            starts = [t['start'] for t in tasks if t['start']]
            ends   = [t['end']   for t in tasks if t['end']]
            per_person[emp][mo].append({
                'date':       date,
                'dow':        tasks[0]['dow'],
                'total_h':    total,
                'first_in':   fmt_time(min(starts)) if starts else None,
                'last_out':   fmt_time(max(ends))   if ends   else None,
                'task_count': len(tasks),
                'tasks': [{
                    't':   t['task'][:100],
                    'h':   t['dur'],
                    'cat': t['category'],
                    'ch':  t['challenge'],
                } for t in tasks],
            })

# ── task totals ───────────────────────────────────────────────────────────

task_totals = defaultdict(lambda: {'h': 0, 'count': 0, 'people': set(), 'cats': set(), 'months': set()})
for r in records:
    if not (r['dur'] and r['dur'] > 0):
        continue
    k = r['task'][:80]
    task_totals[k]['h']      += r['dur']
    task_totals[k]['count']  += 1
    task_totals[k]['people'].add(r['name'].split()[0])
    task_totals[k]['cats'].add((r['category'].split(',')[0] or '').strip())
    task_totals[k]['months'].add(r['month'])

top_tasks = sorted(task_totals.items(), key=lambda x: -x[1]['h'])[:40]
top_tasks = [{
    'task':   t,
    'h':      round(d['h'], 2),
    'count':  d['count'],
    'people': list(d['people']),
    'cats':   list(d['cats'])[:2],
    'months': sorted(d['months']),
} for t, d in top_tasks]

# ── category by person/month ──────────────────────────────────────────────

cat_by_pm = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
for r in records:
    if not (r['dur'] and r['dur'] > 0):
        continue
    c = (r['category'].split(',')[0] or '').strip()
    cat_by_pm[r['name']][r['month']][c] += r['dur']

# ── challenge distribution ────────────────────────────────────────────────

chal_dist = defaultdict(lambda: defaultdict(float))
for r in records:
    if not (r['dur'] and r['dur'] > 0 and r['challenge']):
        continue
    fn = r['name'].split()[0]
    chal_dist[fn][r['challenge']] += r['dur']

# ── late night ────────────────────────────────────────────────────────────

late_night = defaultdict(int)
for r in records:
    if r['start'] and r['start'].hour >= 22:
        fn = r['name'].split()[0]
        late_night[fn] += 1

# ── assemble final object ─────────────────────────────────────────────────

employees = list(per_person.keys())
all_months = sorted({m for emp in per_person for m in per_person[emp]})

embedded = {
    'perPerson':  per_person,
    'topTasks':   top_tasks,
    'catByPM':    {e: {m: dict(cats) for m, cats in months.items()} for e, months in cat_by_pm.items()},
    'chalDist':   {fn: dict(cd) for fn, cd in chal_dist.items()},
    'lateNight':  dict(late_night),
    'employees':  employees,
    'months':     all_months,
    'totalRecords': len(records),
    'fetchedAt':  datetime.utcnow().isoformat(),
}

json_str = json.dumps(embedded, default=str, separators=(',', ':'))

# ── inject into HTML ──────────────────────────────────────────────────────

with open(HTML_PATH, 'r', encoding='utf-8') as f:
    html = f.read()

# Replace everything between "const EMBEDDED = " and the first ";\n" after it
new_html = re.sub(
    r'const EMBEDDED\s*=\s*\{.*?\};',
    'const EMBEDDED = ' + json_str + ';',
    html,
    count=1,
    flags=re.DOTALL,
)

if new_html == html:
    print('WARNING: EMBEDDED constant not found in index.html — nothing replaced.')
else:
    with open(HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(new_html)
    print(f'Done. Injected {len(records)} records into index.html.')
