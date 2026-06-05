/**
 * frontend/js/history.js
 *
 * Conversation history persisted in localStorage.
 * Keys / schema are intentionally private; use the exported functions.
 */

const STORAGE_KEY = 'tbilisi_convos2';
const MAX_AGE_MS  = 30 * 24 * 60 * 60 * 1000; // 30 days

// ── Low-level storage ─────────────────────────────────────────────────────────

function _load() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
  } catch {
    return [];
  }
}

function _save(convos) {
  const cutoff = Date.now() - MAX_AGE_MS;
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(convos.filter(c => new Date(c.startedAt).getTime() >= cutoff)),
    );
  } catch {
    // storage full — silently ignore
  }
}

// ── Conversation lifecycle ────────────────────────────────────────────────────

let _activeId = null;

/** Start a new conversation. Call with the first user message text. */
export function startConversation(firstText) {
  if (_activeId) return; // already started
  const id    = Date.now().toString();
  _activeId   = id;
  const title = firstText.length > 70 ? firstText.slice(0, 67) + '…' : firstText;
  const convos = _load();
  convos.unshift({ id, title, startedAt: new Date().toISOString(), messages: [] });
  _save(convos);
}

/** Append one message to the active conversation. */
export function addMessage(role, text) {
  if (!_activeId) return;
  const convos = _load();
  const conv   = convos.find(c => c.id === _activeId);
  if (!conv) return;
  conv.messages.push({ role, text, ts: new Date().toISOString() });
  _save(convos);
}

/** Reset for next conversation (called when a new mic press starts a new session). */
export function resetActive() {
  _activeId = null;
}

// ── Query interface ───────────────────────────────────────────────────────────

/** Return all saved conversations, newest first. */
export function getAll() {
  return _load();
}

/** Delete one conversation by id. */
export function deleteConversation(id) {
  _save(_load().filter(c => c.id !== id));
}

/** Delete all conversations. */
export function clearAll() {
  localStorage.removeItem(STORAGE_KEY);
}

/** Guess an intent tag from the first user message text. */
export function guessTag(text) {
  const t = (text || '').toLowerCase();
  if (/ავტობუს|მარშრუტ|გაჩერებ|სახლ|მივიდ|წამიყვანე/.test(t))
    return { label: 'ტრანსპორტი',   color: '#2563eb' };
  if (/სპექტაკლ|თეატრ|ოპერ|კონცერტ|ღონისძიებ/.test(t))
    return { label: 'ღონისძიებები', color: '#7c3aed' };
  return   { label: 'სხვა კითხვები', color: '#6C7AA0' };
}