/* Token Analyzer dashboard renderer. Reads window.__CTA_DATA = {agg, report}. */
(function () {
  const D = window.__CTA_DATA || {};
  const A = D.agg, REPORT = D.report || [];
  const $ = (id) => document.getElementById(id);
  if (!A) { document.getElementById('ux').textContent = 'No data yet. Run refresh.py.'; return; }
  const META = A.meta, CAL = (A.limits || {}).calibration || {};
  const LIKELY = ['Duplicate session', 'Polling / loop', 'Context overflow', 'Auto-compaction', 'Cache expired', 'Model switch'];
  const LEAK_INFO = {
    'Duplicate session': 'the same first prompt ran in two sessions within a day; the smaller one counts',
    'Polling / loop': 'an hour with many requests that each wrote almost nothing',
    'Context overflow': 'a chat ran out of context and was reloaded from a summary',
    'Auto-compaction': 'the context filled up and was compacted automatically, then re-sent',
    'Cache expired': 'a session resumed after the prompt cache expired, so the whole context was re-sent at the cache-write price',
    'Model switch': 'the model changed mid-session, which re-sends the whole context',
    'Noisy tool output': 'very long tool output that stayed in the context for later turns',
    'Model overkill': 'a top-tier model used for light steps like reading, searching or short replies',
    'Context bloat': 'context per request above your target, priced at the cache-read rate',
  };
  const S = { lvl: 'day', key: null, unit: 'w', privacy: !!META.privacy_mode };
  const C = (v) => new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(v || 0);
  const P = d3.format('.0%');
  const N = d3.format(',');
  const usdPerW = META.reference_input_price / 1e6;
  const U = (w) => S.unit === 'usd' ? '$' + (w * usdPerW < 100 ? (w * usdPerW).toFixed(2) : N(Math.round(w * usdPerW)))
    : S.unit === 'pct' && CAL.weighted_per_pct_5h ? (w / CAL.weighted_per_pct_5h).toFixed(w / CAL.weighted_per_pct_5h < 10 ? 1 : 0) + '%' : C(w);
  const unitName = () => S.unit === 'usd' ? 'API-equivalent dollars' : S.unit === 'pct' && CAL.weighted_per_pct_5h ? 'of a 5-hour limit (estimated)' : 'weighted tokens';
  const pd = (s) => new Date(s + 'T00:00:00');
  const fmtDay = (k) => d3.timeFormat('%A, %b %-d')(pd(k));
  const fmtShort = (k) => d3.timeFormat('%a %b %-d')(pd(k));
  const fmtWeek = (k) => { const a = pd(k), b = new Date(a.getTime() + 6 * 864e5); return d3.timeFormat('%b %-d')(a) + ' – ' + d3.timeFormat('%b %-d')(b); };
  const fmtMonth = (k) => d3.timeFormat('%B %Y')(pd(k + '-01'));
  const periodName = (lvl, k) => lvl === 'day' ? fmtDay(k) : lvl === 'week' ? 'Week of ' + fmtWeek(k) : lvl === 'month' ? fmtMonth(k) : lvl === 'year' ? k : 'All time · since ' + d3.timeFormat('%b %-d, %Y')(pd(META.first_day));
  const pickName = (lvl, k) => lvl === 'day' ? fmtShort(k) : lvl === 'week' ? fmtWeek(k) : lvl === 'month' ? d3.timeFormat('%b %Y')(pd(k + '-01')) : k;
  const prevName = { day: 'last active day', week: 'week before', month: 'last active month', year: 'last year' };
  const palette = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)', 'var(--series-5)', 'var(--series-6)', 'var(--series-7)', 'var(--series-8)'];
  const hh = (n) => String(((n % 24) + 24) % 24).padStart(2, '0') + ':00';

  // names under privacy mode
  const alias = {};
  const nameOf = (kind, v) => {
    if (!S.privacy) return v;
    const k = kind + '|' + v;
    if (!alias[k]) alias[k] = (kind === 'project' ? 'Project ' : 'Session ') + String.fromCharCode(65 + (Object.keys(alias).filter((x) => x.startsWith(kind)).length % 26));
    return alias[k];
  };

  // ---------- small helpers ----------
  const tipFor = (box) => { let t = box.querySelector('.ux-tip'); if (!t) { t = document.createElement('div'); t.className = 'ux-tip'; box.appendChild(t); } return t; };
  const tipShow = (box, t, ev, lines) => {
    t.replaceChildren(...lines.map((l, i) => { const d = document.createElement('div'); if (i === 0) d.className = 'd'; d.textContent = l; return d; }));
    t.style.display = 'block';
    const r = box.getBoundingClientRect(); let x = ev.clientX - r.left + 12;
    if (x + t.offsetWidth > box.clientWidth) x = Math.max(0, ev.clientX - r.left - t.offsetWidth - 12);
    t.style.left = x + 'px'; t.style.top = Math.max(0, ev.clientY - r.top - 10 - t.offsetHeight) + 'px';
  };
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const copyText = (txt, btn) => {
    const done = () => { if (btn) { const o = btn.textContent; btn.textContent = 'Copied'; setTimeout(() => { btn.textContent = o; }, 1400); } };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(txt).then(done, () => fallback());
    else fallback();
    function fallback() { const ta = el('textarea'); ta.value = txt; ta.style.position = 'fixed'; ta.style.opacity = '0'; document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); done(); } catch (e) { /* ignore */ } ta.remove(); }
  };
  const chip = (id, v, label, lowerIsGood = true) => {
    const c = $(id);
    if (v == null || !isFinite(v)) { c.textContent = 'No earlier ' + label.replace(/^vs /, ''); c.className = 'ux-chip'; return; }
    c.textContent = (v >= 0 ? '↑ ' : '↓ ') + P(Math.abs(v)) + (v >= 0 ? ' more ' : ' less ') + label;
    c.className = 'ux-chip ' + ((v <= 0) === lowerIsGood ? 'good' : 'bad');
  };
  const ring = (box, share, label) => {
    box.replaceChildren();
    const Sz = 136, r = 56, w = 10, circ = 2 * Math.PI * r;
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${Sz} ${Sz}`).attr('aria-hidden', 'true');
    svg.append('circle').attr('cx', Sz / 2).attr('cy', Sz / 2).attr('r', r).attr('fill', 'none').attr('stroke', 'var(--color-border-line)').attr('stroke-width', w);
    if (share != null) svg.append('circle').attr('cx', Sz / 2).attr('cy', Sz / 2).attr('r', r).attr('fill', 'none').attr('stroke', 'var(--series-1)').attr('stroke-width', w).attr('stroke-linecap', 'round')
      .attr('stroke-dasharray', `${Math.max(0.001, share) * circ} ${circ}`).attr('transform', `rotate(-90 ${Sz / 2} ${Sz / 2})`);
    svg.append('text').attr('x', Sz / 2).attr('y', Sz / 2 - 2).attr('text-anchor', 'middle').attr('font-family', 'var(--font-anthropic-serif)').attr('font-size', 28).attr('fill', 'var(--color-fg)').text(share == null ? '—' : P(share));
    svg.append('text').attr('x', Sz / 2).attr('y', Sz / 2 + 18).attr('text-anchor', 'middle').attr('font-size', 11).attr('fill', 'var(--color-fg-muted)').text(label);
    box.setAttribute('aria-label', share == null ? 'No efficiency data' : P(share) + ' ' + label);
  };
  const spark = (box, vals, hi) => {
    box.replaceChildren();
    const W = box.clientWidth || 140, H = 34;
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('height', H).attr('viewBox', `0 0 ${W} ${H}`).attr('preserveAspectRatio', 'none').attr('aria-hidden', 'true');
    if (!vals.length) return;
    const x = d3.scaleBand(d3.range(vals.length), [0, W]).padding(0.25);
    const y = d3.scaleLinear([0, d3.max(vals) || 1], [H, 2]);
    svg.selectAll('rect').data(vals).join('rect').attr('x', (v, i) => x(i)).attr('width', x.bandwidth()).attr('y', (v) => y(v)).attr('height', (v) => H - y(v)).attr('rx', Math.min(2, x.bandwidth() / 2))
      .attr('fill', (v, i) => (i === hi ? 'var(--series-1)' : 'var(--cds-chart-muted)'));
  };
  const hbars = (box, rows, opts = {}) => {
    box.replaceChildren();
    rows = rows.filter((r) => r[1] > 0);
    if (!rows.length) { box.appendChild(el('div', 'ux-sub', opts.empty || 'Nothing in this period.')); return; }
    const tot = d3.sum(rows, (r) => r[1]), mx = d3.max(rows, (r) => r[1]);
    rows.forEach((r, i) => {
      const row = el('div', 'ux-bar' + (opts.onClick ? ' click' : ''));
      const n = el('span', 'n', opts.name ? opts.name(r) : r[0]);
      if (opts.badge) { const b = opts.badge(r); if (b) n.appendChild(el('span', 'ux-badge', b)); }
      const t = el('span', 't'); const f = el('span'); f.style.width = Math.max(2, (r[1] / mx) * 100) + '%'; f.style.background = opts.color ? opts.color(r, i) : palette[i % palette.length]; t.appendChild(f);
      const v = el('span', 'v', U(r[1]) + ' · ' + P(r[1] / tot));
      row.append(n, t, v);
      row.title = (opts.title ? opts.title(r) : r[0]) + ': ' + U(r[1]);
      if (opts.onClick) { row.tabIndex = 0; row.setAttribute('role', 'button'); row.addEventListener('click', () => opts.onClick(r)); row.addEventListener('keydown', (e) => { if (e.key === 'Enter') opts.onClick(r); }); }
      box.appendChild(row);
    });
  };
  const axisY = (svg, y, m, fmt) => {
    const g = svg.append('g').attr('font-size', 11).attr('fill', 'var(--color-fg-muted)');
    const ls = y.ticks(3).map((v) => g.append('text').text(fmt(v)).attr('y', y(v)).attr('dy', '.32em'));
    m.l = (d3.max(ls, (s) => s.node().getComputedTextLength()) || 16) + 10;
    ls.forEach((s) => s.attr('x', m.l - 8).attr('text-anchor', 'end'));
    return y.ticks(3);
  };

  // ---------- main stacked chart ----------
  function mainChart(m, lvl, key) {
    const box = $('main-chart'); box.replaceChildren();
    const rows = m.series.map((s) => ({ k: s[0], label: s[1], w: s[2], lo: s[3], hi: s[4], req: s[5], ses: s[6], ctx: s[7] }));
    const W = box.clientWidth || 600, H = 210, mg = { t: 10, r: 4, b: 24, l: 8 };
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img');
    const y = d3.scaleLinear([0, d3.max(rows, (r) => r.w) || 1], [H - mg.b, mg.t]).nice(3);
    const ticks = axisY(svg, y, mg, U);
    const x = d3.scaleBand(rows.map((r) => r.k), [mg.l, W - mg.r]).padding(0.26);
    if (lvl === 'day') {
      const base = pd(key).getTime() + META.day_start_hour * 3600e3;
      const px = (ms) => mg.l + ((ms - base) / 864e5) * (W - mg.l - mg.r);
      A.windows.filter((w) => w[2] === key).forEach((w) => {
        const x0 = Math.max(mg.l, px(w[0] * 1000)), x1 = Math.min(W - mg.r, px(w[1] * 1000));
        svg.append('rect').attr('x', x0).attr('width', Math.max(2, x1 - x0)).attr('y', mg.t).attr('height', H - mg.b - mg.t).attr('rx', 8).attr('fill', 'var(--series-1)').attr('fill-opacity', 0.07);
      });
    }
    svg.append('g').selectAll('line').data(ticks).join('line').attr('x1', mg.l).attr('x2', W - mg.r).attr('y1', (v) => y(v)).attr('y2', (v) => y(v)).attr('stroke', 'var(--cds-chart-grid)');
    const bw = Math.min(28, x.bandwidth()), off = (x.bandwidth() - bw) / 2, rx = Math.min(5, bw / 2), t = tipFor(box);
    const drill = lvl === 'week' || lvl === 'month' ? 'day' : lvl === 'year' || lvl === 'all' ? 'month' : null;
    const g = svg.append('g').selectAll('g').data(rows).join('g').style('cursor', drill ? 'pointer' : null)
      .on('click', (ev, r) => { if (drill && r.req) go(drill, r.k); })
      .on('mousemove', (ev, r) => tipShow(box, t, ev, [lvl === 'day' ? hh(+r.k) + '–' + hh(+r.k).slice(0, 3) + '59' : (lvl === 'year' || lvl === 'all' ? fmtMonth(r.k) : fmtShort(r.k)),
        U(r.w), 'Avoidable ' + U(r.lo) + ' likely, ' + U(r.hi) + ' max', N(r.req) + ' requests']))
      .on('mouseleave', () => { t.style.display = 'none'; });
    const bar = (sel, v, fill, op) => sel.append('rect').attr('x', (r) => x(r.k) + off).attr('width', bw).attr('y', (r) => y(Math.min(v(r), r.w))).attr('height', (r) => Math.max(0, y(0) - y(Math.min(v(r), r.w)))).attr('rx', rx).attr('fill', fill).attr('fill-opacity', op);
    bar(g, (r) => r.w, 'var(--series-1)', 0.28);
    bar(g, (r) => r.hi, 'var(--series-1)', 0.55);
    bar(g, (r) => r.lo, 'var(--series-1)', 1);
    const step = Math.ceil(rows.length / Math.max(1, Math.floor((W - mg.l) / 40)));
    svg.append('g').attr('font-size', 11).attr('fill', 'var(--color-fg-muted)').selectAll('text').data(rows.filter((r, i) => i % step === 0)).join('text')
      .attr('x', (r) => x(r.k) + x.bandwidth() / 2).attr('y', H - 6).attr('text-anchor', 'middle').text((r) => (lvl === 'day' ? (+r.k % 3 === 0 ? hh(+r.k) : '') : r.label));
    svg.append('line').attr('x1', mg.l).attr('x2', W - mg.r).attr('y1', y(0)).attr('y2', y(0)).attr('stroke', 'var(--cds-chart-axis)');
    const peak = rows.reduce((a, b) => (b.w > a.w ? b : a), rows[0]);
    svg.attr('aria-label', `Bar chart of ${unitName()} per ${lvl === 'day' ? 'hour' : lvl === 'year' || lvl === 'all' ? 'month' : 'day'}; highest ${peak ? peak.label + ' at ' + U(peak.w) : 'none'}.`);
    const lg = $('main-legend'); lg.replaceChildren();
    [['Total', 0.28], ['Possibly avoidable', 0.55], ['Likely avoidable', 1]].forEach(([n, o]) => { const s = el('span'); const i = el('i'); i.style.background = 'var(--series-1)'; i.style.opacity = o; s.append(i, n); lg.appendChild(s); });
    if (lvl === 'day') { const s = el('span'); const i = el('i'); i.style.background = 'var(--series-1)'; i.style.opacity = 0.12; s.append(i, '5-hour window'); lg.appendChild(s); }
    $('main-title').textContent = lvl === 'day' ? 'Hour by hour' : lvl === 'week' || lvl === 'month' ? 'Day by day' : 'Month by month';
    $('main-hint').textContent = drill ? 'tap a bar' : '';
    const pills = $('win-pills'); pills.replaceChildren();
    if (lvl === 'day') A.windows.filter((w) => w[2] === key).forEach((w) => {
      const p = el('span', 'ux-pill'); const b = el('b', null, d3.timeFormat('%H:%M')(new Date(w[0] * 1000)) + '–' + d3.timeFormat('%H:%M')(new Date(w[1] * 1000)));
      p.append(b, ' · ' + U(w[3])); p.title = N(w[4]) + ' requests'; pills.appendChild(p);
    });
  }

  function lineChart(box, pts, target, fmtX) {
    box.replaceChildren();
    pts = pts.filter((p) => p.v > 0);
    if (!pts.length) { box.appendChild(el('div', 'ux-sub', 'No requests in this period.')); return; }
    const W = box.clientWidth || 360, H = 160, m = { t: 12, r: 10, b: 24, l: 8 };
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img');
    const y = d3.scaleLinear([0, Math.max(target * 1.15, d3.max(pts, (p) => p.v))], [H - m.b, m.t]).nice(3);
    const ticks = axisY(svg, y, m, C);
    svg.append('g').selectAll('line').data(ticks).join('line').attr('x1', m.l).attr('x2', W - m.r).attr('y1', (v) => y(v)).attr('y2', (v) => y(v)).attr('stroke', 'var(--cds-chart-grid)');
    svg.append('line').attr('x1', m.l).attr('x2', W - m.r).attr('y1', y(target)).attr('y2', y(target)).attr('stroke', 'var(--cds-chart-reference)').attr('stroke-dasharray', '4 4');
    svg.append('text').attr('x', m.l + 4).attr('y', y(target) - 5).attr('text-anchor', 'start').attr('font-size', 11).attr('fill', 'var(--color-fg-muted)').text('target ' + C(target));
    const x = d3.scalePoint(pts.map((p) => p.k), [m.l + 6, W - m.r - 6]).padding(pts.length === 1 ? 0.5 : 0);
    svg.append('path').datum(pts).attr('fill', 'none').attr('stroke', 'var(--series-1)').attr('stroke-width', 2).attr('stroke-linejoin', 'round').attr('stroke-linecap', 'round').attr('d', d3.line().x((p) => x(p.k)).y((p) => y(p.v)));
    const t = tipFor(box);
    svg.append('g').selectAll('circle').data(pts).join('circle').attr('cx', (p) => x(p.k)).attr('cy', (p) => y(p.v)).attr('r', 3.5).attr('fill', 'var(--color-panel)').attr('stroke', 'var(--series-1)').attr('stroke-width', 2)
      .on('mousemove', (ev, p) => tipShow(box, t, ev, [p.name, C(p.v) + ' context per request'])).on('mouseleave', () => { t.style.display = 'none'; });
    const step = Math.ceil(pts.length / Math.max(1, Math.floor(W / 52)));
    svg.append('g').attr('font-size', 11).attr('fill', 'var(--color-fg-muted)').selectAll('text').data(pts.filter((p, i) => i % step === 0)).join('text').attr('x', (p) => x(p.k)).attr('y', H - 6).attr('text-anchor', 'middle').text((p) => fmtX(p));
    const a = pts[0].v, b = pts[pts.length - 1].v;
    svg.attr('aria-label', `Context per request went from ${C(a)} to ${C(b)}; target ${C(target)}.`);
  }

  // ---------- analyzer text for week / month / year / all ----------
  const FIX = { 'Context bloat': 'one task per session, /compact at milestones, /clear between tasks', 'Cache expired': 'retire long sessions with a handoff note instead of resuming them later', 'Model switch': 'pick the model at the start of a session', 'Auto-compaction': 'compact by hand earlier and say what to keep', 'Context overflow': 'split big tasks before the context fills', 'Duplicate session': 'close one session before repeating a request', 'Polling / loop': 'ask for one final report instead of wait-and-check loops', 'Noisy tool output': 'use quiet flags or run noisy commands in a subagent', 'Model overkill': 'use Sonnet or Haiku for routine steps' };
  function analyzer(m, lvl) {
    const lines = [];
    const eff = m.weighted ? 1 - m.avoid_low / m.weighted : null;
    if (eff != null) lines.push([`${P(eff)} efficient: ${U(m.avoid_low)} likely avoidable, up to ${U(m.avoid_high)} counting possible leaks.`]);
    const top = m.leaks[0];
    if (top) lines.push([`Biggest leak: ${top[0].toLowerCase()} (${P(top[1] / d3.sum(m.leaks, (l) => l[1]))} of avoidable). Fix: ${FIX[top[0]] || 'review the flagged sessions'}.`]);
    const act = m.series.filter((s) => s[5] > 0 && s[7] > 0);
    if (act.length > 1) { const a = act[0], b = act[act.length - 1], ch = (b[7] - a[7]) / a[7]; lines.push([`Context per request went from ${C(a[7])} (${a[1]}) to ${C(b[7])} (${b[1]}): ${ch <= 0 ? 'leaner' : 'heavier'} by ${P(Math.abs(ch))}. Target ${C(META.context_target)}.`]); }
    if (m.leak_sessions[0]) lines.push([`Leakiest session: ${nameOf('session', m.leak_sessions[0][1])} (${U(m.leak_sessions[0][2])}).`, null, m.leak_sessions[0][0]]);
    const opus = m.by_model.filter((x) => /opus|fable/.test(x[0]));
    if (opus.length && m.weighted) lines.push([`Top-tier models used ${P(d3.sum(opus, (x) => x[1]) / m.weighted)} of this period's budget.`]);
    return lines;
  }

  function renderReport(m, lvl, key) {
    const top = $('rep-top'), full = $('rep-full'), wrap = $('rep-full-wrap');
    top.replaceChildren(); full.replaceChildren();
    const addTip = (text, copy, sid) => {
      const li = el('li'); li.appendChild(el('span', null, text));
      if (copy) { const b = el('button', 'ux-copy', 'Copy'); b.title = copy; b.addEventListener('click', () => copyText(copy, b)); li.appendChild(b); }
      else if (sid && A.sessions[sid]) { const b = el('button', 'ux-copy', 'Open'); b.addEventListener('click', () => openSession(sid)); li.appendChild(b); }
      else li.appendChild(el('span'));
      top.appendChild(li);
    };
    if (lvl !== 'day') {
      $('rep-title').textContent = 'Analyzer'; $('rep-when').textContent = ''; wrap.hidden = true;
      analyzer(m, lvl).forEach((l) => addTip(l[0], l[1], l[2]));
      return;
    }
    $('rep-title').textContent = "Today's moves"; wrap.hidden = false;
    let rdate = key;
    if (!REPORT.some((x) => x.date === key)) rdate = REPORT.map((x) => x.date).filter((x) => x <= key).sort().pop();
    const items = REPORT.filter((x) => x.date === rdate).sort((a, b) => a.order - b.order);
    $('rep-when').textContent = !items.length ? '' : rdate === key ? 'written ' + (items[0].written || '') : 'from ' + fmtShort(rdate);
    if (!items.length) { addTip('No report yet. One is written each morning for the day before.'); analyzer(m, lvl).forEach((l) => addTip(l[0], l[1], l[2])); return; }
    let sec = null; const groups = [];
    items.forEach((x) => { if (x.kind === 'heading') { sec = { h: x.text, tips: [] }; groups.push(sec); } else if (x.kind === 'tip') { if (!sec) { sec = { h: '', tips: [] }; groups.push(sec); } sec.tips.push(x); } else full.appendChild(el('p', null, x.text)); });
    const act = groups.find((g) => /do/i.test(g.h)) || groups[0];
    (act ? act.tips.slice(0, 3) : []).forEach((x) => addTip(x.text.split('. ')[0].replace(/\.$/, '') + '.', x.copy));
    groups.forEach((g) => { if (g.h) full.appendChild(el('h3', null, g.h)); const ul = el('ul'); g.tips.forEach((x) => ul.appendChild(el('li', null, x.text + (x.copy ? '  →  ' + x.copy : '')))); full.appendChild(ul); });
  }

  // ---------- limits ----------
  function renderLimits(lvl) {
    const L = A.limits || {}, card = $('limits-card'), body = $('lim-body');
    const fc = L.forecast;
    card.hidden = !(lvl === 'day' || lvl === 'week');
    body.replaceChildren();
    if (!fc) {
      $('lim-at').textContent = '';
      body.appendChild(el('p', 'ux-sub', 'Track your real 5-hour and weekly limits here: run /token-analyzer:setup-statusline once. It records the percentages Claude Code already shows, with no tokens used.'));
      return;
    }
    $('lim-at').textContent = 'last reading ' + d3.timeFormat('%a %H:%M')(new Date(fc.at * 1000));
    [['5-hour', fc.five_hour], ['Weekly', fc.seven_day]].forEach(([n, f]) => {
      if (!f) return;
      const row = el('div', 'ux-gauge'); const t = el('span', 't'); const s = el('span');
      s.style.width = Math.min(100, f.pct) + '%'; s.style.background = f.pct >= 90 ? 'var(--color-bad)' : f.pct >= 70 ? 'var(--color-warn)' : 'var(--series-1)'; t.appendChild(s);
      row.append(el('span', null, n), t, el('span', 'v', Math.round(f.pct) + '%')); body.appendChild(row);
      const parts = [];
      if (f.resets_at) parts.push('resets ' + d3.timeFormat('%a %H:%M')(new Date(f.resets_at * 1000)));
      if (f.hits_at) parts.push('at this pace it runs out ' + d3.timeFormat('%a %H:%M')(new Date(f.hits_at * 1000)));
      if (parts.length) body.appendChild(el('div', 'ux-sub', parts.join(' · ')));
    });
    if (CAL.weighted_per_pct_5h) body.appendChild(el('p', 'ux-sub', `About ${C(CAL.weighted_per_pct_5h)} weighted tokens per 1% of your 5-hour limit, from ${CAL.samples} readings. claude.ai use shares these limits but leaves no local logs, so this can run high.`));
  }

  // ---------- rhythm & calendar ----------
  function rhythm() {
    const box = $('rhythm-chart'); box.replaceChildren();
    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    const W = box.clientWidth || 600, lw = 34, cw = (W - lw) / 24, ch = Math.min(22, Math.max(14, cw)), H = 7 * ch + 18;
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img');
    const flat = A.rhythm.flatMap((row, d) => row.map((v, h) => ({ d, h, v })));
    const mx = d3.max(flat, (q) => q.v) || 1, sc = d3.scaleSqrt([0, mx], [0, 1]), t = tipFor(box);
    svg.append('g').selectAll('rect').data(flat).join('rect').attr('x', (q) => lw + q.h * cw + 1.5).attr('y', (q) => q.d * ch + 1.5).attr('width', Math.max(1, cw - 3)).attr('height', ch - 3).attr('rx', 4)
      .attr('fill', 'var(--series-1)').attr('fill-opacity', (q) => (q.v ? 0.1 + 0.9 * sc(q.v) : 0.04))
      .on('mousemove', (ev, q) => tipShow(box, t, ev, [days[q.d] + ' ' + hh(q.h), N(q.v) + ' requests'])).on('mouseleave', () => { t.style.display = 'none'; });
    const g = svg.append('g').attr('font-size', 11).attr('fill', 'var(--color-fg-muted)');
    days.forEach((d, k) => g.append('text').text(d).attr('x', 0).attr('y', k * ch + ch / 2).attr('dy', '.32em'));
    [0, 6, 12, 18].forEach((h) => g.append('text').text(hh(h)).attr('x', lw + h * cw + cw / 2).attr('y', H - 3).attr('text-anchor', 'middle'));
    const busiest = flat.reduce((a, b) => (b.v > a.v ? b : a), flat[0]);
    svg.attr('aria-label', `Requests by weekday and hour; busiest ${days[busiest.d]} ${hh(busiest.h)}.`);
  }
  function calendar() {
    const box = $('cal-chart'); box.replaceChildren();
    const cal = A.calendar; if (!cal.length) return;
    const start = pd(cal[0][0]), off = (start.getDay() + 6) % 7, nW = Math.ceil((cal.length + off) / 7);
    const W = box.clientWidth || 600, lw = 30, cell = Math.max(8, Math.min(22, (W - lw) / nW)), H = 7 * cell + 20;
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${Math.max(W, lw + nW * cell)} ${H}`).attr('role', 'img');
    const mx = d3.max(cal, (c) => c[1]) || 1, sc = d3.scaleSqrt([0, mx], [0, 1]), t = tipFor(box);
    svg.append('g').selectAll('rect').data(cal.map((c, i) => ({ k: c[0], v: c[1], i: i + off }))).join('rect')
      .attr('x', (c) => lw + Math.floor(c.i / 7) * cell + 1).attr('y', (c) => (c.i % 7) * cell + 1).attr('width', cell - 2).attr('height', cell - 2).attr('rx', 3)
      .attr('fill', 'var(--series-1)').attr('fill-opacity', (c) => (c.v ? 0.12 + 0.88 * sc(c.v) : 0.05)).style('cursor', (c) => (c.v ? 'pointer' : null))
      .on('click', (ev, c) => { if (c.v) go('day', c.k); })
      .on('mousemove', (ev, c) => tipShow(box, t, ev, [fmtShort(c.k), U(c.v)])).on('mouseleave', () => { t.style.display = 'none'; });
    const g = svg.append('g').attr('font-size', 10).attr('fill', 'var(--color-fg-muted)');
    ['Mon', '', 'Wed', '', 'Fri', '', ''].forEach((d, k) => g.append('text').text(d).attr('x', 0).attr('y', k * cell + cell / 2).attr('dy', '.32em'));
    let lastM = '';
    cal.forEach((c, i) => { const m = c[0].slice(0, 7); if (m !== lastM && (i + off) % 7 <= 0 + 6) { lastM = m; g.append('text').text(d3.timeFormat('%b')(pd(c[0]))).attr('x', lw + Math.floor((i + off) / 7) * cell).attr('y', H - 4); } });
    svg.attr('aria-label', 'Calendar of daily usage since ' + fmtShort(cal[0][0]) + '.');
  }

  // ---------- session drawer ----------
  let lastFocus = null;
  function openSession(sid) {
    const s = A.sessions[sid]; if (!s) return;
    lastFocus = document.activeElement;
    $('dr-title').textContent = nameOf('session', s.title);
    $('dr-sub').textContent = nameOf('project', s.project) + ' · ' + s.task;
    const chips = $('dr-chips'); chips.replaceChildren();
    [U(s.weighted) + (S.unit === 'w' ? ' weighted' : ''), N(s.requests) + ' requests', s.subagent_requests ? N(s.subagent_requests) + ' by subagents' : null,
      d3.timeFormat('%b %-d %H:%M')(new Date(s.first * 1000)) + ' → ' + d3.timeFormat('%b %-d %H:%M')(new Date(s.last * 1000))].filter(Boolean).forEach((c) => chips.appendChild(el('span', 'ux-chip', c)));
    $('drawer').hidden = false;
    const box = $('dr-chart'); box.replaceChildren();
    const pts = s.points.map((p) => ({ t: p[0] * 1000, v: p[1], m: p[3] }));
    const W = box.clientWidth || 560, H = 220, mg = { t: 12, r: 10, b: 24, l: 8 };
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', 'Context per request over the session');
    const y = d3.scaleLinear([0, Math.max(META.context_target * 1.15, d3.max(pts, (p) => p.v) || 1)], [H - mg.b, mg.t]).nice(3);
    const ticks = axisY(svg, y, mg, C);
    const x = d3.scaleLinear(d3.extent(pts, (p) => p.t), [mg.l + 4, W - mg.r - 4]);
    svg.append('g').selectAll('line').data(ticks).join('line').attr('x1', mg.l).attr('x2', W - mg.r).attr('y1', (v) => y(v)).attr('y2', (v) => y(v)).attr('stroke', 'var(--cds-chart-grid)');
    svg.append('line').attr('x1', mg.l).attr('x2', W - mg.r).attr('y1', y(META.context_target)).attr('y2', y(META.context_target)).attr('stroke', 'var(--cds-chart-reference)').attr('stroke-dasharray', '4 4');
    const kinds = [...new Set(s.marks.map((mk) => mk[1]).filter((k) => !/^Compaction/.test(k)))];
    const col = (k) => palette[(kinds.indexOf(k) + 1) % palette.length];
    s.marks.filter((mk) => /^Compaction/.test(mk[1])).forEach((mk) => svg.append('line').attr('x1', x(mk[0] * 1000)).attr('x2', x(mk[0] * 1000)).attr('y1', mg.t).attr('y2', H - mg.b).attr('stroke', 'var(--color-fg-muted)').attr('stroke-dasharray', '3 3'));
    svg.append('path').datum(pts).attr('fill', 'none').attr('stroke', 'var(--series-1)').attr('stroke-width', 1.6).attr('stroke-linejoin', 'round').attr('d', d3.line().x((p) => x(p.t)).y((p) => y(p.v)));
    const near = (ts) => { let best = pts[0]; pts.forEach((p) => { if (Math.abs(p.t - ts) < Math.abs(best.t - ts)) best = p; }); return best; };
    svg.append('g').selectAll('circle').data(s.marks.filter((mk) => !/^Compaction/.test(mk[1]))).join('circle').attr('cx', (mk) => x(mk[0] * 1000)).attr('cy', (mk) => y(near(mk[0] * 1000).v)).attr('r', 4.5).attr('fill', (mk) => col(mk[1])).attr('stroke', 'var(--color-panel)');
    const span = (d3.max(pts, (p) => p.t) - d3.min(pts, (p) => p.t)) / 864e5;
    const xf = span > 2 ? d3.timeFormat('%b %-d') : d3.timeFormat('%H:%M');
    svg.append('g').attr('font-size', 11).attr('fill', 'var(--color-fg-muted)').selectAll('text').data(x.ticks(Math.max(2, Math.floor(W / 110)))).join('text').attr('x', (v) => x(v)).attr('y', H - 6).attr('text-anchor', 'middle').text((v) => xf(new Date(v)));
    const lg = $('dr-legend'); lg.replaceChildren();
    kinds.forEach((k) => { const sp = el('span'); const i = el('i'); i.style.background = col(k); sp.append(i, k); lg.appendChild(sp); });
    const tb = $('dr-marks'); tb.replaceChildren();
    const grp = d3.rollups(s.marks, (v) => ({ first: d3.min(v, (x) => x[0]), n: v.length, est: d3.sum(v, (x) => x[2] || 0) }), (x) => x[1]).sort((a, b) => a[1].first - b[1].first);
    grp.forEach(([k, g]) => { const tr = el('tr'); tr.append(el('td', null, d3.timeFormat('%b %-d %H:%M')(new Date(g.first * 1000))), el('td', null, k + (g.n > 1 ? ' ×' + g.n : '')), el('td', 'n', g.est ? U(g.est) : '')); tb.appendChild(tr); });
    $('dr-close').focus();
  }
  const closeDrawer = () => { $('drawer').hidden = true; if (lastFocus) lastFocus.focus(); };
  $('dr-close').addEventListener('click', closeDrawer);
  $('drawer').addEventListener('click', (e) => { if (e.target.id === 'drawer') closeDrawer(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('drawer').hidden) closeDrawer(); });

  // ---------- page ----------
  function keysFor(lvl) { return Object.keys(A.levels[lvl]).filter((k) => A.levels[lvl][k].requests > 0).sort(); }
  function go(lvl, key) { S.lvl = lvl; S.key = key || null; try { history.replaceState(null, '', '#' + lvl + (key ? ':' + key : '')); } catch (e) { /* file:// */ } draw(); }
  function draw() {
    const lvl = S.lvl;
    document.querySelectorAll('.ux-seg button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.lvl === lvl)));
    const keys = keysFor(lvl);
    if (!keys.length) return;
    if (!S.key || !A.levels[lvl][S.key]) S.key = keys[keys.length - 1];
    const key = S.key, m = A.levels[lvl][key];
    const pick = $('pick'); pick.hidden = lvl === 'all';
    pick.replaceChildren(...keys.slice().reverse().map((k) => new Option(pickName(lvl, k), k))); pick.value = key;
    $('h-date').textContent = periodName(lvl, key);
    $('h-big').textContent = U(m.weighted);
    $('h-unit').textContent = unitName() + (S.unit !== 'usd' ? ' · ≈ $' + (m.weighted * usdPerW).toFixed(2) + ' at API prices' : '');
    if (lvl === 'all') { const c = $('h-c1'); c.className = 'ux-chip'; c.textContent = m.active_days + ' active days'; } else chip('h-c1', m.change, 'vs ' + prevName[lvl]);
    const c2 = $('h-c2'); c2.className = 'ux-chip'; c2.textContent = 'Avoidable ' + U(m.avoid_low) + '–' + U(m.avoid_high);
    const c3 = $('h-c3'); c3.className = 'ux-chip'; c3.textContent = C(m.total) + ' raw tokens';
    ring($('h-ring'), m.weighted ? 1 - m.avoid_low / m.weighted : null, 'efficient');
    $('t1').textContent = C(m.avg_context); $('t2').textContent = N(m.requests); $('t3').textContent = N(m.sessions); $('t4').textContent = U(m.avoid_low);
    const ser = m.series; const hi = -1;
    spark($('s1'), ser.map((s) => s[7]), hi); spark($('s2'), ser.map((s) => s[5]), hi); spark($('s3'), ser.map((s) => s[6]), hi); spark($('s4'), ser.map((s) => s[3]), hi);
    renderLimits(lvl);
    mainChart(m, lvl, key);
    renderReport(m, lvl, key);
    // trend: weeks for a day, sub-periods otherwise
    if (lvl === 'day') {
      const wk = Object.keys(A.levels.week).sort().slice(-12).map((k) => ({ k, v: A.levels.week[k].avg_context, name: 'Week of ' + fmtWeek(k), x: d3.timeFormat('%b %-d')(pd(k)) }));
      lineChart($('trend-chart'), wk, META.context_target, (p) => p.x);
    } else lineChart($('trend-chart'), ser.map((s) => ({ k: s[0], v: s[7], name: s[1], x: s[1] })), META.context_target, (p) => p.x);
    hbars($('leak-bars'), m.leaks, { badge: (r) => (LIKELY.includes(r[0]) ? 'likely' : 'possible'), color: (r) => (LIKELY.includes(r[0]) ? 'var(--series-1)' : 'var(--cds-chart-reference)'), empty: 'No leaks found. Nice.' });
    hbars($('leak-ses'), m.leak_sessions.map((x) => [x[1], x[2], x[0]]), { name: (r) => nameOf('session', r[0]), onClick: (r) => openSession(r[2]), color: () => 'var(--series-1)' });
    hbars($('b-task'), m.by_task);
    hbars($('b-proj'), m.by_project, { name: (r) => nameOf('project', r[0]) });
    hbars($('b-tool'), m.by_tool, { name: (r) => { const p = r[0].split('__'); return p[0] === 'mcp' && p.length >= 3 ? (p[1].length > 20 ? p[1].slice(0, 8) + '…' : p[1]) + ' · ' + p.slice(2).join('__') : r[0] === '(text reply)' ? 'Text reply' : r[0]; } });
    hbars($('b-model'), m.by_model);
    $('rhythm-card').hidden = !(lvl === 'week' || lvl === 'all'); if (!$('rhythm-card').hidden) rhythm();
    $('cal-card').hidden = !(lvl === 'all' || lvl === 'year'); if (!$('cal-card').hidden) calendar();
  }

  // static text
  const gen = new Date(META.generated_at);
  $('fresh').textContent = 'Claude Code · this computer · updated ' + (isNaN(gen) ? META.generated_at : d3.timeFormat('%b %-d, %H:%M')(gen));
  const li = $('i-leaks'); Object.entries(LEAK_INFO).forEach(([k, v]) => { const p = el('div'); p.append(el('b', null, k + ' '), el('span', null, '(' + (LIKELY.includes(k) ? 'likely' : 'possible') + '): ' + v + '.')); li.appendChild(p); });
  $('method').append(
    el('p', null, `Prices come from Anthropic's published API rates per model, with 1-hour cache writes (2× input) and 5-minute cache writes (1.25×) priced separately; ${P(META.cache_write_1h_share)} of your cache writes are 1-hour. Weighted tokens are that cost in ${META.reference_model} input tokens.`),
    el('p', null, `Each request gets at most one leak cause, so nothing is counted twice. "Likely" covers clear waste; "possible" adds large contexts, noisy tool output and top-tier models on light steps. Your context target is ${C(META.context_target)} (your 30-day median is ${C(META.median_context)}). The prompt cache is assumed to last ${META.cache_ttl_minutes} minutes.`),
    el('p', null, `A day runs from ${hh(META.day_start_hour)} to ${hh(META.day_start_hour)}; weeks start Monday. 5-hour windows open at your first request after the previous one closed. Subagents account for ${P(META.subagent_share)} of usage.` + (META.unknown_models.length ? ' Unknown models priced as the reference: ' + META.unknown_models.join(', ') + '.' : '')),
    el('p', null, 'Only Claude Code sessions on this computer are included. claude.ai, the mobile app and cloud sessions leave no local logs.'));
  $('foot').textContent = `Token Analyzer ${META.version} · ${META.files} log files · your data never leaves this computer.`;
  if (!CAL.weighted_per_pct_5h) $('unit').querySelector('option[value=pct]').disabled = true;

  document.querySelectorAll('.ux-seg button').forEach((b) => b.addEventListener('click', () => go(b.dataset.lvl)));
  $('pick').addEventListener('change', (e) => go(S.lvl, e.target.value));
  $('unit').addEventListener('change', (e) => { S.unit = e.target.value; draw(); });
  const pv = $('privacy'); pv.setAttribute('aria-pressed', String(S.privacy));
  pv.addEventListener('click', () => { S.privacy = !S.privacy; pv.setAttribute('aria-pressed', String(S.privacy)); draw(); });
  $('share').addEventListener('click', (e) => {
    const m = A.levels[S.lvl][S.key];
    const lines = [`${periodName(S.lvl, S.key)}: ${C(m.weighted)} weighted tokens (≈ $${(m.weighted * usdPerW).toFixed(2)} at API prices), ${N(m.requests)} requests, ${m.sessions} sessions.`,
      `${P(m.weighted ? 1 - m.avoid_low / m.weighted : 0)} efficient; avoidable ${C(m.avoid_low)}–${C(m.avoid_high)}.`,
      m.leaks[0] ? `Biggest leak: ${m.leaks[0][0].toLowerCase()}.` : 'No leaks found.', `Context per request ${C(m.avg_context)} (target ${C(META.context_target)}).`, '— Token Analyzer for Claude Code'];
    copyText(lines.join('\n'), e.currentTarget);
  });
  document.querySelectorAll('.ux-i').forEach((b) => b.addEventListener('click', () => { const p = $(b.dataset.info); p.hidden = !p.hidden; b.setAttribute('aria-expanded', String(!p.hidden)); }));
  document.querySelectorAll('.ux-tile').forEach((b) => b.addEventListener('click', () => { const p = $(b.dataset.more); p.hidden = !p.hidden; }));
  const h = (location.hash || '').slice(1).split(':');
  if (['day', 'week', 'month', 'year', 'all'].includes(h[0])) { S.lvl = h[0]; S.key = h[1] || null; }
  draw();
  let rt = null; window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(draw, 150); });
})();
