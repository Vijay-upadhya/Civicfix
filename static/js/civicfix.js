const CF = {};
CF.cookie = n => (document.cookie.split('; ').find(r => r.startsWith(n + '=')) || '').split('=')[1];
CF.esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
CF.api = async (path, opts = {}) => {
  const init = {method: opts.method || 'GET', headers: {'X-CSRFToken': CF.cookie('csrftoken') || ''}, credentials: 'same-origin'};
  if (opts.form) init.body = opts.form;
  else if (opts.body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
  const r = await fetch('/api' + path, init);
  const data = r.status === 204 ? null : await r.json().catch(() => null);
  if (!r.ok) { const e = new Error('API error'); e.status = r.status; e.data = data; throw e; }
  return data;
};
CF.errText = e => { const d = e.data; if (!d) return 'Something went wrong.'; if (typeof d === 'string') return d;
  return Object.entries(d).map(([k, v]) => (k === 'detail' || k === 'non_field_errors' ? '' : k + ': ') + (Array.isArray(v) ? v.join(' ') : typeof v === 'object' ? JSON.stringify(v) : v)).join(' | '); };
CF.STATUS = {DRAFT:['Draft','bi-pencil'],SUBMITTED:['Submitted','bi-send'],UNDER_REVIEW:['Under review','bi-search'],ASSIGNED:['Assigned','bi-person-check'],
  IN_PROGRESS:['In progress','bi-tools'],WAITING_INFO:['Waiting for information','bi-question-circle'],RESOLVED:['Resolved','bi-check-circle'],
  CLOSED:['Closed','bi-lock'],REOPENED:['Reopened','bi-arrow-counterclockwise'],REJECTED:['Rejected','bi-x-circle'],MERGED:['Merged','bi-diagram-2']};
CF.statusBadge = s => { const [t, i] = CF.STATUS[s] || [s, 'bi-dot']; return `<span class="badge-s s-${s}"><i class="bi ${i}"></i>${CF.esc(t)}</span>`; };
CF.prioBadge = l => `<span class="badge-s p-${l}"><i class="bi bi-flag-fill"></i>${CF.esc(l[0] + l.slice(1).toLowerCase())}</span>`;
CF.color = (prio, status) => (['RESOLVED','CLOSED'].includes(status) ? '#6B7280' : {CRITICAL:'#DC2626',HIGH:'#F97316',MEDIUM:'#EAB308',LOW:'#16A34A'}[prio] || '#2563EB');
CF.ago = d => { if (!d) return '—'; const s = (Date.now() - new Date(d)) / 1000;
  return s < 3600 ? Math.max(1, Math.floor(s / 60)) + ' min ago' : s < 86400 ? Math.floor(s / 3600) + ' h ago' : Math.floor(s / 86400) + ' days ago'; };
CF.date = d => d ? new Date(d).toLocaleString('en-IN', {day: 'numeric', month: 'long', hour: 'numeric', minute: '2-digit'}) : '—';
CF.googleOn = () => !!(window.CF_CONFIG && CF_CONFIG.googleMapsKey && window.google && google.maps && google.maps.Map && L.gridLayer && L.gridLayer.googleMutant);
CF._maps = [];
CF._osm = () => L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'});
CF.map = (el, center = [12.9352, 77.6245], zoom = 12) => {
  const m = L.map(el).setView(center, zoom);
  const layer = CF.googleOn() ? L.gridLayer.googleMutant({type: 'roadmap', maxZoom: 20}) : CF._osm();
  layer.addTo(m); CF._maps.push({map: m, layer});
  return m;
};
// If Google rejects the key (wrong referrer, API not enabled, billing off) fall back to OpenStreetMap.
window.gm_authFailure = () => {
  console.warn('Google Maps key was rejected; falling back to OpenStreetMap.');
  CF_CONFIG.googleMapsKey = '';
  CF._maps.forEach(x => { try { x.map.removeLayer(x.layer); x.layer = CF._osm().addTo(x.map); } catch (e) {} });
  document.querySelectorAll('.gm-err').forEach(n => n.remove());
  const b = document.createElement('div'); b.className = 'alert alert-warning m-0 rounded-0 text-center small';
  b.textContent = 'Google Maps could not load (check the API key, billing and enabled APIs). Showing OpenStreetMap instead.';
  document.body.prepend(b);
};
// Address lookup: Google Geocoder when Google Maps is active, otherwise OpenStreetMap Nominatim.
CF.geocode = {
  _ward: comps => { const c = (comps || []).find(x => x.types.some(t => ['sublocality_level_1', 'sublocality', 'neighborhood'].includes(t))); return c ? c.long_name : ''; },
  async reverse(lat, lng) {
    if (CF.googleOn()) {
      const r = await new google.maps.Geocoder().geocode({location: {lat, lng}});
      const f = r.results[0]; return f ? {address: f.formatted_address, ward: this._ward(f.address_components)} : {address: '', ward: ''};
    }
    const r = await fetch(`https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lng}`).then(r => r.json());
    const a = r.address || {}; return {address: r.display_name || '', ward: a.suburb || a.neighbourhood || a.city_district || ''};
  },
  async search(q) {
    if (CF.googleOn()) {
      const r = await new google.maps.Geocoder().geocode({address: q});
      const f = r.results[0]; return f ? {lat: f.geometry.location.lat(), lng: f.geometry.location.lng(), address: f.formatted_address} : null;
    }
    const r = await fetch('https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=' + encodeURIComponent(q)).then(r => r.json());
    return r[0] ? {lat: +r[0].lat, lng: +r[0].lon, address: r[0].display_name} : null;
  }
};
CF.marker = (c, status) => L.marker([c.lat, c.lng], {icon: L.divIcon({className: '', html: `<div class="mk" style="background:${CF.color(c.prio, status)}"></div>`, iconSize: [18, 18]})});
CF.markers = (map, items, layer) => {
  if (layer) layer.clearLayers(); layer = L.layerGroup().addTo(map); const pts = [];
  items.forEach(c => { const m = CF.marker(c, c.status).addTo(layer); pts.push([c.lat, c.lng]);
    m.bindPopup(`<strong>${CF.esc(c.number)}</strong><br>${CF.esc(c.title)}<br>${CF.esc(c.category || '')} · ${CF.esc(c.prio)} · ${CF.esc((CF.STATUS[c.status] || [c.status])[0])}<br>${CF.esc(c.ward || '')}<br><a class="btn btn-sm btn-primary mt-1" href="/complaints/${c.id}/">View details</a>`); });
  if (pts.length) map.fitBounds(pts, {padding: [30, 30], maxZoom: 15});
  return layer;
};
CF.fromComplaint = c => ({id: c.id, number: c.complaint_number || 'Draft', title: c.title, category: c.category && c.category.name, prio: c.priority.level,
  status: c.status, ward: c.location.ward, lat: c.location.latitude, lng: c.location.longitude});
CF.card = c => `<a class="complaint-card border-bottom" href="/complaints/${c.id}/"><div class="d-flex justify-content-between flex-wrap gap-1"><small class="text-muted">${CF.esc(c.complaint_number || 'Draft')}</small><small class="text-muted">${CF.ago(c.submitted_at || c.created_at)}</small></div>
 <div class="fw-semibold">${CF.esc(c.title)}</div><div class="d-flex flex-wrap gap-2 align-items-center mt-1">${CF.prioBadge(c.priority.level)}${CF.statusBadge(c.status)}
 <small class="text-muted"><i class="bi bi-hand-thumbs-up"></i> ${c.upvotes} upvotes</small><small class="text-muted"><i class="bi bi-geo-alt"></i> ${CF.esc(c.location.ward || 'Unknown ward')}</small></div></a>`;
CF.alert = (el, msg, type = 'danger') => { el.innerHTML = msg ? `<div class="alert alert-${type} py-2">${CF.esc(msg)}</div>` : ''; };
CF.chart = (id, type, labels, data, label, colors) => new Chart(document.getElementById(id), {type, data: {labels, datasets: [{label, data,
  backgroundColor: colors || ['#2563EB','#0F766E','#16A34A','#D97706','#DC2626','#7C3AED','#0891B2','#DB2777','#65A30D','#EA580C','#475569','#94A3B8'], borderColor: type === 'line' ? '#2563EB' : undefined, tension: .3}]},
  options: {plugins: {legend: {display: type === 'doughnut'}}, scales: type === 'doughnut' ? {} : {y: {beginAtZero: true, ticks: {precision: 0}}}}});

// ---- Location / map-services permission
CF.consent = {
  state: null,
  async get() { if (this.state === null) { const me = await CF.api('/auth/me/'); this.state = !!me.location_consent; } return this.state; },
  async set(granted) { await CF.api('/auth/location-consent/', {method: 'POST', body: {granted}}); this.state = granted; },
  async ensure() {
    if (await this.get()) return true;
    return new Promise(resolve => {
      const el = document.createElement('div');
      el.className = 'modal fade'; el.tabIndex = -1;
      el.innerHTML = `<div class="modal-dialog"><div class="modal-content"><div class="modal-header"><h5 class="modal-title"><i class="bi bi-geo-alt"></i> Allow location features?</h5></div>
        <div class="modal-body"><p>CivicFix can use your location to pin a complaint, show nearby issues and sort by distance.</p>
        <ul class="small text-muted"><li>Your browser will ask for its own permission next.</li><li>Looking up an address sends the coordinates to the map provider (Google Maps, or OpenStreetMap's Nominatim if Google is not configured).</li><li>The map itself is loaded from that provider, which can see your IP address.</li></ul>
        <p class="small mb-0">You can withdraw this any time on your profile page. Without it you can still place a pin by clicking the map.</p></div>
        <div class="modal-footer"><button class="btn btn-outline-secondary" data-r="0">Not now</button><button class="btn btn-primary" data-r="1">Allow</button></div></div></div>`;
      document.body.appendChild(el);
      const m = new bootstrap.Modal(el, {backdrop: 'static', keyboard: false});
      el.querySelectorAll('button[data-r]').forEach(b => b.onclick = async () => {
        const ok = b.dataset.r === '1';
        try { if (ok) await CF.consent.set(true); } catch (e) {}
        m.hide(); el.addEventListener('hidden.bs.modal', () => el.remove()); resolve(ok);
      });
      m.show();
    });
  }
};
CF.locate = async () => {
  if (!(await CF.consent.ensure())) { const e = new Error('consent'); e.code = 'CONSENT'; throw e; }
  if (!navigator.geolocation) { const e = new Error('unsupported'); e.code = 'UNSUPPORTED'; throw e; }
  return new Promise((res, rej) => navigator.geolocation.getCurrentPosition(p => res(p.coords), rej, {enableHighAccuracy: true, timeout: 15000}));
};
CF.geoError = e => e.code === 'CONSENT' ? 'Location features are off. You can still click the map to place a pin.'
  : e.code === 'UNSUPPORTED' ? 'This browser does not support location. Click the map to place a pin.'
  : e.code === 1 ? 'Your browser blocked location access. Click the lock icon in the address bar, allow Location for this site, then try again. Or just click the map.'
  : e.code === 2 ? 'Your location could not be determined. Click the map to place a pin.'
  : e.code === 3 ? 'Finding your location timed out. Try again or click the map.' : 'Could not get your location.';
