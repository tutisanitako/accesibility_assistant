/**
 * frontend/js/gps.js
 *
 * GPS / geolocation utilities.
 */

let _lastPosition = null;

/** Start watching position in background. Call once at app init. */
export function startWatching() {
  if (!navigator.geolocation) return;
  navigator.geolocation.watchPosition(
    pos => { _lastPosition = { lat: pos.coords.latitude, lng: pos.coords.longitude }; },
    () => {},
    { enableHighAccuracy: false, timeout: 10_000, maximumAge: 60_000 },
  );
}

/** Return the most recent cached position, or null. */
export function getLastPosition() {
  return _lastPosition;
}

/**
 * Get a fresh GPS fix. Resolves to { lat, lng } or rejects.
 */
export function getCurrentPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error('GPS მიუწვდომელია'));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      pos => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      err => reject(err),
    );
  });
}