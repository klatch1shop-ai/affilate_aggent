// Офлайн-оболонка. Версію піднімати при зміні будь-якого файлу зі списку,
// інакше браузер віддасть старе з кешу.
const V = 'mp-panel-v3';
const SHELL = [
  './', './index.html', './app.css', './app.js', './data.json',
  './commands.json', './manifest.webmanifest'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Сіть спершу, кеш як запас: дані оновлюються частіше за оболонку.
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request)
      .then(r => {
        const copy = r.clone();
        caches.open(V).then(c => c.put(e.request, copy)).catch(() => {});
        return r;
      })
      .catch(() => caches.match(e.request).then(r => r || caches.match('./index.html')))
  );
});
