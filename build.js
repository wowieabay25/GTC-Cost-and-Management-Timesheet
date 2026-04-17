const fs   = require('fs');
const path = require('path');

// ── CONFIG ───────────────────────────────────────────────────────────────────
const CSV_FILE    = 'Timesheet.csv';
const INPUT_HTML  = 'index.html';
const OUTPUT_HTML = 'https://wowieabay25.github.io/GTC-Cost-and-Management-Timesheet/';
// ─────────────────────────────────────────────────────────────────────────────

console.log('📂 Reading CSV: ' + CSV_FILE);
const csvText = fs.readFileSync(path.join(__dirname, CSV_FILE), 'utf8');

console.log('⚙️  Processing data...');
const data = processCSV(csvText);

console.log('📄 Reading HTML template: ' + INPUT_HTML);
let html = fs.readFileSync(path.join(__dirname, INPUT_HTML), 'utf8');

// ── 1. Replace the EMBEDDED data blob with fresh processed data ───────────────
const newBlob = 'const EMBEDDED = ' + JSON.stringify(data) + ';';
html = html.replace(/const EMBEDDED = \{[\s\S]*?\};/, newBlob);

// ── 2. Remove CSV_URL and CACHE_KEY — no longer needed ───────────────────────
html = html.replace(/const CSV_URL = '.*?';\n/, '');
html = html.replace(/const CACHE_KEY = '.*?';\n/, '');

// ── 3. Replace the full init block with an embedded-only version ──────────────
const initRegex = /window\.addEventListener\('DOMContentLoaded'[\s\S]*?^}\);/m;
const newInit = `window.addEventListener('DOMContentLoaded', () => {
  D = EMBEDDED;
  setStatus('Data as of · ' + fmtStatusDate(D.fetchedAt));
  buildUI();
  document.getElementById('loading-overlay').style.display = 'none';
});`;
html = html.replace(initRegex, newInit);

// ── 4. Remove loadCache and saveCache functions — no longer needed ────────────
html = html.replace(/function loadCache\(\)[\s\S]*?^}\n/m, '');
html = html.replace(/function saveCache\([\s\S]*?^}\n/m, '');

// ── 5. Update footer date range based on actual data months ──────────────────
const MONTH_NAMES = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
function fmtFooterMonth(ym) {
  if (!ym) return { name: '', year: '' };
  const parts = ym.split('-');
  return { name: MONTH_NAMES[parseInt(parts[1]) - 1], year: parts[0] };
}
const months     = data.months || [];
const firstMonth = months[0] || '';
const lastMonth  = months[months.length - 1] || '';
const first = fmtFooterMonth(firstMonth);
const last  = fmtFooterMonth(lastMonth);
let footerRange = '';
if (firstMonth === lastMonth) {
  footerRange = first.name + ' ' + first.year;
} else if (first.year === last.year) {
  footerRange = first.name + '\u2013' + last.name + ' ' + last.year;
} else {
  footerRange = first.name + ' ' + first.year + '\u2013' + last.name + ' ' + last.year;
}
html = html.replace(
  /TIMESHEET VALIDATOR \u00B7 GTC EXPORT TUNA \u00B7 CENTURY PACIFIC FOOD INC \u00B7 .+?(?=<\/div>)/,
  'TIMESHEET VALIDATOR \u00B7 GTC EXPORT TUNA \u00B7 CENTURY PACIFIC FOOD INC \u00B7 ' + footerRange
);

// ── Write output ──────────────────────────────────────────────────────────────
fs.writeFileSync(path.join(__dirname, OUTPUT_HTML), html, 'utf8');

console.log('');
console.log('\u2705 Build complete \u2192 ' + OUTPUT_HTML);
console.log('   Total records : ' + data.totalRecords);
console.log('   Employees     : ' + data.employees.join(', '));
console.log('   Months        : ' + data.months.join(', '));
console.log('   Built at      : ' + data.fetchedAt);
console.log('');
console.log('\uD83D\uDCE4 Share dashboard.html \u2014 CSV source is never exposed.');


// ── CSV PROCESSING ────────────────────────────────────────────────────────────
function processCSV(csvText) {
  const lines   = csvText.trim().split('\n');
  const headers = parseCSVRow(lines[0]).map(h => h.trim().replace(/^"|"$/g, ''));
  const idx     = {};
  const MAP     = {
    name      : ['name'],
    task      : ['task'],
    category  : ['category'],
    challenge : ['level of challenge', 'challenge'],
    start     : ['start'],
    end       : ['end']
  };
  headers.forEach((h, i) => {
    const hl = h.toLowerCase();
    Object.entries(MAP).forEach(([k, v]) => {
      if (v.some(x => hl.includes(x))) idx[k] = i;
    });
  });

  const records = [];
  for (let i = 1; i < lines.length; i++) {
    const cols = parseCSVRow(lines[i]);
    const name = (cols[idx.name] || '').trim();
    if (!name) continue;
    const start = parseDateTime((cols[idx.start] || '').trim());
    const end   = parseDateTime((cols[idx.end]   || '').trim());
    if (!start) continue;
    const dur    = (end && end > start) ? (end - start) / 3600000 : null;
    const catRaw = (cols[idx.category] || '').trim();
    const cats   = catRaw.match(/"([^"]+)"/g)
      ? catRaw.match(/"([^"]+)"/g).map(s => s.replace(/"/g, ''))
      : [(catRaw.replace(/[\[\]"]/g, '')).trim()];
    const cat = cats.filter(Boolean).join(', ');
    records.push({
      name,
      task      : (cols[idx.task]      || '').trim(),
      category  : cat,
      challenge : (cols[idx.challenge] || '').trim(),
      start, end,
      date  : fmtDate(start),
      month : fmtMonth(start),
      dow   : getDOW(start),
      dur   : dur !== null ? Math.round(dur * 100) / 100 : null
    });
  }

  const byPMD = {};
  records.forEach(r => {
    if (!byPMD[r.name])                  byPMD[r.name]              = {};
    if (!byPMD[r.name][r.month])         byPMD[r.name][r.month]     = {};
    if (!byPMD[r.name][r.month][r.date]) byPMD[r.name][r.month][r.date] = [];
    byPMD[r.name][r.month][r.date].push(r);
  });

  const perPerson = {};
  Object.entries(byPMD).forEach(([emp, months]) => {
    perPerson[emp] = {};
    Object.entries(months).forEach(([mo, days]) => {
      perPerson[emp][mo] = Object.entries(days).sort().map(([date, tasks]) => {
        const valid  = tasks.filter(t => t.dur && t.dur > 0);
        const total  = Math.round(valid.reduce((s, t) => s + t.dur, 0) * 100) / 100;
        const starts = tasks.map(t => t.start).filter(Boolean);
        const ends   = tasks.map(t => t.end).filter(Boolean);
        return {
          date,
          dow        : tasks[0].dow,
          total_h    : total,
          first_in   : starts.length ? fmtTime(new Date(Math.min(...starts))) : null,
          last_out   : ends.length   ? fmtTime(new Date(Math.max(...ends)))   : null,
          task_count : tasks.length,
          tasks      : tasks.map(t => ({
            t   : t.task.substring(0, 100),
            h   : t.dur,
            cat : t.category,
            ch  : t.challenge
          }))
        };
      });
    });
  });

  const taskTotals = {};
  records.filter(r => r.dur && r.dur > 0).forEach(r => {
    const k = r.task.substring(0, 80);
    if (!taskTotals[k]) taskTotals[k] = { h: 0, count: 0, people: new Set(), cats: new Set(), months: new Set() };
    taskTotals[k].h += r.dur;
    taskTotals[k].count++;
    taskTotals[k].people.add(r.name.split(' ')[0]);
    taskTotals[k].cats.add((r.category.split(',')[0] || '').trim());
    taskTotals[k].months.add(r.month);
  });
  const topTasks = Object.entries(taskTotals)
    .sort((a, b) => b[1].h - a[1].h).slice(0, 40)
    .map(([t, d]) => ({
      task   : t,
      h      : Math.round(d.h * 100) / 100,
      count  : d.count,
      people : [...d.people],
      cats   : [...d.cats].slice(0, 2),
      months : [...d.months].sort()
    }));

  const catByPM = {};
  records.filter(r => r.dur && r.dur > 0).forEach(r => {
    if (!catByPM[r.name])          catByPM[r.name]          = {};
    if (!catByPM[r.name][r.month]) catByPM[r.name][r.month] = {};
    const c = (r.category.split(',')[0] || '').trim();
    catByPM[r.name][r.month][c] = (catByPM[r.name][r.month][c] || 0) + r.dur;
  });

  const chalDist = {};
  records.filter(r => r.dur && r.dur > 0 && r.challenge).forEach(r => {
    const fn = r.name.split(' ')[0];
    if (!chalDist[fn]) chalDist[fn] = {};
    chalDist[fn][r.challenge] = (chalDist[fn][r.challenge] || 0) + r.dur;
  });

  const lateNight = {};
  records.forEach(r => {
    if (r.start && new Date(r.start).getHours() >= 22) {
      const fn = r.name.split(' ')[0];
      lateNight[fn] = (lateNight[fn] || 0) + 1;
    }
  });

  return {
    perPerson,
    topTasks,
    catByPM,
    chalDist,
    lateNight,
    employees    : Object.keys(perPerson),
    months       : [...new Set(records.map(r => r.month))].sort(),
    totalRecords : records.length,
    fetchedAt    : new Date().toISOString()
  };
}

// ── UTILS ─────────────────────────────────────────────────────────────────────
function parseCSVRow(line) {
  const r = []; let c = '', q = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (q && line[i + 1] === '"') { c += '"'; i++; } else q = !q;
    } else if (ch === ',' && !q) { r.push(c); c = ''; }
    else c += ch;
  }
  r.push(c);
  return r;
}

function parseDateTime(s) {
  if (!s) return null;
  const m = s.match(/(\d+)\/(\d+)\/(\d+)\s+(\d+):(\d+)\s*(AM|PM)?/i);
  if (m) {
    let h = parseInt(m[4]), mn = parseInt(m[5]);
    const pm = (m[6] || '').toUpperCase() === 'PM';
    if (pm && h < 12) h += 12;
    if (!pm && h === 12) h = 0;
    return new Date(parseInt(m[3]), parseInt(m[1]) - 1, parseInt(m[2]), h, mn);
  }
  const d = new Date(s);
  return isNaN(d) ? null : d;
}

function fmtDate(d)  { return d ? d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0') : ''; }
function fmtMonth(d) { return d ? d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') : ''; }
function fmtTime(d)  { return d ? String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0') : ''; }
function getDOW(d)   { return d ? ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'][d.getDay()] : ''; }
