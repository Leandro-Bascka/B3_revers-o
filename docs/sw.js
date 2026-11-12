/* Service worker: o app abre offline; data.json sempre tenta a rede primeiro. */
const VERSAO = "b3rev-v3";
const SHELL = ["./", "index.html", "style.css", "app.js", "chart.js", "manifest.webmanifest", "icon.svg", "icon-192.png", "icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSAO).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== VERSAO).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.endsWith("/data.json")) {
    e.respondWith(
      fetch(req).then((r) => { const cp = r.clone(); caches.open(VERSAO).then((c) => c.put("data.json", cp)); return r; })
        .catch(() => caches.match("data.json"))
    );
    return;
  }
  // arquivos do app: devolve o cache e atualiza em segundo plano
  e.respondWith(
    caches.match(req, { ignoreSearch: true }).then((hit) => {
      const rede = fetch(req).then((r) => { if (r.ok) { const cp = r.clone(); caches.open(VERSAO).then((c) => c.put(req, cp)); } return r; }).catch(() => hit);
      return hit || rede;
    })
  );
});
