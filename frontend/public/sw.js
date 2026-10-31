// Service worker for the till. Two jobs: open the app when the shop's internet
// or the LAN link drops, and stop re-downloading the bundle and product photos
// on every launch. It deliberately never touches /api/ - stock, prices and
// payment state have one source of truth and a cached answer there would let a
// cashier sell stock that is already gone.
const SHELL = 'duka-shell-v1'
const ASSETS = 'duka-assets-v1'
const MEDIA = 'duka-media-v1'
const CACHES = [SHELL, ASSETS, MEDIA]
const INDEX = '/index.html'

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      // 'reload' so an install during a visit stores the shell being deployed
      // now, not one the browser still holds from this morning.
      .open(SHELL)
      .then((cache) => cache.add(new Request(INDEX, { cache: 'reload' })))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => !CACHES.includes(key)).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/')) return

  if (request.mode === 'navigate') {
    event.respondWith(fromShell(request))
    return
  }
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(cacheFirst(request, ASSETS))
    return
  }
  if (url.pathname.startsWith('/media/') || url.pathname.startsWith('/icons/')) {
    event.respondWith(refreshInBackground(request, MEDIA, event))
  }
})

// Network first: a fresh build changes index.html, and serving the old shell
// would keep loading the old bundles it points at. The cache is the fallback
// that lets the app open with no connection at all.
async function fromShell(request) {
  try {
    const response = await fetch(request, { cache: 'no-store' })
    const cache = await caches.open(SHELL)
    cache.put(INDEX, response.clone())
    return response
  } catch {
    const cached = await caches.match(INDEX)
    if (cached) return cached
    return offlinePage()
  }
}

// Content-hashed filenames never change without the name changing, so the
// cached copy is always the right copy.
async function cacheFirst(request, cacheName) {
  const hit = await caches.match(request)
  if (hit) return hit
  const response = await fetch(request)
  if (response.ok) {
    const cache = await caches.open(cacheName)
    cache.put(request, response.clone())
  }
  return response
}

// Show the photo already cached immediately, then quietly fetch the current one
// so a re-uploaded image appears on the next look rather than after the cache is
// cleared. A miss waits for the network, and serves the offline page only if
// even that fails.
async function refreshInBackground(request, cacheName, event) {
  const hit = await caches.match(request)
  const refresh = fetch(request)
    .then(async (response) => {
      if (response.ok) {
        const cache = await caches.open(cacheName)
        await cache.put(request, response.clone())
      }
      return response
    })
    .catch(() => null)

  if (hit) {
    event.waitUntil(refresh.then(() => {}))
    return hit
  }
  const fresh = await refresh
  if (fresh) return fresh
  return new Response('Not cached and the server is unreachable.', { status: 504 })
}

function offlinePage() {
  return new Response(
    '<!doctype html><html><head><meta charset="utf-8"><title>Offline</title>' +
      '<meta name="viewport" content="width=device-width, initial-scale=1">' +
      '</head><body style="font-family:system-ui;padding:3rem;background:#f6f7f9;color:#252b34">' +
      '<h1 style="font-size:1.25rem">The shop app cannot be reached</h1>' +
      '<p>This device has no saved copy of the app yet. Connect to the shop network once ' +
      'and open the till again, and it will work offline from then on.</p>' +
      '</body></html>',
    { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } },
  )
}
