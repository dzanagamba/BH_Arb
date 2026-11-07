// P3-4: cache only the static app shell. Never cache /api or odds: stale odds
// are dangerous, and a service worker must not become a second stale-feed layer.
// The document asks for versioned assets (?v=7); cache those exact URLs and
// match with ignoreSearch so a version bump still resolves.
const CACHE = 'bh-arb-shell-v3';
const SHELL = ['/', '/css/style.css?v=7', '/js/i18n.js', '/js/app.js?v=7', '/manifest.webmanifest'];

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
        fetch(event.request).catch(() => caches.match(event.request, { ignoreSearch: true }).then(hit => {
            if (hit) return hit;
            // Only a navigation may become the HTML shell. A missing script,
            // stylesheet or font must fail as itself, never as HTML.
            if (event.request.mode === 'navigate') return caches.match('/');
            return Response.error();
        }))
    );
});
