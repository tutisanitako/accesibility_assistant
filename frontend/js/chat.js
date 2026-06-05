/**
 * frontend/js/chat.js
 * Chat UI — building and inserting DOM elements.
 * Knows nothing about API calls or business logic.
 */

const convoEl = document.getElementById('convo');

function _nowTime() {
  const d = new Date();
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
}
function _esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function _scroll() {
  setTimeout(() => { convoEl.scrollTop = convoEl.scrollHeight; }, 50);
}

const _BOT_AV = `
  <div class="bot-av">
    <svg viewBox="0 0 24 24" fill="white">
      <path d="M12 1a4 4 0 0 1 4 4v6a4 4 0 0 1-8 0V5a4 4 0 0 1 4-4zm-1
               16.93A8.001 8.001 0 0 1 4 11H2a10 10 0 0 0 9 9.95V23h2v-2.05A10
               10 0 0 0 22 11h-2a8.001 8.001 0 0 1-7 6.93z"/>
    </svg>
  </div>`;
const _USER_AV = `
  <div class="user-av">
    <svg viewBox="0 0 24 24" fill="none" stroke="#032D8F" stroke-width="2">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
      <circle cx="12" cy="7" r="4"/>
    </svg>
  </div>`;

export function addUserMsg(text) {
  const row = document.createElement('div');
  row.className = 'msg-row user';
  row.innerHTML = `
    ${_USER_AV}
    <div class="bwrap">
      <div class="bubble">${_esc(text)}</div>
      <div class="msg-time">${_nowTime()}</div>
    </div>`;
  convoEl.appendChild(row);
  _scroll();
}

export function addBotMsg(text) {
  const row   = document.createElement('div');
  row.className = 'msg-row bot';
  const bwrap = document.createElement('div');
  bwrap.className = 'bwrap';
  const bub   = document.createElement('div');
  bub.className = 'bubble';
  bub.textContent = text;
  const time  = document.createElement('div');
  time.className = 'msg-time';
  time.textContent = _nowTime();
  bwrap.append(bub, time);
  row.innerHTML = _BOT_AV;
  row.appendChild(bwrap);
  convoEl.appendChild(row);
  _scroll();
  return row;
}

/**
 * Attach an audio player to the most recent bot message.
 * @param {Blob} audioBlob
 * @param {function(HTMLAudioElement):void} [onElement]  called with the audio element
 *        so the caller can keep a reference to stop it later.
 */
export function attachAudio(audioBlob, onElement) {
  const rows = convoEl.querySelectorAll('.msg-row.bot');
  const last = rows[rows.length - 1];
  if (!last) return;

  const old = last.querySelector('audio.inline-audio');
  if (old) { URL.revokeObjectURL(old.src); old.remove(); }

  const url = URL.createObjectURL(audioBlob);
  const au  = document.createElement('audio');
  au.className = 'inline-audio';
  au.controls  = true;
  au.src       = url;
  au.setAttribute('playsinline', '');
  au.setAttribute('webkit-playsinline', '');

  const bwrap = last.querySelector('.bwrap');
  if (bwrap) bwrap.appendChild(au);

  // Expose element to caller so it can be stopped when mic starts
  if (typeof onElement === 'function') onElement(au);

  const tryPlay = async () => {
    try {
      await au.play();
    } catch {
      au.style.outline      = '2px solid var(--blue)';
      au.style.borderRadius = '8px';
      setTimeout(() => { au.style.outline = ''; au.style.borderRadius = ''; }, 2000);
    }
  };
  au.addEventListener('canplay', tryPlay, { once: true });
  if (au.readyState >= 3) tryPlay();
}

export function addTyping() {
  const id  = 'tp-' + Date.now();
  const row = document.createElement('div');
  row.className = 'msg-row bot';
  row.id = id;
  row.innerHTML = `
    ${_BOT_AV}
    <div class="bwrap">
      <div class="typing-bubble">
        <span class="tdot"></span>
        <span class="tdot"></span>
        <span class="tdot"></span>
      </div>
    </div>`;
  convoEl.appendChild(row);
  _scroll();
  return id;
}

export function removeTyping(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}