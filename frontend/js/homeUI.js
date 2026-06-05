/**
 * frontend/js/homeUI.js
 *
 * Home address panel UI.
 *
 * Behaviour:
 *  - Save button is DISABLED (grayed) when the typed address matches what's
 *    already saved. It re-enables as soon as the user edits the field.
 *  - "GPS = სახლი" fills the input with the reverse-geocoded address of the
 *    current position but does NOT save automatically. The user still has to
 *    click Save.
 *  - refreshSavedDisplay(home) — called externally (e.g. after voice command
 *    saves home) to keep the panel in sync.
 */

import * as Home from './home.js';
import { getCurrentPosition } from './gps.js';
import { reverseGeocode }     from './api.js';

const overlay   = document.getElementById('home-overlay');
const homeBtn   = document.getElementById('home-btn');
const addrInput = document.getElementById('home-addr');
const statusEl  = document.getElementById('home-status');
const saveBtn   = document.getElementById('home-save');
const gpsBtn    = document.getElementById('home-gps');

// Coordinates staged by GPS button — only committed on Save
let _stagedLat = null;
let _stagedLng = null;

// ── Helpers ───────────────────────────────────────────────────────────────────

function _savedAddress() {
  return Home.get()?.address || '';
}

/** Gray out save button when input matches the already-saved address. */
function _syncSaveBtn() {
  const typed = addrInput.value.trim();
  const same  = typed !== '' && typed === _savedAddress();
  saveBtn.disabled = same;
  saveBtn.style.opacity  = same ? '0.45' : '1';
  saveBtn.style.cursor   = same ? 'default' : 'pointer';
}

// ── Init ──────────────────────────────────────────────────────────────────────

export function init() {
  const saved = Home.load();
  if (saved) {
    addrInput.value      = saved.address || '';
    statusEl.textContent = '✓ სახლი შენახულია';
    homeBtn.classList.add('saved');
  }
  _syncSaveBtn();
}

/** Called externally when a voice command saves a new home address. */
export function refreshSavedDisplay(saved) {
  if (!saved) return;
  addrInput.value      = saved.address || '';
  statusEl.textContent = '✓ სახლი შენახულია';
  homeBtn.classList.add('saved');
  _stagedLat = saved.lat;
  _stagedLng = saved.lng;
  _syncSaveBtn();
}

// ── Panel open / close ────────────────────────────────────────────────────────

homeBtn.addEventListener('click', () => {
  _syncSaveBtn();
  overlay.classList.add('open');
});
document.getElementById('home-close').addEventListener('click', () => {
  overlay.classList.remove('open');
  // Discard any staged GPS coords if user closed without saving
  const typed = addrInput.value.trim();
  if (typed === _savedAddress()) {
    _stagedLat = null;
    _stagedLng = null;
  }
});

// Re-evaluate save button whenever the user types
addrInput.addEventListener('input', () => {
  // If user edited away from staged GPS address, clear staged coords
  if (addrInput.value.trim() !== (_savedAddress() || '')) {
    if (addrInput.value.trim() !== (Home.get()?.address || '')) {
      _stagedLat = null;
      _stagedLng = null;
    }
  }
  _syncSaveBtn();
});

// ── Save button ───────────────────────────────────────────────────────────────

saveBtn.addEventListener('click', async () => {
  const addr = addrInput.value.trim();
  if (!addr || saveBtn.disabled) return;

  statusEl.textContent = 'შენახვა...';

  try {
    let saved;
    if (_stagedLat !== null && _stagedLng !== null) {
      // GPS coordinates already resolved — save directly
      saved = await Home.saveFromCoords(addr, _stagedLat, _stagedLng);
    } else {
      // Typed address — geocode it
      statusEl.textContent = 'გეოკოდირება...';
      saved = await Home.saveByAddress(addr);
    }

    addrInput.value      = saved.address;
    statusEl.textContent = '✓ შენახულია';
    homeBtn.classList.add('saved');
    _stagedLat = null;
    _stagedLng = null;
    _syncSaveBtn();
    setTimeout(() => overlay.classList.remove('open'), 600);
  } catch {
    statusEl.textContent = '⚠️ მისამართი ვერ მოიძებნა';
    _syncSaveBtn();
  }
});

// ── GPS button — FILL ONLY, no auto-save ─────────────────────────────────────

gpsBtn.addEventListener('click', async () => {
  statusEl.textContent = 'GPS-ის ლოდინი...';
  saveBtn.disabled = true;

  try {
    const pos = await getCurrentPosition();
    statusEl.textContent = 'მისამართის ძიება...';

    let displayAddr = `${pos.lat.toFixed(5)}, ${pos.lng.toFixed(5)}`;
    try {
      const data = await reverseGeocode(pos.lat, pos.lng);
      const road = data.address?.road || data.address?.suburb || '';
      const city = data.address?.city  || data.address?.town  || '';
      if (road)               displayAddr = road + (city ? ', ' + city : '');
      else if (data.display_name)
        displayAddr = data.display_name.split(',').slice(0, 2).join(',').trim();
    } catch { /* keep coordinate string */ }

    // Stage coords + fill input, but DO NOT persist yet
    _stagedLat = pos.lat;
    _stagedLng = pos.lng;
    addrInput.value      = displayAddr;
    statusEl.textContent = 'მისამართი ნაპოვნია. დააჭირეთ "შენახვა".';
    _syncSaveBtn();

  } catch {
    statusEl.textContent = '⚠️ GPS შეცდომა';
    _syncSaveBtn();
  }
});