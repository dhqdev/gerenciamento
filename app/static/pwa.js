/* VM//PANEL - registra o app (PWA) e guarda o convite de instalacao */
(function () {
  "use strict";
  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", function () { navigator.serviceWorker.register("/sw.js").catch(function () {}); });
  }
  window.vmpInstall = null;
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    window.vmpInstall = e;
    document.dispatchEvent(new Event("vmp-installable"));
  });
  window.addEventListener("appinstalled", function () { window.vmpInstall = null; });
})();
