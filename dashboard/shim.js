/* Minimal runtime for the dashboard page when opened as a local file.
   Provides the small `dash` API the page uses: data, calc, onData, params, setParams, setLink, colors. */
(function () {
  const raw = window.__CTA_DATA || {};
  const calcs = {}, cache = {}, subs = [];
  let params = {};
  const resolve = (id) => {
    if (id in cache) return cache[id];
    if (raw[id]) return (cache[id] = raw[id]);
    const c = calcs[id];
    if (!c) throw new Error('Unknown dataset ' + id);
    return (cache[id] = c.fn(...c.inputs.map(resolve)));
  };
  let timer = null;
  const fire = () => subs.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });
  window.dash = {
    colors: ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)', 'var(--series-5)', 'var(--series-6)', 'var(--series-7)', 'var(--series-8)'],
    calc: (id, def) => { calcs[id] = def; },
    loader: () => {},
    data: (id) => {
      try { const d = resolve(id); return { status: 'ok', data: d, rows: d, refreshing: false, meta: [] }; }
      catch (e) { console.error(e); return { status: 'error', data: [], message: String(e) }; }
    },
    onData: (fn) => { subs.push(fn); },
    params: () => ({ ...params }),
    setParams: (p) => { params = { ...params, ...p }; fire(); },
    resetParams: () => { params = {}; fire(); },
    setLink: (name) => { if (history.replaceState) history.replaceState(null, '', '#' + name); },
    refresh: () => {},
    __start: () => { fire(); window.addEventListener('resize', () => { clearTimeout(timer); timer = setTimeout(fire, 150); }); },
  };
})();
