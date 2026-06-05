/**
 * frontend/js/app.js
 * Entry point. Wires all modules together.
 */

import * as API     from './api.js';
import * as GPS     from './gps.js';
import * as Chat    from './chat.js';
import * as Ctx     from './context.js';
import * as History from './history.js';
import * as Home    from './home.js';
import { init as initHomeUI, refreshSavedDisplay } from './homeUI.js';
import './historyUI.js';

// ── Init ──────────────────────────────────────────────────────────────────────
GPS.startWatching();
initHomeUI();

if ('serviceWorker' in navigator)
  navigator.serviceWorker.register('sw.js').catch(() => {});

const offEl = document.getElementById('offline');
function checkOnline() { offEl.classList.toggle('show', !navigator.onLine); }
window.addEventListener('online',  checkOnline);
window.addEventListener('offline', checkOnline);
checkOnline();

Chat.addBotMsg('გამარჯობა! მე ვარ თქვენი ასისტენტი.\nმითხარით, რით შემიძლია დაგეხმარო?');

// ── Last bot response (for repeat) ────────────────────────────────────────────
let _lastDisplay = '';
let _lastSpeech  = '';

// ── Active audio — stopped when mic starts ────────────────────────────────────
let _currentAudio = null;

function _stopAudio() {
  if (_currentAudio) {
    try { _currentAudio.pause(); _currentAudio.currentTime = 0; } catch {}
    _currentAudio = null;
  }
  document.querySelectorAll('audio.inline-audio').forEach(a => {
    try { a.pause(); } catch {}
  });
}

// ── Recording ─────────────────────────────────────────────────────────────────
const micBtn   = document.getElementById('big-mic-btn');
const micLabel = document.getElementById('mic-label');
let mediaRec, chunks = [], recording = false;

micBtn.addEventListener('click',   toggle);
micBtn.addEventListener('keydown', e => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
});

async function toggle() { recording ? stopRec() : await startRec(); }

async function startRec() {
  _stopAudio();
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRec = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
    chunks = [];
    mediaRec.ondataavailable = e => chunks.push(e.data);
    mediaRec.onstop = _processAudio;
    mediaRec.start();
    recording = true;
    micBtn.classList.add('recording');
    micBtn.setAttribute('aria-pressed', 'true');
    micLabel.textContent = 'მოუსმინეთ...';
    micLabel.classList.add('recording-text');
    History.resetActive();
  } catch {
    micLabel.textContent = 'მიკროფონი მიუწვდომელია';
  }
}

function stopRec() {
  mediaRec.stop();
  mediaRec.stream.getTracks().forEach(t => t.stop());
  recording = false;
  micBtn.classList.remove('recording');
  micBtn.setAttribute('aria-pressed', 'false');
  micLabel.textContent = 'დამუშავება...';
  micLabel.classList.remove('recording-text');
}

async function _processAudio() {
  const blob = new Blob(chunks, { type: 'audio/webm' });
  try {
    micLabel.textContent = 'ამოიცნობს...';
    const result = await API.transcribe(blob);
    const said = (result.text || '').trim();
    if (!said) { _setLabel('ვერ გავიგე, სცადეთ თავიდან', 2500); return; }
    await runQuery(said);
  } catch (e) {
    _setLabel('შეცდომა', 2500);
    console.error('STT error:', e);
  }
}

function _setLabel(text, timeout) {
  micLabel.textContent = text;
  if (timeout) setTimeout(() => _resetLabel(), timeout);
}
function _resetLabel() {
  micLabel.textContent = 'დააჭირეთ და ისაუბრეთ';
  micLabel.classList.remove('recording-text');
}

// ── Main query pipeline ───────────────────────────────────────────────────────
export async function runQuery(text) {
  const enriched = Ctx.enrich(text, Home.get());

  Chat.addUserMsg(text);
  History.startConversation(text);
  History.addMessage('user', text);
  micLabel.textContent = 'ეძებს...';
  const tid = Chat.addTyping();

  try {
    const gps  = GPS.getLastPosition();
    const home = Home.get();
    const extra = {};
    if (gps)       { extra.lat = gps.lat;  extra.lng = gps.lng; }
    if (home?.lat) { extra.home_lat = home.lat; extra.home_lng = home.lng; }
    const lastDate = Ctx.getLastDate();
    if (lastDate) extra.context_date = lastDate;

    const data = await API.query(enriched, extra);
    Chat.removeTyping(tid);
    _resetLabel();

    // ── repeat ──────────────────────────────────────────────────────────────
    if (data.intent === 'repeat') {
      if (_lastDisplay) {
        Chat.addBotMsg(_lastDisplay);
        History.addMessage('assistant', _lastDisplay);
        await _speak(_lastSpeech || _lastDisplay);
      } else {
        Chat.addBotMsg('გასამეორებელი პასუხი არ მოიძებნა.');
      }
      return;
    }

    // ── save_home_location ──────────────────────────────────────────────────
    if (data.intent === 'save_home_location') {
      const coords = data.results?.[0];
      let saved;
      if (coords?.lat) {
        saved = await Home.saveFromCoords(coords.address, coords.lat, coords.lng);
      } else if (gps) {
        saved = await Home.saveByGPS();
      }
      // Update the home panel UI to show the new address
      if (saved) refreshSavedDisplay(saved);
      const msg = 'სახლის მისამართი შეინახა.';
      Chat.addBotMsg(msg);
      History.addMessage('assistant', msg);
      _lastDisplay = msg; _lastSpeech = msg;
      await _speak(msg);
      return;
    }

    if (data.intent === 'home_route')   { await doHomeRoute(); return; }

    // ── nearest_stop ────────────────────────────────────────────────────────
    if (data.intent === 'nearest_stop') {
      const stopsOnly = data.results?.[0]?.stops_only === true;
      await gpsNearest(stopsOnly);
      return;
    }

    const display = (data.response_text || '').trim();
    const speech  = (data.tts_text || data.response_text || '').trim();
    _lastDisplay = display;
    _lastSpeech  = speech;
    Chat.addBotMsg(display);
    History.addMessage('assistant', display);
    Ctx.update(text, display, data);
    await _speak(speech);

  } catch (e) {
    Chat.removeTyping(tid);
    _resetLabel();
    Chat.addBotMsg('შეცდომა. გთხოვთ სცადოთ თავიდან.');
    console.error('Query error:', e);
  }
}

// ── Home route ────────────────────────────────────────────────────────────────
async function doHomeRoute() {
  const home = Home.get();
  if (!home) {
    Chat.addBotMsg('სახლის მისამართი არ არის შენახული. დააჭირეთ "სახლი" ღილაკს.');
    return;
  }
  const tid = Chat.addTyping();
  const _go = async (curLat, curLng) => {
    try {
      const data = await API.homeRoute({
        current_lat: curLat, current_lng: curLng,
        home_lat: home.lat,  home_lng:    home.lng,
      });
      Chat.removeTyping(tid);
      _resetLabel();
      if (data.needs_geocoding) {
        const msg = 'GPS ფუნქცია ჯერ კონფიგურირებული არ არის.';
        Chat.addBotMsg(msg); History.addMessage('assistant', msg);
        _lastDisplay = msg; _lastSpeech = msg;
        await _speak(msg); return;
      }
      const display = (data.response_text || '').trim();
      const speech  = (data.tts_text || data.response_text || '').trim();
      _lastDisplay = display; _lastSpeech = speech;
      Chat.addBotMsg(display); History.addMessage('assistant', display);
      await _speak(speech);
    } catch (e) {
      Chat.removeTyping(tid); _resetLabel();
      Chat.addBotMsg('შეცდომა'); console.error(e);
    }
  };
  try {
    const pos = await GPS.getCurrentPosition();
    await _go(pos.lat, pos.lng);
  } catch {
    await _go(home.lat, home.lng);
  }
}

// ── GPS nearest ───────────────────────────────────────────────────────────────
async function gpsNearest(stopsOnly = false) {
  // Don't re-add user message — the original query already shows in chat
  const tid = Chat.addTyping();
  try {
    const pos  = await GPS.getCurrentPosition();
    const data = await API.nearestStopText(pos.lat, pos.lng, 6, stopsOnly);
    Chat.removeTyping(tid);
    _resetLabel();
    const display = (data.response_text || 'ახლომდებარე გაჩერება ვერ მოიძებნა.').trim();
    const speech  = (data.tts_text || display).trim();
    _lastDisplay = display; _lastSpeech = speech;
    Chat.addBotMsg(display); History.addMessage('assistant', display);
    await _speak(speech);
  } catch (e) {
    Chat.removeTyping(tid); _resetLabel();
    Chat.addBotMsg('GPS შეცდომა.'); console.error(e);
  }
}

// ── TTS ───────────────────────────────────────────────────────────────────────
async function _speak(text) {
  try {
    const blob = await API.synthesize(text);
    Chat.attachAudio(blob, au => { _currentAudio = au; });
  } catch (e) { console.warn('TTS:', e); }
}

// ── Text input ────────────────────────────────────────────────────────────────
const textInput = document.getElementById('text-input');
const textSend  = document.getElementById('text-send');
textSend.addEventListener('click', _sendText);
textInput.addEventListener('keydown', e => { if (e.key === 'Enter') _sendText(); });
function _sendText() {
  const t = textInput.value.trim();
  if (t) { runQuery(t); textInput.value = ''; }
}

// ── Quick actions ─────────────────────────────────────────────────────────────
window.processText = text => runQuery(text);
window.gpsNearest  = () => gpsNearest(false);