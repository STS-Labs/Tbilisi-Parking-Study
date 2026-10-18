/* GPX Improver route viewer. Plain script; needs maplibre-gl 4.7.1 loaded first. */
'use strict';

(() => {
  const STATUS = [
    ['covered', '#2ca02c', 'covered'],
    ['wrong_side', '#ff7f0e', 'wrong side'],
    ['not_covered', '#d62728', 'not covered'],
    ['filmed', '#1f77b4', 'filmed (14 Oct)'],
    ['unreachable', '#7f7f7f', 'unreachable'],
    ['not_needed', '#bcbd22', 'not needed'],
    ['other_day', '#bdbdbd', 'other days'],
  ];
  const STATUS_COLOR = Object.fromEntries(STATUS.map(([k, c]) => [k, c]));
  const UNKNOWN_COLOR = '#cccccc';
  const FILMED_COLOR = '#00e5ff';
  const NO_DAY_COLOR = '#888888';
  const LAYER_NAMES = { city_hall: 'City Hall', proposed: 'Proposed' };
  const EMPTY = { type: 'FeatureCollection', features: [] };
  // Time colours for the driven trail: start of the day -> end of the day
  // (plasma, stopping short of its pale yellow; no cyan to mix up with the filmed streets)
  const RAMP = ['#0d0887', '#5c01a6', '#9c179e', '#cc4778', '#ed7953', '#fdb42f'];
  const CLEAR_GRADIENT = ['interpolate', ['linear'], ['line-progress'], 0, 'rgba(0,0,0,0)', 1, 'rgba(0,0,0,0)'];
  const RAMP_RGB = RAMP.map((h) => [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16)));
  function rampAt(t) {                                   // colour of the ramp at 0..1
    const x = Math.max(0, Math.min(1, t)) * (RAMP.length - 1), i = Math.min(RAMP.length - 2, Math.floor(x));
    const f = x - i, a = RAMP_RGB[i], b = RAMP_RGB[i + 1];
    return `rgb(${a.map((v, k) => Math.round(v + f * (b[k] - v))).join(',')})`;
  }
  // The trail: ramp colours from the start up to `frac` of the day, transparent after it (flat stops only)
  function trailGradient(frac) {
    if (frac <= 0) return CLEAR_GRADIENT;
    const e = ['interpolate', ['linear'], ['line-progress']];
    RAMP.forEach((c, i) => { const t = i / (RAMP.length - 1); if (t < frac) e.push(t, c); });
    e.push(frac, rampAt(frac));
    if (frac < 0.9999) e.push(frac + 0.00005, 'rgba(0,0,0,0)', 1, 'rgba(0,0,0,0)');
    return e;
  }

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
  const fmtKm = (v) => (isNum(v) ? v.toFixed(1) : '-');
  const fmtInt = (v) => (isNum(v) ? Math.round(v).toLocaleString('en-US') : '-');

  const state = { manifest: null, set: null, visibleDays: new Set(), routes: null };

  // ---------------------------------------------------------------- map + basemaps
  const map = new maplibregl.Map({
    container: 'map',
    center: [44.79, 41.715],
    zoom: 13,
    hash: true,                  // the view is in the address (#zoom/lat/lon): links open the same spot
    style: {
      version: 8,
      sources: {
        osm: {
          type: 'raster',
          tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
          tileSize: 256,
          maxzoom: 19,
          attribution: '© OpenStreetMap contributors',
        },
        esri: {
          type: 'raster',
          tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
          tileSize: 256,
          maxzoom: 19,
          attribution: 'Esri, Maxar, Earthstar Geographics',
        },
      },
      layers: [
        { id: 'osm', type: 'raster', source: 'osm' },
        { id: 'esri', type: 'raster', source: 'esri', layout: { visibility: 'none' } },
      ],
    },
  });
  map.addControl(new maplibregl.NavigationControl(), 'top-right');
  const mapLoaded = new Promise((resolve) => map.once('load', resolve));

  // ---------------------------------------------------------------- canvas icons
  // Arrow pointing +x (= line direction for symbol-placement: line), turned into a
  // signed distance field so icon-color tints it and icon-halo works.
  function arrowSdf() {
    const size = 32;
    const R = 8; // SDF radius in px (same convention as MapLibre glyphs)
    const c = document.createElement('canvas');
    c.width = c.height = size;
    const ctx = c.getContext('2d');
    ctx.beginPath();
    ctx.moveTo(9, 8);
    ctx.lineTo(24, 16);
    ctx.lineTo(9, 24);
    ctx.lineTo(13, 16);
    ctx.closePath();
    ctx.fill();
    const a = ctx.getImageData(0, 0, size, size).data;
    const inside = new Uint8Array(size * size);
    for (let i = 0; i < size * size; i++) inside[i] = a[i * 4 + 3] > 127 ? 1 : 0;
    const out = new Uint8ClampedArray(size * size * 4);
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        const i = y * size + x;
        let best = (R + 1) * (R + 1);
        for (let yy = Math.max(0, y - R); yy <= Math.min(size - 1, y + R); yy++) {
          for (let xx = Math.max(0, x - R); xx <= Math.min(size - 1, x + R); xx++) {
            if (inside[yy * size + xx] !== inside[i]) {
              const d = (xx - x) ** 2 + (yy - y) ** 2;
              if (d < best) best = d;
            }
          }
        }
        const dist = Math.sqrt(best) - 0.5;
        const outside = inside[i] ? -dist : dist; // >0 outside the shape
        out[i * 4] = out[i * 4 + 1] = out[i * 4 + 2] = 255;
        out[i * 4 + 3] = 255 - 255 * (outside / R + 0.25);
      }
    }
    return { width: size, height: size, data: out };
  }

  function letterIcon(letter, color) {
    const size = 24;
    const c = document.createElement('canvas');
    c.width = c.height = size;
    const ctx = c.getContext('2d');
    ctx.fillStyle = color;
    ctx.font = 'bold 16px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(letter, size / 2, size / 2 + 1);
    const img = ctx.getImageData(0, 0, size, size);
    return { width: size, height: size, data: new Uint8Array(img.data.buffer) };
  }

  // ---------------------------------------------------------------- layers
  const ARROW_LAYOUT = {
    'symbol-placement': 'line',
    'symbol-spacing': 80,
    'icon-image': 'arrow',
    'icon-size': 1,
    'icon-allow-overlap': true,
    'icon-ignore-placement': true,
    'icon-rotation-alignment': 'map',
    'icon-keep-upright': false,
  };
  const ROUTE_LAYERS = ['route-connector', 'route-productive', 'route-arrows',
    'pt-turnaround', 'pt-turnaround-lbl', 'pt-hairpin', 'pt-hairpin-lbl'];

  function statusColorExpr(setId) {
    const m = ['match', ['to-string', ['get', `st_${setId}`]]];
    for (const [k, c] of STATUS) m.push(k, c);
    m.push(UNKNOWN_COLOR);
    return m;
  }

  function addLayers() {
    map.addImage('arrow', arrowSdf(), { sdf: true, pixelRatio: 2 });
    map.addImage('lbl-U', letterIcon('U', '#ffffff'), { pixelRatio: 2 });
    map.addImage('lbl-H', letterIcon('H', '#222222'), { pixelRatio: 2 });

    map.addSource('lots', { type: 'geojson', data: EMPTY });
    map.addSource('filmed', { type: 'geojson', data: EMPTY });
    map.addSource('routes', { type: 'geojson', data: EMPTY });

    // bottom to top: lots, filmed, routes, arrows, points (depot is a DOM marker on top)
    map.addLayer({
      id: 'lots-fill', type: 'fill', source: 'lots',
      paint: { 'fill-color': UNKNOWN_COLOR, 'fill-opacity': 0.45 },
    });
    map.addLayer({
      id: 'lots-line', type: 'line', source: 'lots',
      paint: { 'line-color': UNKNOWN_COLOR, 'line-width': 1.5 },
    });
    map.addLayer({
      id: 'filmed-line', type: 'line', source: 'filmed',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': FILMED_COLOR, 'line-width': 3 },
    });
    map.addLayer({
      id: 'filmed-arrows', type: 'symbol', source: 'filmed', layout: ARROW_LAYOUT,
      paint: { 'icon-color': FILMED_COLOR, 'icon-halo-color': '#003c44', 'icon-halo-width': 1 },
    });
    map.addLayer({
      id: 'route-connector', type: 'line', source: 'routes',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': ['get', '_color'], 'line-width': 2.5, 'line-dasharray': [2, 1.5] },
    });
    map.addLayer({
      id: 'route-productive', type: 'line', source: 'routes',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': ['get', '_color'], 'line-width': 4 },
    });
    map.addLayer({
      id: 'route-arrows', type: 'symbol', source: 'routes', layout: ARROW_LAYOUT,
      paint: { 'icon-color': ['get', '_color'], 'icon-halo-color': '#ffffff', 'icon-halo-width': 1 },
    });
    // playback: the chosen day as one line (lineMetrics -> line-progress for the time gradient)
    map.addSource('play', { type: 'geojson', data: EMPTY, lineMetrics: true });
    map.addLayer({
      id: 'play-rest', type: 'line', source: 'play',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#6b6b6b', 'line-width': 2.5, 'line-opacity': 0.55 },
    });
    map.addLayer({
      id: 'play-driven', type: 'line', source: 'play',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-width': 5, 'line-gradient': CLEAR_GRADIENT },
    });
    map.addLayer({
      id: 'pt-turnaround', type: 'circle', source: 'routes',
      paint: {
        'circle-radius': 7, 'circle-color': ['get', '_color'],
        'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2,
      },
    });
    map.addLayer({
      id: 'pt-turnaround-lbl', type: 'symbol', source: 'routes',
      layout: { 'icon-image': 'lbl-U', 'icon-allow-overlap': true, 'icon-ignore-placement': true },
    });
    map.addLayer({
      id: 'pt-hairpin', type: 'circle', source: 'routes',
      paint: {
        'circle-radius': 7, 'circle-color': '#ffffff',
        'circle-stroke-color': ['get', '_color'], 'circle-stroke-width': 3,
      },
    });
    map.addLayer({
      id: 'pt-hairpin-lbl', type: 'symbol', source: 'routes',
      layout: { 'icon-image': 'lbl-H', 'icon-allow-overlap': true, 'icon-ignore-placement': true },
    });
  }

  // ---------------------------------------------------------------- filters
  function applyDayFilter() {
    const days = ['in', ['get', 'day'], ['literal', [...state.visibleDays]]];
    const kind = (...k) => ['in', ['get', 'kind'], ['literal', k]];
    const filters = {
      'route-connector': kind('connector'),
      'route-productive': kind('productive'),
      'route-arrows': kind('productive', 'connector'),
      'pt-turnaround': kind('turnaround'),
      'pt-turnaround-lbl': kind('turnaround'),
      'pt-hairpin': kind('hairpin', 'uturn'),
      'pt-hairpin-lbl': kind('hairpin', 'uturn'),
    };
    for (const id of ROUTE_LAYERS) map.setFilter(id, ['all', filters[id], days]);
  }

  function applyLotFilter() {
    const hidden = [];
    if (!$('show-cityhall').checked) hidden.push('city_hall');
    if (!$('show-proposed').checked) hidden.push('proposed');
    const f = ['!', ['in', ['to-string', ['get', 'layer']], ['literal', hidden]]];
    map.setFilter('lots-fill', f);
    map.setFilter('lots-line', f);
  }

  function applyFilmedVisibility() {
    const v = $('show-filmed').checked ? 'visible' : 'none';
    map.setLayoutProperty('filmed-line', 'visibility', v);
    map.setLayoutProperty('filmed-arrows', 'visibility', v);
  }

  function applyBasemap(which) {
    map.setLayoutProperty('osm', 'visibility', which === 'osm' ? 'visible' : 'none');
    map.setLayoutProperty('esri', 'visibility', which === 'esri' ? 'visible' : 'none');
  }

  // ---------------------------------------------------------------- panel
  function showMessage(html) {
    $('message').innerHTML = html;
    $('message').hidden = false;
  }
  function hideMessage() {
    $('message').hidden = true;
  }

  function buildLegend() {
    const set = state.set;
    const counts = (state.manifest.status_counts || {})[set.id] || {};
    $('legend-set').textContent = `(${set.label || set.id})`;
    $('legend').tBodies[0].innerHTML = STATUS.map(([k, c, label]) => `
      <tr><td><span class="swatch" style="background:${c}"></span></td>
          <td>${esc(label)}</td><td class="num">${fmtInt(counts[k])}</td></tr>`).join('');
  }

  function buildDays() {
    const days = state.set.days || [];
    const tbody = $('days').tBodies[0];
    tbody.innerHTML = days.map((d) => `
      <tr>
        <td class="vis"><input type="checkbox" data-day="${esc(d.n)}" checked
            ><span class="swatch" style="background:${esc(d.color || NO_DAY_COLOR)}"></span></td>
        <td class="name"><a href="#" data-zoom="${esc(d.n)}">${esc(d.name || `Day ${d.n}`)}</a></td>
        <td>${fmtKm(d.km)}</td><td>${fmtKm(d.productive_km)}</td><td>${fmtKm(d.connector_km)}</td>
        <td>${fmtKm(d.redriven_km)}</td><td>${fmtInt(d.uturns)}</td><td>${fmtInt(d.lefts)}</td>
        <td>${fmtInt(d.new_lots)}</td>
      </tr>`).join('');
    const sum = (k) => days.reduce((s, d) => s + (isNum(d[k]) ? d[k] : 0), 0);
    $('days').tFoot.innerHTML = `
      <tr><td></td><td class="name">Total (${days.length} days)</td>
        <td>${fmtKm(sum('km'))}</td><td>${fmtKm(sum('productive_km'))}</td><td>${fmtKm(sum('connector_km'))}</td>
        <td>${fmtKm(sum('redriven_km'))}</td><td>${fmtInt(sum('uturns'))}</td><td>${fmtInt(sum('lefts'))}</td>
        <td>${fmtInt(sum('new_lots'))}</td></tr>`;
  }

  function setAllDays(on) {
    state.visibleDays = new Set(on ? (state.set.days || []).map((d) => Number(d.n)) : []);
    for (const cb of $('days').querySelectorAll('input[data-day]')) cb.checked = on;
    applyDayFilter();
  }

  async function fetchJson(url) {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
    return r.json();
  }

  async function selectSet(id) {
    const set = state.manifest.sets.find((s) => s.id === id) || state.manifest.sets[0];
    playbackStop();
    state.routes = null;
    state.set = set;
    state.visibleDays = new Set((set.days || []).map((d) => Number(d.n)));
    buildDays();
    buildLegend();
    const colour = statusColorExpr(set.id);
    map.setPaintProperty('lots-fill', 'fill-color', colour);
    map.setPaintProperty('lots-line', 'line-color', colour);
    applyDayFilter();
    map.getSource('routes').setData(EMPTY);
    hideMessage();

    let gj;
    try {
      gj = await fetchJson(`data/${set.routes}`);
    } catch (err) {
      console.error(err);
      if (state.set === set) showMessage(`Could not load routes file <code>${esc(set.routes)}</code> for "${esc(set.label)}".`);
      return;
    }
    if (state.set !== set) return; // user switched again while loading
    const colours = new Map((set.days || []).map((d) => [Number(d.n), d.color]));
    for (const f of gj.features || []) {
      const p = (f.properties ||= {});
      p.day = Number(p.day);
      p._color = colours.get(p.day) || NO_DAY_COLOR;
    }
    map.getSource('routes').setData(gj);
    state.routes = gj;
    fillPlaybackDays();
  }

  // ---------------------------------------------------------------- playback
  // A day's pieces are written in driving order, so joining them gives the whole drive.
  const pb = {
    day: null, coords: [], cum: [], kinds: [], total: 0, pos: 0,
    playing: false, raf: 0, lastT: 0, lastPaint: 0, lastFollow: 0, marker: null,
  };

  function kmBetween(a, b) {
    const R = 6371.0088, rad = Math.PI / 180;
    const dLat = (b[1] - a[1]) * rad, dLon = (b[0] - a[0]) * rad;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }

  function dayPath(n) {
    const coords = [], kinds = [];
    for (const f of (state.routes && state.routes.features) || []) {
      if (!f.geometry || f.geometry.type !== 'LineString' || Number(f.properties.day) !== n) continue;
      const c = f.geometry.coordinates;
      let i = 0;
      if (coords.length) {
        const last = coords[coords.length - 1];
        if (last[0] === c[0][0] && last[1] === c[0][1]) i = 1;
      }
      for (; i < c.length; i++) { coords.push(c[i]); kinds.push(f.properties.kind || ''); }
    }
    const cum = [0];
    for (let i = 1; i < coords.length; i++) cum.push(cum[i - 1] + kmBetween(coords[i - 1], coords[i]));
    return { coords, kinds, cum, total: cum[cum.length - 1] || 0 };
  }

  function fillPlaybackDays() {
    const sel = $('pb-day');
    sel.innerHTML = '<option value="">choose a day...</option>' + (state.set.days || [])
      .map((d) => `<option value="${esc(d.n)}">${esc(d.name || `Day ${d.n}`)} (${fmtKm(d.km)} km)</option>`).join('');
    sel.disabled = false;
  }

  function carElement() {
    const el = document.createElement('div');
    el.className = 'pb-car';
    el.innerHTML = '<svg viewBox="0 0 30 30"><circle cx="15" cy="15" r="13" fill="#111" stroke="#fff" stroke-width="2"/>'
      + '<path d="M15 5 L22 21 L15 17 L8 21 Z" fill="#fff"/></svg>';
    return el;
  }

  function setPlanDimmed(dim) {
    const o = dim ? 0.18 : 1;
    map.setPaintProperty('route-connector', 'line-opacity', o);
    map.setPaintProperty('route-productive', 'line-opacity', o);
    map.setPaintProperty('route-arrows', 'icon-opacity', o);
  }

  function setButtons(active) {
    for (const id of ['pb-play', 'pb-restart', 'pb-stop', 'pb-pos']) $(id).disabled = !active;
    $('pb-play').innerHTML = pb.playing ? '&#10073;&#10073; Pause' : '&#9654; Play';
  }

  function playbackStart(n) {
    playbackStop();
    const path = dayPath(n);
    if (path.coords.length < 2) return;
    Object.assign(pb, path, { day: n, pos: 0 });
    map.getSource('play').setData({
      type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: path.coords } });
    // show only this day, dimmed, under the playback lines
    state.visibleDays = new Set([n]);
    for (const cb of $('days').querySelectorAll('input[data-day]')) cb.checked = Number(cb.dataset.day) === n;
    applyDayFilter();
    setPlanDimmed(true);
    pb.marker = new maplibregl.Marker({ element: carElement(), rotationAlignment: 'map' })
      .setLngLat(path.coords[0]).addTo(map);
    const d = (state.set.days || []).find((x) => Number(x.n) === n);
    if (d && Array.isArray(d.bbox) && d.bbox.length === 4) map.fitBounds(d.bbox, { padding: 40, maxZoom: 16 });
    $('pb-day').value = String(n);
    setButtons(true);
    render(true);
  }

  function playbackStop() {
    pause();
    if (pb.marker) pb.marker.remove();
    Object.assign(pb, { day: null, coords: [], cum: [], kinds: [], total: 0, pos: 0, marker: null });
    if (map.getSource('play')) {
      map.getSource('play').setData(EMPTY);
      map.setPaintProperty('play-driven', 'line-gradient', CLEAR_GRADIENT);
      setPlanDimmed(false);
    }
    if ($('pb-day').options.length) $('pb-day').value = '';
    $('pb-pos').value = 0;
    $('pb-readout').textContent = 'Pick a day to watch the car drive it in order.';
    setButtons(false);
  }

  function play() {
    if (pb.day === null) return;
    if (pb.pos >= pb.total) pb.pos = 0;
    pb.playing = true;
    pb.lastT = performance.now();
    setButtons(true);
    pb.raf = requestAnimationFrame(tick);
  }

  function pause() {
    pb.playing = false;
    cancelAnimationFrame(pb.raf);
    if (pb.day !== null) setButtons(true);
  }

  function tick(t) {
    if (!pb.playing) return;
    const dt = Math.min(0.25, (t - pb.lastT) / 1000);   // a background tab must not jump ahead
    pb.lastT = t;
    pb.pos = Math.min(pb.total, pb.pos + Number($('pb-speed').value) * dt);
    render(false);
    if (pb.pos >= pb.total) { pause(); render(true); return; }
    pb.raf = requestAnimationFrame(tick);
  }

  // index of the segment holding along-distance km
  function segAt(km) {
    let lo = 0, hi = pb.cum.length - 1;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (pb.cum[mid] <= km) lo = mid; else hi = mid; }
    return lo;
  }

  function render(force) {
    const i = segAt(pb.pos);
    const a = pb.coords[i], b = pb.coords[Math.min(i + 1, pb.coords.length - 1)];
    const L = pb.cum[i + 1] - pb.cum[i] || 1;
    const f = Math.max(0, Math.min(1, (pb.pos - pb.cum[i]) / L));
    const here = [a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])];
    const lat = a[1] * Math.PI / 180;
    const heading = Math.atan2((b[0] - a[0]) * Math.cos(lat), b[1] - a[1]) * 180 / Math.PI;
    pb.marker.setLngLat(here).setRotation(heading);

    const now = performance.now();
    const frac = pb.total ? pb.pos / pb.total : 0;
    if (force || now - pb.lastPaint > 60) {             // the gradient is cheap, but not every frame
      pb.lastPaint = now;
      map.setPaintProperty('play-driven', 'line-gradient', trailGradient(frac));
      $('pb-pos').value = Math.round(frac * 1000);
      const kind = pb.kinds[Math.min(i + 1, pb.kinds.length - 1)];
      $('pb-readout').textContent = `${pb.pos.toFixed(1)} / ${pb.total.toFixed(1)} km (${Math.round(frac * 100)}%)`
        + (kind ? ` - ${kind === 'productive' ? 'filming new lots' : 'connector'}` : '');
    }
    if ($('pb-follow').checked && pb.playing && now - pb.lastFollow > 300) {
      pb.lastFollow = now;
      const p = map.project(here), c = map.getCanvas();
      const w = c.clientWidth, h = c.clientHeight;
      if (p.x < w * 0.2 || p.x > w * 0.8 || p.y < h * 0.2 || p.y > h * 0.8) map.easeTo({ center: here, duration: 600 });
    }
  }

  function seek(km) {
    if (pb.day === null) return;
    pb.pos = Math.max(0, Math.min(pb.total, km));
    render(true);
  }

  function wirePlayback() {
    $('pb-day').addEventListener('change', (e) => {
      if (e.target.value === '') playbackStop(); else playbackStart(Number(e.target.value));
    });
    $('pb-play').addEventListener('click', () => (pb.playing ? pause() : play()));
    $('pb-restart').addEventListener('click', () => seek(0));
    $('pb-stop').addEventListener('click', () => { playbackStop(); setAllDays(true); });
    $('pb-pos').addEventListener('input', (e) => seek(Number(e.target.value) / 1000 * pb.total));
    document.addEventListener('keydown', (e) => {
      const el = e.target instanceof Element ? e.target : document.body;
      if (pb.day === null || el.closest('select, input[type="text"], textarea')) return;
      if (e.code === 'Space') { e.preventDefault(); if (pb.playing) pause(); else play(); }
      else if (el.closest('#map')) return;                 // arrow keys pan the map when it has focus
      else if (e.code === 'ArrowRight') { e.preventDefault(); seek(pb.pos + 0.5); }
      else if (e.code === 'ArrowLeft') { e.preventDefault(); seek(pb.pos - 0.5); }
    });
  }

  // ---------------------------------------------------------------- popups
  function lotPopupHtml(p) {
    const st = p[`st_${state.set.id}`];
    const zone = [p.zone, p.ptype].filter((v) => v !== undefined && v !== null && v !== '').join(' / ');
    const rows = [
      ['Layer', LAYER_NAMES[p.layer] || p.layer],
      ['Address', p.address],
      ['Spaces', p.spaces],
      ['Zone / type', zone],
      ['Status', `<span class="swatch" style="background:${STATUS_COLOR[st] || UNKNOWN_COLOR}"></span> ${esc(st ?? '-')}`, true],
      ['Reason', p.reason],
    ];
    return `<div class="title">${esc(p.id)}</div><table>${rows
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v, raw]) => `<tr><td class="muted">${k}</td><td>${raw ? v : esc(v)}</td></tr>`)
      .join('')}</table>`;
  }

  function pointPopupHtml(p) {
    const day = (state.set.days || []).find((d) => Number(d.n) === p.day);
    const kind = p.kind === 'hairpin' ? 'Hairpin' : p.kind === 'uturn' ? 'U-turn (not at a dead end)' : 'Turnaround';
    return `<div class="title">${kind} - ${esc(day ? day.name : `Day ${p.day}`)}</div>${esc(p.note || '')}`;
  }

  function wirePopups() {
    const pointLayers = ['pt-turnaround', 'pt-hairpin'];
    map.on('click', (e) => {
      if (!state.set) return;
      const pad = 4;
      const box = [[e.point.x - pad, e.point.y - pad], [e.point.x + pad, e.point.y + pad]];
      const pt = map.queryRenderedFeatures(box, { layers: pointLayers })[0];
      if (pt) {
        new maplibregl.Popup().setLngLat(pt.geometry.coordinates).setHTML(pointPopupHtml(pt.properties)).addTo(map);
        return;
      }
      const lot = map.queryRenderedFeatures(e.point, { layers: ['lots-fill'] })[0];
      if (lot) new maplibregl.Popup().setLngLat(e.lngLat).setHTML(lotPopupHtml(lot.properties)).addTo(map);
    });
    for (const id of [...pointLayers, 'lots-fill']) {
      map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', id, () => { map.getCanvas().style.cursor = ''; });
    }
  }

  // ---------------------------------------------------------------- controls
  function wireControls() {
    $('show-cityhall').addEventListener('change', applyLotFilter);
    $('show-proposed').addEventListener('change', applyLotFilter);
    $('show-filmed').addEventListener('change', applyFilmedVisibility);
    $('set-select').addEventListener('change', (e) => selectSet(e.target.value));
    $('days-all').addEventListener('click', () => setAllDays(true));
    $('days-none').addEventListener('click', () => setAllDays(false));

    const days = $('days');
    days.addEventListener('change', (e) => {
      const cb = e.target.closest('input[data-day]');
      if (!cb) return;
      const n = Number(cb.dataset.day);
      if (cb.checked) state.visibleDays.add(n); else state.visibleDays.delete(n);
      applyDayFilter();
    });
    days.addEventListener('click', (e) => {
      const a = e.target.closest('a[data-zoom]');
      if (!a) return;
      e.preventDefault();
      const d = (state.set.days || []).find((x) => String(x.n) === a.dataset.zoom);
      if (d && Array.isArray(d.bbox) && d.bbox.length === 4) map.fitBounds(d.bbox, { padding: 40, maxZoom: 17 });
    });
  }

  // ---------------------------------------------------------------- start
  async function init() {
    // basemap switching works even without a plan
    for (const r of document.querySelectorAll('input[name="basemap"]')) {
      r.addEventListener('change', () => { if (r.checked) mapLoaded.then(() => applyBasemap(r.value)); });
    }

    let manifest;
    try {
      manifest = await fetchJson('data/manifest.json');
      if (!Array.isArray(manifest.sets) || manifest.sets.length === 0) throw new Error('manifest has no sets');
    } catch (err) {
      console.warn(err);
      showMessage('No plan yet - run <code>make plan</code>');
      return;
    }
    state.manifest = manifest;
    if (manifest.generated) $('generated').textContent = `Plan generated ${manifest.generated}`;

    const sel = $('set-select');
    sel.innerHTML = manifest.sets.map((s) => `<option value="${esc(s.id)}">${esc(s.label || s.id)}</option>`).join('');
    sel.disabled = false;

    const optional = (name) => fetchJson(`data/${name}`).catch((err) => { console.warn(err); return EMPTY; });
    const [lots, filmed] = await Promise.all([optional('lots.geojson'), optional('filmed.geojson'), mapLoaded]);

    addLayers();
    map.getSource('lots').setData(lots);
    map.getSource('filmed').setData(filmed);
    if (Array.isArray(manifest.depot) && manifest.depot.length === 2) {
      new maplibregl.Marker({ color: '#111111' })
        .setLngLat(manifest.depot)
        .setPopup(new maplibregl.Popup({ offset: 25 }).setText('Depot'))
        .addTo(map);
    }

    wireControls();
    wirePlayback();
    wirePopups();
    applyLotFilter();
    applyFilmedVisibility();
    await selectSet(manifest.sets[0].id);
  }

  init().catch((err) => {
    console.error(err);
    showMessage(`Viewer error: ${esc(err.message)}`);
  });
})();
