const CACHE = 'personofinterest-android-lite-v1';
const SHELL = ['/', '/styles.css', '/lite.css', '/lite.js', '/manifest.webmanifest', '/icon.svg'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key.startsWith('personofinterest-') && key !== CACHE).map((key) => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || !SHELL.includes(url.pathname)) return;
  event.respondWith((async () => {
    try { return await fetch(event.request); }
    catch (error) {
      const cache = await caches.open(CACHE);
      const fallback = await cache.match(url.pathname);
      if (fallback) return fallback;
      throw error;
    }
  })());
});
