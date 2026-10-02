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
    if (d.locked) say("IP BLOQUEADO. TENTE EM " + Math.ceil(d.locked / 60) + " MIN.", "crit");
  }).catch(function () {});

  f.addEventListener("submit", function (e) {
    e.preventDefault();
    go.disabled = true;
    say("VERIFICANDO CREDENCIAIS...");
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
        say("ACESSO CONCEDIDO.", "ok");
        try { sessionStorage.setItem("vmp_boot", "1"); } catch (_) {}
        location.href = "/";
        return;
      }
      document.getElementById("p").value = "";
      document.getElementById("t").value = "";
      if (res.s === 429) say("ACESSO NEGADO. IP BLOQUEADO POR " + Math.ceil((res.d.retry || 900) / 60) + " MIN.", "crit");
      else say("ACESSO NEGADO.", "crit");
      go.disabled = false;
    }).catch(function () { say("ERRO DE CONEXAO.", "crit"); go.disabled = false; });
  });

  try {
    var th = localStorage.getItem("vmp_theme");
    if (th) document.documentElement.setAttribute("data-theme", th);
  } catch (_) {}
})();
