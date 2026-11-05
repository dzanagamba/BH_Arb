// P3-4: cache only the static app shell. Never cache /api or odds: stale odds
// are dangerous, and a service worker must not become a second stale-feed layer.
const CACHE = 'bh-arb-shell-v2';
const SHELL = ['/', '/index.html', '/css/style.css', '/js/i18n.js', '/js/app.js', '/manifest.webmanifest'];

self.addEventListener('install', event => {
    event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)));
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
    );
    self.clients.claim();
});

self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);
    if (event.request.method !== 'GET' || url.pathname.startsWith('/api/')) {
        return; // network only: the scanner's truth is never served from cache
    }
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request).then(hit => hit || caches.match('/index.html')))
    );
});
