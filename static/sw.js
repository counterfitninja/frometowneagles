// Service Worker for offline functionality
const CACHE_NAME = 'football-manager-availability-20261005';
const urlsToCache = [
    '/static/manifest.json',
    '/static/design-language.css?v=20260818-rounded',
    '/static/live-match.css?v=20261004',
    '/static/match-result.js?v=20261004',
    '/static/icon-192.svg',
    '/static/icon-512.svg',
    '/static/logo.jpg'
];

// Install service worker and cache resources
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => {
                console.log('Opened cache');
                return cache.addAll(urlsToCache.map(url => {
                    return new Request(url, { credentials: 'same-origin' });
                })).catch(err => {
                    console.log('Cache addAll error:', err);
                });
            })
    );
    self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
    // Skip cross-origin requests
    if (!event.request.url.startsWith(self.location.origin)) {
        return;
    }

    // Let result uploads reach Flask directly; only GET requests are cacheable.
    if (event.request.method !== 'GET') {
        return;
    }

    const path = new URL(event.request.url).pathname;
    if (path.startsWith('/api/') || path.startsWith('/team-generator') ||
        path.startsWith('/public/players/') ||
        path === '/login' || path === '/logout') return;

    event.respondWith((async () => {
        const cached = await caches.match(event.request);
        const navigation = event.request.mode === 'navigate';
        if (cached && !navigation) return cached;
        try {
            // Match pages must load fresh server results when connected.
            const response = await fetch(event.request.clone());
            if (response.status === 200 && response.type === 'basic' && !response.redirected) {
                const responseToCache = response.clone();
                event.waitUntil(
                    caches.open(CACHE_NAME)
                        .then(cache => cache.put(event.request, responseToCache))
                        .catch(error => console.error('Cannot cache this page for offline use', error))
                );
            }
            return response;
        } catch (error) {
            if (cached) return cached;
            if (!navigation) return Response.error();
            return new Response(
                '<!doctype html><html lang="en"><meta name="viewport" content="width=device-width, initial-scale=1">' +
                '<title>Page unavailable offline</title><h1>Page unavailable offline</h1>' +
                '<p>Reconnect to open this page. Previously opened match screens are available offline.</p>' +
                '<a href="/matches">Back to matches</a></html>',
                { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
            );
        }
    })());
});

// Clean up old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName !== CACHE_NAME) {
                        console.log('Deleting old cache:', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
    self.clients.claim();
});
