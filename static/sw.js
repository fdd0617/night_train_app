/**
 * 夜行列车推荐 — Service Worker
 *
 * 缓存策略：
 *   - 静态资源（/static/*）   ：cache-first，缺失时 fallback 网络
 *   - 文档 HTML（/）           ：network-first，离线 fallback 缓存
 *   - API（/api/*）            ：永不缓存（实时数据）
 */
const CACHE_NAME = 'ntr-static-v2';
const STATIC_ASSETS = [
  '/',
  '/static/app.css',
  '/static/app.js',
  '/static/icon.svg',
  '/static/manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
      .catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // API：永不缓存，绕过 SW
  if (url.pathname.startsWith('/api/')) return;

  // 静态资源：cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((cached) =>
        cached || fetch(request).then((res) => {
          // 仅对成功响应写入缓存
          if (res && res.status === 200) {
            const clone = res.clone();
            caches.open(CACHE_NAME).then((c) => c.put(request, clone));
          }
          return res;
        }).catch(() => cached)
      )
    );
    return;
  }

  // HTML：network-first，离线 fallback 缓存
  if (request.mode === 'navigate' || (request.headers.get('accept') || '').includes('text/html')) {
    event.respondWith(
      fetch(request)
        .then((res) => {
          if (res && res.status === 200) {
            const clone = res.clone();
            caches.open(CACHE_NAME).then((c) => c.put(request, clone));
          }
          return res;
        })
        .catch(() => caches.match(request).then((c) => c || caches.match('/')))
    );
  }
});
