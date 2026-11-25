const CACHE_NAME = 'ione-mobile-v1'
const urlsToCache = [
  '/ione-mobile',
  '/assets/tongjianyun/mobile/manifest.webmanifest',
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(urlsToCache))
  )
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n))
      )
    )
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  if (event.request.url.includes('/api/')) {
    return
  }

  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone()
            caches.open(CACHE_NAME).then((cache) => cache.put('/ione-mobile', clone))
          }
          return response
        })
        .catch(() => caches.match('/ione-mobile'))
    )
    return
  }

  event.respondWith(
    caches.match(event.request).then((response) => {
      return response || fetch(event.request).then((fetchResponse) => {
        if (fetchResponse.ok) {
          const clone = fetchResponse.clone()
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone))
        }
        return fetchResponse
      })
    })
  )
})
