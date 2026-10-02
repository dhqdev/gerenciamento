(function () {
  "use strict";
  var f = document.getElementById("f");
  var msg = document.getElementById("msg");
  var go = document.getElementById("go");

  function say(t, cls) { msg.textContent = t; msg.className = "msg " + (cls || ""); }

  fetch("/api/login-info").then(function (r) { return r.json(); }).then(function (d) {
    if (d.totp) {
      document.getElementById("totp-row").classList.remove("hidden");
      document.getElementById("t").required = true;
    }
    if (d.locked) say("IP bloqueado. Tente em " + Math.ceil(d.locked / 60) + " min.", "crit");
  }).catch(function () {});

  f.addEventListener("submit", function (e) {
    e.preventDefault();
    go.disabled = true;
    say("Carregando...");
    fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-VMPanel": "1" },
      body: JSON.stringify({
        username: document.getElementById("u").value,
        password: document.getElementById("p").value,
        totp: document.getElementById("t").value
      })
    }).then(function (r) {
      return r.json().then(function (d) { return { s: r.status, d: d }; });
    }).then(function (res) {
      if (res.s === 200) {
        say("Bem-vindo, player 1!", "ok");
        try { sessionStorage.setItem("vmp_boot", "1"); } catch (_) {}
        location.href = "/";
        return;
      }
      document.getElementById("p").value = "";
      document.getElementById("t").value = "";
      if (res.s === 429) say("GAME OVER: IP bloqueado por " + Math.ceil((res.d.retry || 900) / 60) + " min.", "crit");
      else say("Usuario, senha ou codigo incorretos.", "crit");
      go.disabled = false;
    }).catch(function () { say("Erro de conexao.", "crit"); go.disabled = false; });
  });

  try {
    var th = localStorage.getItem("vmp_theme");
    if (th) document.documentElement.setAttribute("data-theme", th);
  } catch (_) {}
})();
