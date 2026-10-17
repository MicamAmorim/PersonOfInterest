const CACHE = 'personofinterest-v4.1.0';
const SHELL = ['/', '/styles.css', '/v2.css', '/v34.css', '/app-core.js', '/app-runtime.js', '/v34.js', '/v4-stream-fix.js', '/v4-audio-fix.js', '/camera-webrtc.html', '/manifest.webmanifest', '/icon.svg'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET' || event.request.url.includes('/api/') || event.request.url.includes('/go2rtc/')) return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const clone = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, clone));
        return response;
      })
      .catch(() => caches.match(event.request).then((cached) => cached || caches.match('/')))
  );
});

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; }
  catch (_) { data = { body: event.data ? event.data.text() : 'Novo alerta' }; }
  const title = data.title || 'PersonOfInterest';
  const options = {
    body: data.body || 'Novo evento detectado.',
    icon: '/icon.svg',
    badge: '/icon.svg',
    tag: data.tag || `poi-${Date.now()}`,
    renotify: true,
    data: { url: data.url || '/', event_id: data.event_id || null },
  };
  if (data.image) options.image = data.image;
  event.waitUntil(Promise.all([
    self.registration.showNotification(title, options),
    self.navigator?.setAppBadge ? self.navigator.setAppBadge() : Promise.resolve(),
  ]));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || '/', self.location.origin).href;
  event.waitUntil((async () => {
    const windows = await clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of windows) {
      if ('focus' in client) {
        try { await client.navigate(target); } catch (_) {}
        await client.focus();
        return;
      }
    }
    if (clients.openWindow) await clients.openWindow(target);
  })());
});
