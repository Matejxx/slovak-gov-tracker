const API = '/api';

let map, selectedFlightLayer;
let aircraftMarkers = {};
let selectedFlightId = null;
let flightOffset = 0;
let flightFilter = '';
let list_aircraft_cache = [];

// ── Map ───────────────────────────────────────────────────────────────────────

function initMap() {
  map = L.map('map', { center: [48.7, 19.5], zoom: 7, zoomControl: false });

  L.control.zoom({ position: 'bottomright' }).addTo(map);

  L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · © <a href="https://carto.com/">CARTO</a>',
    maxZoom: 19,
  }).addTo(map);
}

function planeIcon(heading, airborne, category) {
  const color = airborne ? '#39d353' : '#4a5568';
  const shadow = airborne ? '0 0 6px rgba(57,211,83,.7)' : 'none';
  const rot = category === 'helicopter' ? (heading || 0) : (heading || 0) - 90;

  const shape = category === 'helicopter'
    ? `<svg width="28" height="28" viewBox="0 0 28 28">
        <g transform="rotate(${rot},14,14)">
          <rect x="2" y="12" width="24" height="2.5" rx="1.2" fill="${color}"/>
          <ellipse cx="14" cy="16" rx="5" ry="4" fill="${color}"/>
          <path d="M19 16 Q24 18 26 22" stroke="${color}" stroke-width="2" fill="none"/>
          <rect x="24" y="20" width="3" height="1.5" rx=".7" fill="${color}"/>
        </g>
      </svg>`
    : `<svg width="28" height="28" viewBox="0 0 28 28">
        <g transform="rotate(${rot},14,14)">
          <path d="M14 4 L17 13 L26 15 L17 17 L18 23 L14 21 L10 23 L11 17 L2 15 L11 13 Z"
                fill="${color}" stroke="rgba(255,255,255,.3)" stroke-width=".8"/>
        </g>
      </svg>`;

  return L.divIcon({
    html: `<div style="filter:drop-shadow(${shadow})">${shape}</div>`,
    className: '',
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

// ── Aircraft ──────────────────────────────────────────────────────────────────

function renderAircraftList(list) {
  const el = document.getElementById('aircraft-list');
  const sel = document.getElementById('filter-icao');
  el.innerHTML = '';
  sel.innerHTML = '<option value="">Všetky lietadlá</option>';

  list.forEach(a => {
    const pos = a.latest_position;
    const fresh = pos && (Date.now() - new Date(pos.timestamp).getTime()) < 5 * 60_000;
    let cls, badge, badgeText;
    if (!pos || !fresh)    { cls = '';          badge = 'badge-off'; badgeText = 'Offline'; }
    else if (a.is_airborne){ cls = 'airborne';  badge = 'badge-air'; badgeText = 'Letí'; }
    else                   { cls = 'grounded';  badge = 'badge-gnd'; badgeText = 'Zem'; }

    const reg  = a.registration || a.icao_hex;
    const emoji = a.category === 'helicopter' ? '🚁' : '✈️';
    const photoEl = a.photo_url
      ? `<img class="ac-photo" src="${a.photo_url}" alt="${reg}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
        + `<div class="ac-photo-placeholder" style="display:none">${emoji}</div>`
      : `<div class="ac-photo-placeholder">${emoji}</div>`;

    const card = document.createElement('div');
    card.className = `ac-card ${cls}`;
    card.dataset.icao = a.icao_hex;
    card.innerHTML = `
      ${photoEl}
      <div class="ac-info">
        <div class="ac-reg">${reg}</div>
        <div class="ac-name">${a.label}</div>
      </div>
      <span class="ac-badge ${badge}">${badgeText}</span>`;
    card.addEventListener('click', () => focusAircraft(a.icao_hex));
    el.appendChild(card);

    const opt = document.createElement('option');
    opt.value = a.icao_hex;
    opt.textContent = `${a.label} (${reg})`;
    sel.appendChild(opt);
  });

  // Restore active filter after dropdown re-render
  if (flightFilter) sel.value = flightFilter;
}

function updateMarkers(list) {
  list.forEach(a => {
    const pos = a.latest_position;
    if (!pos?.lat || !pos?.lon) return;

    const icon = planeIcon(pos.heading, a.is_airborne, a.category);
    const latlng = [pos.lat, pos.lon];

    const tip = `<strong>${a.label}</strong><br>
      ${a.registration || a.icao_hex}${a.type ? ' · ' + a.type : ''}<br>
      ${pos.altitude_ft ? pos.altitude_ft.toLocaleString() + ' ft' : ''}
      ${pos.ground_speed ? ' · ' + Math.round(pos.ground_speed) + ' kt' : ''}
      ${pos.flight_number ? '<br>Let: ' + pos.flight_number : ''}`;

    if (aircraftMarkers[a.icao_hex]) {
      aircraftMarkers[a.icao_hex].setLatLng(latlng).setIcon(icon).setTooltipContent(tip);
    } else {
      const m = L.marker(latlng, { icon })
        .addTo(map)
        .bindTooltip(tip, { direction: 'top', className: 'aircraft-tooltip' });
      m.on('click', () => focusAircraft(a.icao_hex));
      aircraftMarkers[a.icao_hex] = m;
    }
  });
}

function focusAircraft(icao) {
  const m = aircraftMarkers[icao];
  if (m) { map.setView(m.getLatLng(), 9, { animate: true }); m.openTooltip(); }

  // Filter flight history to this aircraft
  flightFilter = icao;
  const sel = document.getElementById('filter-icao');
  sel.value = icao;
  loadFlights(false);
}

// ── Flights ───────────────────────────────────────────────────────────────────

function fmt(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('sk-SK', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}
function fmtDur(min) {
  if (!min) return '';
  const h = Math.floor(min / 60), m = min % 60;
  return h ? `${h}h ${m}min` : `${m}min`;
}

function renderFlights(flights, append) {
  const el = document.getElementById('flights-list');
  if (!append) el.innerHTML = '';

  if (!flights.length && !append) {
    el.innerHTML = '<div style="color:var(--muted);font-size:.78rem;padding:6px 0">Žiadne lety</div>';
    return;
  }

  flights.forEach(f => {
    const div = document.createElement('div');
    div.className = `fl-item${f.is_active ? ' active-flight' : ''}${f.id === selectedFlightId ? ' selected' : ''}`;
    div.dataset.id = f.id;
    const route = (f.departure_airport && f.arrival_airport)
      ? `<span class="fl-route">${f.departure_airport} → ${f.arrival_airport}</span>`
      : (f.departure_airport ? `<span class="fl-route">${f.departure_airport} →</span>` : '');
    const acType = list_aircraft_cache.find(a => a.icao_hex === f.aircraft.icao_hex)?.label || '';
    div.innerHTML = `
      <div class="fl-top">
        <span class="fl-reg">${f.is_active ? '<span class="dot"></span>' : ''}${f.aircraft.registration || f.aircraft.icao_hex}</span>
        ${f.flight_number ? `<span class="fl-num">${f.flight_number}</span>` : ''}
      </div>
      ${acType ? `<div class="fl-type">${acType}</div>` : ''}
      <div class="fl-time">${fmt(f.start_time)}${f.duration_minutes ? ' · ' + fmtDur(f.duration_minutes) : ''}</div>
      ${route ? `<div class="fl-dur">${route}</div>` : ''}`;
    div.addEventListener('click', () => loadTrack(f.id));
    el.appendChild(div);
  });
}

async function loadFlights(append) {
  if (!append) flightOffset = 0;
  const params = new URLSearchParams({ limit: 30, offset: flightOffset });
  if (flightFilter) params.set('icao', flightFilter);

  const data = await apiFetch(`/flights?${params}`);
  if (!data) return;

  renderFlights(data.flights, append);
  flightOffset += data.flights.length;

  const btn = document.getElementById('load-more');
  btn.style.display = flightOffset < data.total ? 'block' : 'none';
}

// ── Track ─────────────────────────────────────────────────────────────────────

async function loadTrack(id) {
  selectedFlightId = id;
  document.querySelectorAll('.fl-item').forEach(el => {
    el.classList.toggle('selected', +el.dataset.id === id);
  });

  const data = await apiFetch(`/flights/${id}/track`);
  if (!data) return;

  // On mobile switch to map view to show the track
  if (window.innerWidth <= 768) switchMobileTab('map');

  if (selectedFlightLayer) map.removeLayer(selectedFlightLayer);
  selectedFlightLayer = L.layerGroup().addTo(map);

  const coords = data.track.map(p => [p.lat, p.lon]);
  if (!coords.length) return;

  L.polyline(coords, {
    color: '#58a6ff',
    weight: 2.5,
    opacity: .9,
    dashArray: data.flight.is_active ? null : '6 5',
  }).addTo(selectedFlightLayer);

  L.circleMarker(coords[0], { radius: 5, fillColor: '#39d353', color: '#fff', weight: 2, fillOpacity: 1 })
    .bindTooltip('Vzlet', { direction: 'top', className: 'aircraft-tooltip' })
    .addTo(selectedFlightLayer);

  if (!data.flight.is_active && coords.length > 1) {
    L.circleMarker(coords.at(-1), { radius: 5, fillColor: '#da3633', color: '#fff', weight: 2, fillOpacity: 1 })
      .bindTooltip('Pristátie', { direction: 'top', className: 'aircraft-tooltip' })
      .addTo(selectedFlightLayer);
  }

  map.fitBounds(coords, { padding: [50, 50] });

  const f = data.flight;
  const panel = document.getElementById('flight-panel');
  // Highlight matching aircraft card
  document.querySelectorAll('.ac-card').forEach(el => el.classList.remove('highlighted'));
  const matchCard = document.querySelector(`.ac-card[data-icao="${f.aircraft.icao_hex}"]`);
  if (matchCard) {
    matchCard.classList.add('highlighted');
    matchCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  const ac = list_aircraft_cache.find(a => a.icao_hex === f.aircraft.icao_hex);
  const photoHtml = ac?.photo_url
    ? `<img src="${ac.photo_url}" style="width:100%;border-radius:6px;margin-bottom:10px;object-fit:cover;max-height:80px" loading="lazy">`
    : '';
  document.getElementById('flight-panel-body').innerHTML = `
    ${photoHtml}
    <div class="fp-title">${f.aircraft.registration || f.aircraft.icao_hex} · ${f.aircraft.label}</div>
    <div class="fp-row"><span class="fp-label">Reg.</span><span class="fp-val">${f.aircraft.registration || f.aircraft.icao_hex}</span></div>
    ${f.flight_number ? `<div class="fp-row"><span class="fp-label">Let</span><span class="fp-val">${f.flight_number}</span></div>` : ''}
    <div class="fp-row"><span class="fp-label">Vzlet</span><span class="fp-val">${fmt(f.start_time)}</span></div>
    <div class="fp-row"><span class="fp-label">Pristátie</span><span class="fp-val">${fmt(f.end_time)}</span></div>
    <div class="fp-row"><span class="fp-label">Body trasy</span><span class="fp-val">${coords.length}</span></div>
    ${f.is_active ? '<div class="fp-live"><span class="dot"></span>Let prebieha</div>' : ''}`;
  panel.classList.remove('hidden');
}

// ── Refresh ───────────────────────────────────────────────────────────────────

async function apiFetch(path) {
  try {
    const r = await fetch(API + path);
    if (!r.ok) throw new Error(r.status);
    return r.json();
  } catch (e) {
    console.warn('API error', path, e);
    return null;
  }
}

async function refreshAircraft() {
  const data = await apiFetch('/aircraft');
  if (!data) return;
  list_aircraft_cache = data;
  renderAircraftList(data);
  updateMarkers(data);
  document.getElementById('last-update').textContent =
    'Aktualizované ' + new Date().toLocaleTimeString('sk-SK');
}

async function refreshStats() {
  const data = await apiFetch('/stats');
  if (!data) return;
  document.getElementById('stat-flights').textContent    = `✈ Letov: ${data.total_flights}`;
  document.getElementById('stat-positions').textContent = `📍 Pozícií: ${data.total_positions}`;
}

// ── Boot ──────────────────────────────────────────────────────────────────────

document.getElementById('close-panel').addEventListener('click', () => {
  document.getElementById('flight-panel').classList.add('hidden');
  if (selectedFlightLayer) { map.removeLayer(selectedFlightLayer); selectedFlightLayer = null; }
  selectedFlightId = null;
  document.querySelectorAll('.fl-item').forEach(el => el.classList.remove('selected'));
  document.querySelectorAll('.ac-card').forEach(el => el.classList.remove('highlighted'));
});

document.getElementById('load-more').addEventListener('click', () => loadFlights(true));

document.getElementById('filter-icao').addEventListener('change', e => {
  flightFilter = e.target.value;
  loadFlights(false);
});

function switchMobileTab(tab) {
  document.getElementById('tab-map').classList.toggle('active', tab === 'map');
  document.getElementById('tab-list').classList.toggle('active', tab === 'list');
  document.getElementById('sidebar').classList.toggle('mobile-show', tab === 'list');
  if (tab === 'map') map.invalidateSize();
}

initMap();
refreshAircraft().then(() => loadFlights(false));
refreshStats();

setInterval(refreshAircraft, 30_000);
setInterval(() => loadFlights(false), 120_000);
setInterval(refreshStats, 60_000);
