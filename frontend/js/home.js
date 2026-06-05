/**
 * frontend/js/home.js
 * Saved home address — localStorage persistence + save actions.
 */
import { geocode, reverseGeocode } from './api.js';
import { getCurrentPosition }      from './gps.js';

const STORAGE_KEY = 'tbilisi_home';
let _home = null;

export function load() {
  try { _home = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'); }
  catch { _home = null; }
  return _home;
}
export function get()     { return _home; }
export function isSaved() { return Boolean(_home?.lat && _home?.lng); }

function _persist(obj) {
  _home = obj;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(obj));
}

/** Save via typed address string — geocodes it first. */
export async function saveByAddress(address) {
  const data = await geocode(address);
  _persist({ address, lat: data.lat, lng: data.lng });
  return _home;
}

/** Save at current GPS position with reverse-geocoded label. */
export async function saveByGPS() {
  const pos = await getCurrentPosition();
  let displayAddr = `${pos.lat.toFixed(5)}, ${pos.lng.toFixed(5)}`;
  try {
    const data = await reverseGeocode(pos.lat, pos.lng);
    const road = data.address?.road || data.address?.suburb || '';
    const city = data.address?.city || data.address?.town   || '';
    if (road)               displayAddr = road + (city ? ', ' + city : '');
    else if (data.display_name)
      displayAddr = data.display_name.split(',').slice(0, 2).join(',').trim();
  } catch { /* keep coordinate string */ }
  _persist({ address: displayAddr, lat: pos.lat, lng: pos.lng });
  return _home;
}

/**
 * Save from already-resolved coords (used when backend geocoded a named address).
 * Called by app.js when save_home_location intent returns coords.
 */
export function saveFromCoords(address, lat, lng) {
  _persist({ address, lat, lng });
  return _home;
}