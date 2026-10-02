/* VM//PANEL - service worker do app (PWA).
 * Rede primeiro para tudo; o cache so serve para abrir o app sem internet.
 * A API nunca e guardada: dados da VM sao sempre ao vivo. */
var CACHE = "vmpanel-v3";
var SHELL = ["/static/style.css", "/static/app.js", "/static/pwa.js", "/static/login.js", "/static/offline.html",
             "/static/sprite.svg", "/static/icons/icon-192.png"];

self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(SHELL); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener("fetch", function (e) {
  var req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.indexOf("/api/") === 0 || url.pathname === "/sw.js") return;
  if (req.mode === "navigate") {
    // paginas: sempre da rede (login/sessao); sem rede, tela de "sem sinal"
    e.respondWith(fetch(req).catch(function () { return caches.match("/static/offline.html"); }));
    return;
  }
  if (url.pathname.indexOf("/static/") !== 0) return;
  e.respondWith(fetch(req).then(function (res) {
    if (res.ok) { var copy = res.clone(); caches.open(CACHE).then(function (c) { c.put(req, copy); }); }
    return res;
  }).catch(function () { return caches.match(req); }));
});
