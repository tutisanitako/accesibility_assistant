// sw.js — Service Worker
const CACHE_NAME = 'tbilisi-assistant-v1';

const ASSETS_TO_CACHE = [
  '/app/',
  '/app/index.html',
  '/app/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS_TO_CACHE))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then(names =>
      Promise.all(
        names.filter(n => n !== CACHE_NAME).map(n => caches.delete(n))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Never intercept backend API calls — always go straight to network
  if (event.request.url.includes('127.0.0.1:8001')) return;
  if (event.request.url.includes('localhost:8001')) return;
  if (event.request.url.includes('ngrok-free.dev')) return;
  if (event.request.url.includes('ngrok-free.app')) return;

  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;
      return fetch(event.request).then(response => {
        return caches.open(CACHE_NAME).then(cache => {
          cache.put(event.request, response.clone());
          return response;
        });
      }).catch(() => caches.match('/index.html'));
    })
  );
});