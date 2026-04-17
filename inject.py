"""
inject.py
Reads Timesheet.csv, processes it into the same JSON structure
the dashboard expects, and replaces the EMBEDDED constant in index.html.
No external dependencies — stdlib only.
"""

import csv
import json
import re
import sys
from datetime import datetime
from collections import defaultdict

CSV_PATH  = 'Timesheet.csv'
HTML_PATH = 'index.html'

def parse_dt(s):
    if not s:
        return None
    s = s.strip().strip('"')
    formats = [
        '%m/%d/%Y %I:%M %p',
        '%m/%d/%Y %I:%M%p',
        '%m/%d/%Y %H:%M',
        '%m/%d/%Y %H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%Y/%m/%d %H:%M',
        '%d/%m/%Y %H:%M',
        '%m-%d-%Y %H:%M',
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    print(f'  WARNING: Could not parse date: "{s}"', file=sys.stderr)
    return None

def fmt_date(d):  return d.strftime('%Y-%m-%d') if d else ''
def fmt_month(d): return d.strftime('%Y-%m') if d else ''
def fmt_time(d):  return d.strftime('%H:%M') if d else ''
def get_dow(d):   return d.strftime('%A') if d else ''

print(f'Reading {CSV_PATH}...')

MAP = {
    'name':      ['name'],
    'task':      ['task'],
    'category':  ['category'],
    'challenge': ['level of challenge', 'challenge'],
    'start':     ['start'],
    'end':       ['end'],
}

records = []
skipped = 0

try:
    with open(CSV_PATH, newline='', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        raw_headers = next(reader)
        headers = [h.strip().lower().strip('"') for h in raw_headers]
        print(f'Headers: {headers}')

        idx = {}
        for key, variants in MAP.items():
            for i, h in enumerate(headers):
                if any(v in h for v in variants):
                    idx[key] = i
                    break
        print(f'Column map: {idx}')

        missing = [k for k in ['name','task','start'] if k not in idx]
        if missing:
            print(f'ERROR: Required columns missing: {missing}', file=sys.stderr)
            sys.exit(1)

        for row_num, row in enumerate(reader, start=2):
            def col(k):
                i = idx.get(k)
                return row[i].strip().strip('"') if i is not None and i < len(row) else ''

            name = col('name')
            if not name:
                skipped += 1
                continue

            start_raw = col('start')
            if row_num <= 4 and start_raw:
                print(f'Date sample row {row_num}: "{start_raw}"')

            start = parse_dt(start_raw)
            end   = parse_dt(col('end'))
            if not start:
                skipped += 1
                continue

            dur = round((end - start).total_seconds() / 3600, 2) if end and end > start else None

            cat_raw = col('category')
            cats = re.findall(r'"([^"]+)"', cat_raw)
            if not cats:
                cats = [c.strip() for c in cat_raw.strip('[]"\' ').split(',') if c.strip()]
            cat = ', '.join(c for c in cats if c)

            records.append({'name': name, 'task': col('task')[:200], 'category': cat,
                'challenge': col('challenge'), 'start': start, 'end': end,
                'date': fmt_date(start), 'month': fmt_month(start),
                'dow': get_dow(start), 'dur': dur})

except FileNotFoundError:
    print(f'ERROR: {CSV_PATH} not found', file=sys.stderr); sys.exit(1)
except Exception as e:
    import traceback
    print(f'ERROR reading CSV: {e}', file=sys.stderr)
    traceback.print_exc(); sys.exit(1)

print(f'Parsed {len(records)} records, skipped {skipped}')
if not records:
    print('ERROR: 0 records parsed', file=sys.stderr); sys.exit(1)

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
                'date': date, 'dow': tasks[0]['dow'], 'total_h': total,
                'first_in': fmt_time(min(starts)) if starts else None,
                'last_out': fmt_time(max(ends)) if ends else None,
                'task_count': len(tasks),
                'tasks': [{'t': t['task'][:100], 'h': t['dur'],
                           'cat': t['category'], 'ch': t['challenge']} for t in tasks],
            })

task_totals = defaultdict(lambda: {'h':0,'count':0,'people':set(),'cats':set(),'months':set()})
for r in records:
    if not (r['dur'] and r['dur'] > 0): continue
    k = r['task'][:80]
    task_totals[k]['h'] += r['dur']; task_totals[k]['count'] += 1
    task_totals[k]['people'].add(r['name'].split()[0])
    task_totals[k]['cats'].add((r['category'].split(',')[0] or '').strip())
    task_totals[k]['months'].add(r['month'])

top_tasks = [{'task':t,'h':round(d['h'],2),'count':d['count'],'people':list(d['people']),
              'cats':list(d['cats'])[:2],'months':sorted(d['months'])}
             for t,d in sorted(task_totals.items(), key=lambda x:-x[1]['h'])[:40]]

cat_by_pm = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
for r in records:
    if not (r['dur'] and r['dur'] > 0): continue
    cat_by_pm[r['name']][r['month']][(r['category'].split(',')[0] or '').strip()] += r['dur']

chal_dist = defaultdict(lambda: defaultdict(float))
for r in records:
    if r['dur'] and r['dur'] > 0 and r['challenge']:
        chal_dist[r['name'].split()[0]][r['challenge']] += r['dur']

late_night = defaultdict(int)
for r in records:
    if r['start'] and r['start'].hour >= 22:
        late_night[r['name'].split()[0]] += 1

employees = list(per_person.keys())
all_months = sorted({m for emp in per_person for m in per_person[emp]})
print(f'Employees: {employees}')
print(f'Months: {all_months}')

embedded = {
    'perPerson': per_person, 'topTasks': top_tasks,
    'catByPM': {e:{m:dict(c) for m,c in ms.items()} for e,ms in cat_by_pm.items()},
    'chalDist': {fn:dict(cd) for fn,cd in chal_dist.items()},
    'lateNight': dict(late_night), 'employees': employees, 'months': all_months,
    'totalRecords': len(records), 'fetchedAt': datetime.utcnow().isoformat(),
}

json_str = json.dumps(embedded, default=str, separators=(',',':'))
print(f'JSON size: {len(json_str):,} chars')

try:
    with open(HTML_PATH, 'r', encoding='utf-8') as f:
        html = f.read()
except FileNotFoundError:
    print(f'ERROR: {HTML_PATH} not found', file=sys.stderr); sys.exit(1)

if 'const EMBEDDED' not in html:
    print('ERROR: "const EMBEDDED" not found in index.html', file=sys.stderr); sys.exit(1)

replacement = 'const EMBEDDED = ' + json_str + ';'
new_html = re.sub(r'const EMBEDDED\s*=\s*\{.*?\};',
                  lambda m: replacement, html, count=1, flags=re.DOTALL)

if new_html == html:
    print('WARNING: No change made — regex may not have matched', file=sys.stderr)
else:
    with open(HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(new_html)
    print(f'Done. Injected {len(records)} records ({", ".join(all_months)}) into {HTML_PATH}.')
