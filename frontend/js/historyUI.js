/**
 * frontend/js/historyUI.js
 *
 * Renders the history list page and the conversation detail page.
 * Depends on history.js for data, touches DOM only.
 */

import * as History from './history.js';

// ── DOM refs ──────────────────────────────────────────────────────────────────

const histPage    = document.getElementById('history-page');
const histList    = document.getElementById('hist-list');
const hdetailPage = document.getElementById('hdetail-page');
const hdMsgs      = document.getElementById('hd-msgs');

let _currentDetailId = null;

// ── Open / close pages ────────────────────────────────────────────────────────

export function openHistoryPage() {
  renderList();
  histPage.classList.add('open');
}

export function closeHistoryPage() {
  histPage.classList.remove('open');
}

export function closeDetailPage() {
  hdetailPage.classList.remove('open');
  _currentDetailId = null;
}

// ── List rendering ────────────────────────────────────────────────────────────

function _formatWhen(dateStr) {
  const d   = new Date(dateStr);
  const now = new Date();
  const yest = new Date(now);
  yest.setDate(yest.getDate() - 1);
  const timePart = d.toLocaleTimeString('ka-GE', { hour: '2-digit', minute: '2-digit' });
  if (d.toDateString() === now.toDateString())  return `დღეს, ${timePart}`;
  if (d.toDateString() === yest.toDateString()) return `გუშინ, ${timePart}`;
  return d.toLocaleDateString('ka-GE', { day: '2-digit', month: 'long' }) + `, ${timePart}`;
}

function _esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _closeAllDropdowns(except = null) {
  document.querySelectorAll('.hist-menu-dropdown.open').forEach(d => {
    if (d !== except) d.classList.remove('open');
  });
}

export function renderList(filter = '') {
  histList.innerHTML = '';
  const convos = History.getAll();

  const visible = filter
    ? convos.filter(c => c.title.toLowerCase().includes(filter.toLowerCase()))
    : convos;

  if (!visible.length) {
    histList.innerHTML = '<div class="hist-empty">საუბრების ისტორია ცარიელია</div>';
    return;
  }

  visible.forEach(c => {
    const firstMsg = (c.messages.find(m => m.role === 'user') || {}).text || c.title;
    const tag      = History.guessTag(firstMsg);
    const when     = _formatWhen(c.startedAt);

    const item = document.createElement('div');
    item.className    = 'hist-item';
    item.dataset.title = c.title;
    item.innerHTML = `
      <div class="hist-item-left">
        <div class="hist-item-title">${_esc(c.title)}</div>
        <div class="hist-item-tag">
          <span class="tag-dot" style="background:${tag.color}"></span>
          ${tag.label}
        </div>
      </div>
      <div class="hist-item-right">
        <div class="hist-item-time">${when}</div>
        <button class="hist-item-menu" title="მენიუ">⋯</button>
      </div>`;

    // Dropdown
    const dropdown = document.createElement('div');
    dropdown.className = 'hist-menu-dropdown';
    dropdown.innerHTML = `
      <button class="hist-menu-action">გახსნა</button>
      <button class="hist-menu-action danger">წაშლა</button>`;
    item.appendChild(dropdown);

    // Open detail on row click
    item.addEventListener('click', e => {
      if (e.target.closest('.hist-item-menu, .hist-menu-action')) return;
      if (dropdown.classList.contains('open')) return;
      _openDetail(c);
    });

    // Three-dot button
    item.querySelector('.hist-item-menu').addEventListener('click', e => {
      e.stopPropagation();
      _closeAllDropdowns(dropdown);
      dropdown.classList.toggle('open');
    });

    // Open action
    dropdown.querySelectorAll('.hist-menu-action')[0].addEventListener('click', e => {
      e.stopPropagation();
      dropdown.classList.remove('open');
      _openDetail(c);
    });

    // Delete action
    dropdown.querySelectorAll('.hist-menu-action')[1].addEventListener('click', e => {
      e.stopPropagation();
      dropdown.classList.remove('open');
      if (confirm(`"${c.title}" — წაიშლება. დარწმუნებული ხართ?`)) {
        History.deleteConversation(c.id);
        renderList(filter);
      }
    });

    histList.appendChild(item);
  });
}

// ── Detail rendering ──────────────────────────────────────────────────────────

function _openDetail(convo) {
  _currentDetailId = convo.id;

  const firstMsg = (convo.messages.find(m => m.role === 'user') || {}).text || convo.title;
  const tag  = History.guessTag(firstMsg);
  const d    = new Date(convo.startedAt);
  const now  = new Date();
  const timePart = d.toLocaleTimeString('ka-GE', { hour: '2-digit', minute: '2-digit' });
  const when = d.toDateString() === now.toDateString()
    ? `დღეს, ${timePart}`
    : d.toLocaleDateString('ka-GE', { day: '2-digit', month: 'long' }) + `, ${timePart}`;

  document.getElementById('hd-title').textContent       = convo.title;
  document.getElementById('hd-tag-dot').style.background = tag.color;
  document.getElementById('hd-tag-lbl').textContent     = tag.label;
  document.getElementById('hd-topbar-time').textContent = when;
  document.getElementById('hd-footer-val').textContent  =
    d.toLocaleDateString('ka-GE', { day: 'numeric', month: 'long', year: 'numeric' }) +
    ' • ' + timePart;

  // Messages
  hdMsgs.innerHTML = '';
  (convo.messages || []).forEach(m => {
    const isUser = m.role === 'user';
    const ts     = new Date(m.ts).toLocaleTimeString('ka-GE', { hour: '2-digit', minute: '2-digit' });
    const avClass = isUser ? 'user' : 'bot';
    const avSvg   = isUser
      ? `<svg viewBox="0 0 24 24" fill="none" stroke="#032D8F" stroke-width="2" width="14" height="14">
           <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
           <circle cx="12" cy="7" r="4"/>
         </svg>`
      : `<svg viewBox="0 0 24 24" fill="white" width="12" height="12">
           <path d="M12 1a4 4 0 0 1 4 4v6a4 4 0 0 1-8 0V5a4 4 0 0 1 4-4zm-1
                    16.93A8.001 8.001 0 0 1 4 11H2a10 10 0 0 0 9 9.95V23h2v-2.05A10
                    10 0 0 0 22 11h-2a8.001 8.001 0 0 1-7 6.93z"/>
         </svg>`;
    const row = document.createElement('div');
    row.className = `hd-row ${isUser ? 'user' : 'bot'}`;
    row.innerHTML = `
      <div class="hd-av ${avClass}">${avSvg}</div>
      <div class="hd-bwrap">
        <div class="hd-bub">${_esc(m.text)}</div>
        <div class="hd-time">${ts}</div>
      </div>`;
    hdMsgs.appendChild(row);
  });

  closeHistoryPage();
  hdetailPage.classList.add('open');
  setTimeout(() => { hdMsgs.scrollTop = hdMsgs.scrollHeight; }, 50);
}

/** Delete the currently open detail conversation. */
export function deleteCurrentDetail() {
  if (!_currentDetailId) return;
  if (confirm('ეს საუბარი წაიშლება. დარწმუნებული ხართ?')) {
    History.deleteConversation(_currentDetailId);
    closeDetailPage();
    renderList();
    openHistoryPage();
  }
}

// ── Wire up static button handlers ───────────────────────────────────────────

document.getElementById('hist-open-btn').addEventListener('click', openHistoryPage);
document.getElementById('hist-back').addEventListener('click', closeHistoryPage);

document.getElementById('hist-clear').addEventListener('click', () => {
  if (confirm('ყველა საუბარი წაიშლება?')) {
    History.clearAll();
    renderList();
  }
});

document.getElementById('hist-search').addEventListener('input', function () {
  renderList(this.value);
});

document.getElementById('hdetail-back').addEventListener('click', () => {
  closeDetailPage();
  renderList();
  openHistoryPage();
});

// Three-dot menu in detail page
const hdMenuBtn      = document.getElementById('hd-menu-btn');
const hdMenuDropdown = document.getElementById('hd-menu-dropdown');
hdMenuBtn.addEventListener('click', e => {
  e.stopPropagation();
  hdMenuDropdown.classList.toggle('open');
});
document.getElementById('hd-delete-btn').addEventListener('click', () => {
  hdMenuDropdown.classList.remove('open');
  deleteCurrentDetail();
});
document.addEventListener('click', () => hdMenuDropdown.classList.remove('open'));