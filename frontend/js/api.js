/**
 * frontend/js/api.js
 * All HTTP calls to the backend. Nothing else.
 */

const API_BASE = 'https://nerissa-nonvolatilized-drew.ngrok-free.dev';

function _fetch(path, opts = {}) {
  return fetch(API_BASE + path, {
    ...opts,
    headers: {
      'ngrok-skip-browser-warning': '1',
      ...(opts.headers || {}),
    },
  });
}

// ── Voice ─────────────────────────────────────────────────────────────────────

export async function transcribe(audioBlob) {
  const form = new FormData();
  form.append('audio', audioBlob, 'rec.webm');
  const r = await _fetch('/transcribe?engine=google', { method: 'POST', body: form });
  if (!r.ok) throw new Error(`STT ${r.status}`);
  return r.json();
}

export async function synthesize(text) {
  const r = await _fetch('/synthesize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, language_code: 'ka-GE' }),
  });
  if (!r.ok) throw new Error(`TTS ${r.status}`);
  return r.blob();
}

// ── Query ─────────────────────────────────────────────────────────────────────

export async function query(text, extra = {}) {
  const r = await _fetch('/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, ...extra }),
  });
  if (!r.ok) throw new Error(`Query ${r.status}`);
  return r.json();
}

// ── GPS endpoints ─────────────────────────────────────────────────────────────

/**
 * @param {number} lat
 * @param {number} lng
 * @param {number} limit
 * @param {boolean} stopsOnly  true → returns stop names + walk times (no buses)
 */
export async function nearestStopText(lat, lng, limit = 6, stopsOnly = false) {
  const extra = stopsOnly ? '&stops_only=1' : '';
  const r = await _fetch(`/nearest-stop-text?lat=${lat}&lng=${lng}&limit=${limit}${extra}`);
  if (!r.ok) throw new Error(`NearestStop ${r.status}`);
  return r.json();
}

export async function homeRoute(coords) {
  const r = await _fetch('/home-route', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(coords),
  });
  if (!r.ok) throw new Error(`HomeRoute ${r.status}`);
  return r.json();
}

// ── Geocode ───────────────────────────────────────────────────────────────────

export async function geocode(address) {
  const r = await _fetch(`/geocode?address=${encodeURIComponent(address)}`);
  if (!r.ok) throw new Error(`Geocode ${r.status}`);
  return r.json();
}

export async function reverseGeocode(lat, lng) {
  const url =
    `https://nominatim.openstreetmap.org/reverse` +
    `?lat=${lat}&lon=${lng}&format=json&accept-language=ka`;
  const r = await fetch(url, { headers: { 'User-Agent': 'TbilisiAssistant/1.0' } });
  if (!r.ok) throw new Error(`ReverseGeocode ${r.status}`);
  return r.json();
}