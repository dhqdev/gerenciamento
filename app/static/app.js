/* VM//PANEL v2 - frontend (JS puro; xterm.js carregado sob demanda para o terminal) */
(function () {
  "use strict";

  // ------------------------------------------------------------------ utilitarios
  var $ = function (id) { return document.getElementById(id); };

  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === "class") el.className = v;
        else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
        else if (k === "text") el.textContent = v;
        else el.setAttribute(k, v === true ? "" : v);
      });
    }
    add(el, Array.prototype.slice.call(arguments, 2));
    return el;
  }
  function add(el, kids) {
    kids.forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      if (Array.isArray(c)) return add(el, c);
      el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    });
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

  // icones 8x8 desenhados pixel a pixel (SVG, cor = currentColor)
  var ICONS = {
    dash: [".XX..XX.", "XXXXXXXX", "XXXXXXXX", "XXXXXXXX", ".XXXXXX.", "..XXXX..", "...XX...", "........"],
    docker: ["........", "XX.XX.XX", "XX.XX.XX", "........", "XXXXXXXX", "X......X", ".XXXXXX.", "........"],
    procs: ["XXXXXXX.", "........", "XXXXX...", "........", "XXXXXXXX", "........", "XXX.....", "........"],
    term: ["XXXXXXXX", "X......X", "X.X....X", "X..X...X", "X.X.XX.X", "X......X", "XXXXXXXX", "........"],
    more: ["........", "XXXXXXXX", "........", "XXXXXXXX", "........", "XXXXXXXX", "........", "........"],
    net: ["..X..X..", ".XXX.X..", "X.X..X..", "..X..X..", "..X..X.X", "..X.XXX.", "..X..X..", "........"],
    disks: [".XXXXXX.", "X......X", "XXXXXXXX", "X......X", "X....XXX", "X......X", ".XXXXXX.", "........"],
    system: [".X.X.X..", "XXXXXXX.", ".X...X..", "XX.X.XX.", ".X...X..", "XXXXXXX.", ".X.X.X..", "........"],
    security: ["XXXXXXXX", "X..XX..X", "X..XX..X", "XXXXXXXX", "X..XX..X", ".X.XX.X.", "..XXXX..", "...XX..."],
    history: ["X.......", "X.....X.", "X....XX.", "X.X..XX.", "X.XX.XX.", "X.XXXXX.", "XXXXXXXX", "........"],
    config: ["...XX...", ".XXXXXX.", ".XX..XX.", "XX....XX", "XX....XX", ".XX..XX.", ".XXXXXX.", "...XX..."],
    star: ["...X....", "...X....", "XXXXXXX.", ".XXXXX..", "..XXX...", ".XX.XX..", ".X...X..", "........"],
    power: ["...X....", ".X.X.X..", "X..X..X.", "X..X..X.", "X.....X.", ".X...X..", "..XXX...", "........"],
    install: ["...X....", "...X....", "...X....", ".XXXXX..", "..XXX...", "...X....", "X.....X.", "XXXXXXX."],
    refresh: ["..XXXX..", ".X....X.", "X.......", "X.....XX", "X....XX.", ".X....X.", "..XXXX..", "........"]
  };
  var SVGNS = "http://www.w3.org/2000/svg";
  function icon(name) {
    var svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("viewBox", "0 0 8 8"); svg.setAttribute("class", "ico"); svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("shape-rendering", "crispEdges");
    (ICONS[name] || ICONS.more).forEach(function (row, y) {
      for (var x = 0; x < row.length; x++) if (row[x] === "X") {
        var r = document.createElementNS(SVGNS, "rect");
        r.setAttribute("x", x); r.setAttribute("y", y); r.setAttribute("width", 1); r.setAttribute("height", 1);
        svg.appendChild(r);
      }
    });
    return svg;
  }
  var MOBILE = window.matchMedia("(max-width: 760px)");
  function buzz() { try { if (navigator.vibrate) navigator.vibrate(8); } catch (_) {} }

  var UNITS = ["B", "KB", "MB", "GB", "TB", "PB"];
  function bytes(n) {
    n = Number(n) || 0;
    var i = 0;
    while (n >= 1024 && i < UNITS.length - 1) { n /= 1024; i++; }
    return (i === 0 ? n.toFixed(0) : n.toFixed(n >= 100 ? 0 : 1)) + " " + UNITS[i];
  }
  function rate(n) { return bytes(n) + "/s"; }
  function pct(n) { return (Number(n) || 0).toFixed(1) + "%"; }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function dur(s) {
    s = Math.floor(s || 0);
    var d = Math.floor(s / 86400), hh = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
    return (d ? d + "d " : "") + hh + "h " + pad(m) + "m";
  }
  function when(ts) {
    var d = new Date(ts * 1000);
    return d.toLocaleDateString("pt-BR") + " " + d.toLocaleTimeString("pt-BR");
  }
  function level(p, w, c) { return p >= (c || 90) ? "crit" : p >= (w || 75) ? "warn" : "ok"; }

  // barra estilo HP: verde, amarela e vermelha conforme o uso
  function hp(p, opts) {
    opts = opts || {};
    p = Math.max(0, Math.min(100, Number(p) || 0));
    var fill = h("i");
    fill.style.width = p + "%";
    return h("div", { class: "hp " + (opts.sm ? "sm " : "") + level(p, opts.w, opts.c), title: pct(p) }, fill);
  }
  function stat(label, p, valText, opts) {
    return h("div", { class: "stat" }, h("span", { class: "label" }, label), hp(p, opts),
      h("span", { class: "val " + level(p, (opts || {}).w, (opts || {}).c) }, valText === undefined ? pct(p) : valText));
  }
  function box(title, cls) {
    var b = h("section", { class: "box " + (cls || "") }, h("h2", null, title));
    add(b, Array.prototype.slice.call(arguments, 2));
    return b;
  }
  function kv(pairs) {
    var d = h("div", { class: "kv" });
    pairs.forEach(function (p) { add(d, [h("span", null, p[0]), h("span", null, p[1] === undefined || p[1] === null || p[1] === "" ? "-" : p[1])]); });
    return d;
  }
  function table(cols, rows, opts) {
    opts = opts || {};
    var thead = h("tr", null, cols.map(function (c) {
      var th = h("th", { class: (c.num ? "num " : "") + (c.sort ? "sort " : "") + (c.m === "hide" ? "hide-m" : "") }, c.t);
      if (c.sort && opts.onSort) th.addEventListener("click", function () { opts.onSort(c.sort); });
      return th;
    }));
    rows.forEach(function (tr) {
      Array.prototype.forEach.call(tr.children, function (cell, i) {
        var c = cols[i];
        if (!c) return;
        cell.setAttribute("data-l", c.t);
        if (c.m === "hide") cell.classList.add("hide-m");
        if (c.m === "title") cell.classList.add("card-title");
      });
    });
    var body = rows.length ? rows : [h("tr", null, h("td", { colspan: cols.length, class: "muted" }, opts.empty || "Nada por aqui."))];
    return h("div", { class: "tbl-wrap" + (opts.cards ? " cards" : "") }, h("table", null, h("thead", null, thead), h("tbody", null, body)));
  }
  function td(v, cls, title) { return h("td", { class: cls || null, title: title || null }, v); }

  function toast(msg, err) {
    var t = h("div", { class: "toast" + (err ? " err" : "") }, msg);
    $("toasts").appendChild(t);
    setTimeout(function () { t.remove(); }, err ? 7000 : 3500);
  }

  function api(path) {
    return fetch(path, { credentials: "same-origin" }).then(function (r) {
      if (r.status === 401) { location.href = "/login"; throw new Error("401"); }
      return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || r.status); return d; });
    });
  }
  function post(path, body) {
    return fetch(path, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-VMPanel": "1" },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      if (r.status === 401 && path !== "/api/term/unlock") { location.href = "/login"; throw new Error("401"); }
      return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || (d.errors || []).join("; ") || r.status); return d; });
    });
  }

  // ------------------------------------------------------------------ preferencias
  var THEMES = [["16bit", "16-BIT (padrao)"], ["nes", "NES"], ["arcade", "ARCADE NEON"], ["gameboy", "GAME BOY"]];
  var prefs = { theme: "16bit", crt: false };
  try {
    var t = localStorage.getItem("vmp_theme2");
    if (THEMES.some(function (x) { return x[0] === t; })) prefs.theme = t;
    prefs.crt = localStorage.getItem("vmp_crt2") === "1";
  } catch (_) {}
  function savePref(k, v) { try { localStorage.setItem(k, v); } catch (_) {} }
  function applyPrefs() {
    document.documentElement.setAttribute("data-theme", prefs.theme);
    document.body.classList.toggle("crt", prefs.crt);
  }
  applyPrefs();
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  // ------------------------------------------------------------------ graficos pixelados
  function drawChart(canvas, series, opts) {
    if (!canvas) return;
    opts = opts || {};
    var w = canvas.clientWidth, hgt = canvas.clientHeight;
    if (!w || !hgt) return;
    var scale = 2;   // desenha em baixa resolucao e amplia = visual pixelado
    var W = Math.floor(w / scale), H = Math.floor(hgt / scale);
    canvas.width = W; canvas.height = H;
    var c = canvas.getContext("2d");
    c.imageSmoothingEnabled = false;
    c.fillStyle = css("--ink"); c.fillRect(0, 0, W, H);
    var max = opts.max || 0;
    series.forEach(function (s) { s.data.forEach(function (v) { if (v > max) max = v; }); });
    if (!max) max = 1;
    c.fillStyle = css("--panel-2");
    for (var i = 1; i < 4; i++) for (var x = 0; x < W; x += 4) c.fillRect(x, Math.round(H * i / 4), 2, 1);
    series.forEach(function (s, idx) {
      var d = s.data;
      if (!d.length) return;
      var color = s.color || (idx === 0 ? css("--ok-2") : css("--accent-2"));
      c.fillStyle = color;
      var n = d.length;
      for (var px = 0; px < W; px++) {
        var k = n === 1 ? 0 : Math.round(px / (W - 1) * (n - 1));
        var y = Math.round((H - 2) - (H - 4) * Math.min(d[k], max) / max);
        if (s.fill) { c.globalAlpha = .28; c.fillRect(px, y, 1, H - y); c.globalAlpha = 1; }
        c.fillRect(px, y, 1, s.dash && px % 4 > 1 ? 0 : 2);
      }
    });
    if (opts.axis) {
      c.fillStyle = css("--muted");
      c.font = "8px monospace";
      c.fillText((opts.fmt || String)(max), 2, 9);
      if (opts.labels && opts.labels.length) {
        c.fillText(opts.labels[0], 2, H - 3);
        var last = opts.labels[opts.labels.length - 1];
        c.fillText(last, W - c.measureText(last).width - 2, H - 3);
      }
    }
  }

  var live = { cpu: [], mem: [], rx: [], tx: [], rd: [], wr: [] };
  function pushLive(k, v) { live[k].push(v); if (live[k].length > 150) live[k].shift(); }

  // ------------------------------------------------------------------ navegacao
  var state = { me: null, procSort: "cpu", procQuery: "", dockerQuery: "", histRange: "24h", version: null };

  var TABS = [
    { id: "dash", key: "1", name: "STATUS", every: 3000 },
    { id: "docker", key: "2", name: "DOCKER", every: 5000 },
    { id: "procs", key: "3", name: "PROCESSOS", every: 3000 },
    { id: "net", key: "4", name: "REDE", every: 4000 },
    { id: "disks", key: "5", name: "DISCOS", every: 5000 },
    { id: "system", key: "6", name: "SISTEMA", every: 15000 },
    { id: "security", key: "7", name: "SEGURANCA", every: 30000 },
    { id: "history", key: "8", name: "HISTORICO", every: 60000 },
    { id: "term", key: "9", name: "TERMINAL", every: 0 },
    { id: "config", key: "0", name: "CONFIG", every: 0 }
  ];
  var current = null, timer = null, body = null;

  function show(id) {
    var tab = TABS.filter(function (t) { return t.id === id; })[0] || TABS[0];
    if (current && current.id === "term" && tab.id !== "term") closeTerminal();
    current = tab;
    try { history.replaceState(null, "", "#" + tab.id); } catch (_) {}
    Array.prototype.forEach.call($("tabs").children, function (b) { b.classList.toggle("on", b.dataset.id === tab.id); });
    Array.prototype.forEach.call($("bnav").children, function (b) {
      b.classList.toggle("on", b.dataset.id === tab.id || (b.dataset.id === "more" && BNAV.indexOf(tab.id) < 0));
    });
    document.body.setAttribute("data-tab", tab.id);
    window.scrollTo(0, 0);
    var view = clear($("view"));
    body = h("div");
    var setup = VIEWS[tab.id].setup;
    if (setup) view.appendChild(setup());
    view.appendChild(body);
    clearTimeout(timer);
    refresh();
  }
  function refresh() {
    var tab = current;
    clearTimeout(timer);
    var btn = $("btn-refresh");
    btn.disabled = true;
    return Promise.resolve(VIEWS[tab.id].load()).then(function (d) {
      if (tab !== current) return;
      var node = VIEWS[tab.id].render(d);
      clear(body).appendChild(node);
      if (VIEWS[tab.id].after) VIEWS[tab.id].after(d);
    }).catch(function (e) {
      if (tab !== current) return;
      clear(body).appendChild(box("ERRO", "", h("p", { class: "crit" }, String(e.message || e))));
    }).then(function () {
      btn.disabled = false;
      if (tab === current && tab.every && !document.hidden) timer = setTimeout(refresh, tab.every);
    });
  }
  document.addEventListener("visibilitychange", function () { if (!document.hidden && current && current.every) refresh(); });

  // ------------------------------------------------------------------ confirmacao (caixa de dialogo de RPG)
  function ask(title, text, okLabel, danger) {
    return new Promise(function (resolve) {
      var root = h("div", { class: "modal confirm", role: "alertdialog", "aria-modal": "true" });
      function done(v) { root.remove(); document.removeEventListener("keydown", key, true); resolve(v); }
      function key(e) { if (e.key === "Escape") { e.stopPropagation(); done(false); } }
      var yes = h("button", { class: "btn " + (danger ? "danger" : "gold"), onclick: function () { buzz(); done(true); } }, "▶ " + (okLabel || "SIM"));
      add(root, [h("div", { class: "box sheet" }, h("h2", null, title), h("p", null, text),
        h("div", { class: "toolbar choice" }, yes, h("button", { class: "btn", onclick: function () { done(false); } }, "CANCELAR")))]);
      root.addEventListener("click", function (e) { if (e.target === root) done(false); });
      document.addEventListener("keydown", key, true);
      document.body.appendChild(root);
      setTimeout(function () { yes.focus(); }, 30);
    });
  }

  // ------------------------------------------------------------------ docker: acoes e janelas
  function dockerAct(name, act, label) {
    var go = act === "stop" || act === "restart"
      ? ask(act === "stop" ? "PARAR CONTAINER?" : "REINICIAR CONTAINER?", (label || name) + (act === "stop" ? " vai parar de rodar." : " vai reiniciar agora."),
            act === "stop" ? "PARAR" : "REINICIAR", act === "stop")
      : Promise.resolve(true);
    return go.then(function (ok) {
      if (!ok) return;
      toast("Enviando " + act + " para " + (label || name) + "...");
      return post("/api/docker/action", { id: name, action: act }).then(function () {
        toast("OK: " + (label || name) + " (" + act + ")");
        if (current) refresh();
      }).catch(function (e) { toast("Erro: " + e.message, true); });
    });
  }
  function serviceRestart(s) {
    ask("REINICIAR SERVICO?", s.name + ": as tarefas sao recriadas (igual a docker service update --force).", "REINICIAR").then(function (ok) {
      if (!ok) return;
      toast("Reiniciando " + s.name + "...");
      post("/api/swarm/action", { id: s.name, action: "restart" }).then(function () {
        toast("Servico " + s.name + " reiniciando");
        setTimeout(refresh, 1500);
      }).catch(function (e) { toast("Erro: " + e.message, true); });
    });
  }

  var modalTimer = null, modalOpen = false;
  function openModal(title, tools, content, opts) {
    opts = opts || {};
    $("modal-title").textContent = title;
    $("modal").classList.toggle("menu", !!opts.menu);
    add(clear($("modal-tools")), [tools, h("button", { class: "btn close-x", onclick: closeModal }, MOBILE.matches ? "FECHAR" : "FECHAR [ESC]")]);
    add(clear($("modal-body")), [content]);
    var m = $("modal"), box = m.querySelector(".box");
    box.style.transform = ""; box.scrollTop = 0;
    m.classList.remove("hidden");
    document.body.classList.add("noscroll");
    if (!modalOpen) { try { history.pushState({ sheet: 1 }, ""); } catch (_) {} }
    modalOpen = true;
  }
  function hideModal() {
    clearInterval(modalTimer);
    $("modal").classList.add("hidden");
    document.body.classList.remove("noscroll");
    modalOpen = false;
  }
  function closeModal() {
    if (!modalOpen) return;
    if (history.state && history.state.sheet) history.back();   // dispara popstate, que esconde
    else hideModal();
  }
  window.addEventListener("popstate", function () { if (modalOpen) hideModal(); });
  $("modal").addEventListener("click", function (e) { if (e.target.id === "modal") closeModal(); });
  // arrastar a janela para baixo fecha (celular)
  (function () {
    var box = $("modal").querySelector(".box"), y0 = null, dy = 0;
    box.addEventListener("touchstart", function (e) {
      var fromGrab = e.target.closest && e.target.closest("#modal-grab, #modal-title");
      if (!MOBILE.matches || (!fromGrab && box.scrollTop > 0)) { y0 = null; return; }
      y0 = e.touches[0].clientY; dy = 0; box.classList.add("dragging");
    }, { passive: true });
    box.addEventListener("touchmove", function (e) {
      if (y0 === null) return;
      dy = Math.max(0, e.touches[0].clientY - y0);
      box.style.transform = dy ? "translateY(" + dy + "px)" : "";
    }, { passive: true });
    box.addEventListener("touchend", function () {
      if (y0 === null) return;
      box.classList.remove("dragging");
      if (dy > 110) closeModal(); else box.style.transform = "";
      y0 = null;
    });
  })();

  function openLogs(name, label, service) {
    var pre = h("pre", { class: "logs" }, "carregando...");
    var tail = h("select", null, [100, 200, 500, 1000, 2000].map(function (n) { return h("option", { value: n, selected: n === 200 }, n + " linhas"); }));
    var follow = h("input", { type: "checkbox", checked: true });
    var filter = h("input", { placeholder: "filtrar texto..." });
    var lastText = "";
    function paint() {
      var q = filter.value.toLowerCase();
      var txt = q ? lastText.split("\n").filter(function (l) { return l.toLowerCase().indexOf(q) >= 0; }).join("\n") : lastText;
      var atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 40;
      pre.textContent = txt || "(sem logs)";
      if (atBottom) pre.scrollTop = pre.scrollHeight;
    }
    function load() {
      var url = (service ? "/api/swarm/logs?id=" : "/api/docker/logs?id=") + encodeURIComponent(name) + "&tail=" + tail.value;
      api(url).then(function (d) { lastText = d.logs; paint(); })
        .catch(function (e) { pre.textContent = "Erro: " + e.message; });
    }
    tail.addEventListener("change", load);
    filter.addEventListener("input", paint);
    openModal("LOGS: " + (label || name), [tail, h("label", { class: "chk" }, follow, "ao vivo"), filter], pre);
    load();
    setTimeout(function () { pre.scrollTop = pre.scrollHeight; }, 400);
    clearInterval(modalTimer);
    modalTimer = setInterval(function () { if (follow.checked) load(); }, 3000);
  }
  function openInspect(name, label) {
    api("/api/docker/inspect?id=" + encodeURIComponent(name)).then(function (d) {
      openModal("CONTAINER: " + (label || d.name), null, h("div", { class: "stack" },
        kv([["ID", d.id], ["Nome", d.name], ["Imagem", d.image], ["Status", d.status], ["Health", d.health],
            ["Criado", d.created], ["Iniciado", d.started], ["Restarts", d.restart_count],
            ["Politica de restart", d.restart_policy], ["Redes", d.networks.join(", ")], ["Comando", d.cmd]]),
        h("p", { class: "label" }, "Volumes e pastas montadas"),
        table([{ t: "ORIGEM" }, { t: "DESTINO" }, { t: "MODO" }], d.mounts.map(function (m) {
          return h("tr", null, td(m.src, "cmd"), td(m.dst), td(m.rw ? "leitura/escrita" : "so leitura"));
        }))));
    }).catch(function (e) { toast("Erro: " + e.message, true); });
  }
  function openImages() {
    api("/api/docker/images").then(function (imgs) {
      var total = imgs.reduce(function (a, i) { return a + i.size; }, 0);
      openModal("IMAGENS (" + imgs.length + " / " + bytes(total) + ")", null,
        table([{ t: "TAG" }, { t: "ID" }, { t: "TAMANHO", num: 1 }, { t: "CRIADA" }], imgs.map(function (i) {
          return h("tr", null, td(i.tags.join(", "), "cmd"), td(i.id, "muted"), td(bytes(i.size), "num"), td(when(i.created)));
        })));
    }).catch(function (e) { toast("Erro: " + e.message, true); });
  }
  function openDockerDisk() {
    api("/api/docker/df").then(function (d) {
      openModal("ESPACO USADO PELO DOCKER", null, kv([["Imagens", bytes(d.images)], ["  sem uso (recuperavel)", bytes(d.images_reclaimable)],
        ["Camadas dos containers", bytes(d.containers)], ["Volumes", bytes(d.volumes) + " em " + d.volumes_count + " volumes"], ["Cache de build", bytes(d.build_cache)]]));
    }).catch(function (e) { toast("Erro: " + e.message, true); });
  }

  var VIEWS = {};

  // ---------- STATUS
  VIEWS.dash = {
    load: function () { return api("/api/overview"); },
    render: function (d) {
      var n = d.now || {};
      if (!n.cpu) return box("AGUARDE", "", h("p", null, "Coletando a primeira leitura..."));
      var s = d.static, m = n.memory, dk = d.docker || {};
      pushLive("cpu", n.cpu.percent); pushLive("mem", m.percent);
      pushLive("rx", n.net.rx_rate); pushLive("tx", n.net.tx_rate);
      pushLive("rd", n.io.read_rate); pushLive("wr", n.io.write_rate);
      updateHeader(d);
      var alerts = (d.alerts || []).slice();
      if (d.reboot_required) alerts.push("Reinicio pendente (atualizacao do kernel)");
      var o = d.oracle || {};

      return h("div", { class: "grid" },
        box("CPU", "",
          h("div", { class: "row" }, h("span", { class: "big " + level(n.cpu.percent) }, pct(n.cpu.percent)),
            h("span", { class: "muted" }, s.cpu_count + " nucleos")),
          h("canvas", { class: "spark", id: "sp-cpu" }),
          h("hr", { class: "sep" }),
          h("div", { class: "cores" }, n.cpu.cores.map(function (p, i) { return stat("#" + i, p, Math.round(p) + "%", { sm: 1 }); })),
          h("hr", { class: "sep" }),
          kv([["Carga (1/5/15 min)", n.load.map(function (x) { return x.toFixed(2); }).join("  /  ")],
              ["Steal (CPU roubada)", h("span", { class: n.cpu.steal > 5 ? "warn" : "" }, pct(n.cpu.steal))]])),
        box("MEMORIA", "",
          h("div", { class: "row" }, h("span", { class: "big " + level(m.percent) }, pct(m.percent)),
            h("span", { class: "muted" }, bytes(m.used) + " de " + bytes(m.total))),
          h("canvas", { class: "spark", id: "sp-mem" }),
          h("hr", { class: "sep" }),
          stat("RAM", m.percent),
          m.swap_total ? stat("SWAP", m.swap_percent) : null,
          h("hr", { class: "sep" }),
          kv([["Livre de verdade", bytes(m.available)], ["Cache", bytes(m.cached)],
              ["Swap", m.swap_total ? bytes(m.swap_used) + " de " + bytes(m.swap_total) : "desativado"]])),
        box("DISCOS", "", h("div", { class: "stack" }, n.disks.map(function (x) {
          return h("div", null,
            h("div", { class: "row" }, h("b", null, x.mount), h("span", { class: "muted" }, bytes(x.free) + " livres de " + bytes(x.total))),
            stat("USO", x.percent, undefined, { w: 80, c: 90 }));
        })), h("hr", { class: "sep" }),
          kv([["Leitura", rate(n.io.read_rate)], ["Escrita", rate(n.io.write_rate)]])),
        box("REDE", "",
          h("div", { class: "row" }, h("span", null, h("span", { class: "label" }, "DOWNLOAD"), h("div", { class: "mid ok" }, "↓ " + rate(n.net.rx_rate))),
            h("span", null, h("span", { class: "label" }, "UPLOAD"), h("div", { class: "mid", text: "↑ " + rate(n.net.tx_rate) }))),
          h("canvas", { class: "spark", id: "sp-net" }),
          h("p", { class: "muted" }, "verde = download, azul = upload"),
          table([{ t: "INTERFACE" }, { t: "RECEBIDO", num: 1 }, { t: "ENVIADO", num: 1 }], n.net.ifaces.filter(function (i) { return i.rx_total + i.tx_total > 0; }).map(function (i) {
            return h("tr", null, td(i.name), td(bytes(i.rx_total), "num"), td(bytes(i.tx_total), "num"));
          }))),
        box("DOCKER", "", dk.available ? [
          h("div", { class: "row" }, h("span", { class: "big " + (dk.info.stopped ? "warn" : "ok") }, dk.info.running + "/" + dk.info.containers),
            h("span", { class: "muted" }, "containers rodando")),
          dk.info.stopped ? h("p", { class: "warn" }, dk.info.stopped + " container(s) parado(s)") : null,
          h("p", { class: "label" }, "Quem mais usa CPU agora"),
          table([{ t: "SERVICO" }, { t: "CPU", num: 1 }, { t: "RAM", num: 1 }], dk.top.map(function (c) {
            return h("tr", null, td(c.label || c.name, "name", c.name), td(pct(c.cpu), "num " + level(c.cpu, 50, 90)), td(bytes(c.mem_used), "num"));
          })),
          h("p", null, h("button", { class: "btn small", onclick: function () { show("docker"); } }, "VER TODOS ▶"))
        ] : h("p", { class: "muted" }, "Docker nao disponivel neste host.")),
        box("SISTEMA", "",
          kv([["Maquina", s.hostname], ["Sistema", s.os], ["Kernel", s.kernel], ["Arquitetura", s.arch], ["Processador", s.cpu_model],
              ["Processos", n.procs.total + " (" + n.procs.running + " rodando" + (n.procs.zombie ? ", " + n.procs.zombie + " zumbi" : "") + ")"],
              ["Ligada ha", dur(n.uptime)],
              ["Temperatura", n.temps.length ? n.temps.map(function (t) { return t.c + "°C"; }).join(" ") : "n/d"]])),
        box("ALERTAS", "", alerts.length ? h("div", { class: "stack" }, alerts.map(function (a) { return h("div", { class: "warn" }, "⚠ " + a); }))
          : h("div", { class: "row" }, h("span", { class: "mid ok" }, "ALL CLEAR!"), h("span", { class: "muted" }, "Nenhum alerta ativo"))),
        box("ORACLE FREE TIER", "",
          h("p", { class: "muted" }, "A Oracle pode recuperar VMs gratuitas ociosas (CPU p95 abaixo de 20% em 7 dias)."),
          o.cpu_p95 === null || o.cpu_p95 === undefined ? h("p", null, "Coletando dados (" + (o.days || 0) + " dias)...") :
            h("div", { class: "stack" }, stat("CPU95", o.cpu_p95, pct(o.cpu_p95)), stat("RAM95", o.mem_p95 || 0, pct(o.mem_p95)),
              kv([["Dados coletados", o.days + " dias"], ["Situacao", o.at_risk ? h("span", { class: "warn" }, "RISCO DE RECUPERACAO") : h("span", { class: "ok" }, "SEGURA")]]))));
    },
    after: function () {
      drawChart($("sp-cpu"), [{ data: live.cpu, fill: true }], { max: 100 });
      drawChart($("sp-mem"), [{ data: live.mem, fill: true, color: css("--magic") }], { max: 100 });
      drawChart($("sp-net"), [{ data: live.rx, fill: true }, { data: live.tx }]);
    }
  };

  function updateHeader(d) {
    var s = d.static;
    $("subtitle").textContent = "HOST " + s.hostname.toUpperCase() + " · v" + d.version;
    var chips = clear($("chips"));
    [["SO", s.os], ["CPU", s.cpu_count + " vCPU " + s.arch], ["RAM", bytes(d.now.memory.total)],
     ["PLAYER", (state.me && state.me.user) || "?"]].forEach(function (c) {
      chips.appendChild(h("span", { class: "chip" }, h("b", null, c[0] + " "), c[1]));
    });
    $("uptime").textContent = "ligada ha " + dur(d.now.uptime);
  }

  // ---------- DOCKER
  VIEWS.docker = {
    setup: function () {
      var q = h("input", { placeholder: "buscar servico, container ou imagem", value: state.dockerQuery, size: 34 });
      q.addEventListener("input", function () { state.dockerQuery = q.value; refresh(); });
      return h("div", { class: "toolbar" }, q,
        h("button", { class: "btn", onclick: openImages }, "IMAGENS"),
        h("button", { class: "btn", onclick: openDockerDisk }, "ESPACO EM DISCO"));
    },
    load: function () {
      return Promise.all([api("/api/docker"), api("/api/swarm").catch(function () { return { active: false }; })]);
    },
    render: function (r) {
      var d = r[0], sw = r[1];
      if (!d.available) return box("DOCKER", "", h("p", { class: "warn" }, d.error || "Docker indisponivel"),
        h("p", { class: "muted" }, "Se acabou de instalar o Docker, rode na VM: sudo vmpanel restart"));
      var q = state.dockerQuery.toLowerCase();
      function match(txt) { return !q || txt.toLowerCase().indexOf(q) >= 0; }
      var out = h("div", { class: "stack" });

      if (sw.active) {
        var services = sw.services.filter(function (s) { return match(s.name + s.image + s.stack + s.domains.join(" ")); });
        out.appendChild(box("DOCKER SWARM · " + sw.stacks.length + " STACKS · " + sw.services.length + " SERVICOS", "",
          h("div", { class: "stacks" }, sw.stacks.map(function (st) {
            var okAll = st.healthy === st.services;
            return h("div", { class: "stack-card" }, h("span", { class: "px" }, st.name),
              h("span", { class: "tag " + (okAll ? "run" : "stop") }, st.healthy + "/" + st.services + " OK"));
          })),
          table([{ t: "STACK" }, { t: "SERVICO", m: "title" }, { t: "REPLICAS" }, { t: "IMAGEM" }, { t: "DOMINIO" }, { t: "ACOES" }],
            services.map(function (s) {
              var good = s.desired === null ? s.running > 0 : s.running >= s.desired;
              return h("tr", null, td(s.stack || "-", "muted"), td(s.name, "name", s.name),
                td(h("span", { class: "tag " + (good ? "run" : "stop"), title: s.error || "" }, s.running + "/" + (s.desired === null ? "global" : s.desired))),
                td(s.image, "cmd", s.image),
                td(s.domains.length ? s.domains.map(function (x) { return h("div", null, h("a", { href: "https://" + x, target: "_blank", rel: "noopener" }, x)); }) : "-"),
                td([h("button", { class: "btn small", onclick: function () { openLogs(s.name, s.name, true); } }, "LOGS"), " ",
                    h("button", { class: "btn small", onclick: function () { serviceRestart(s); } }, "↻ REINICIAR")], "actions"));
            }), { empty: "nenhum servico encontrado", cards: true })));
      }

      var list = d.containers.filter(function (c) { return match(c.name + c.label + c.image + c.project); });
      var i = d.info;
      out.appendChild(box("CONTAINERS · " + i.running + " RODANDO · " + i.stopped + " PARADOS", "",
        table([{ t: "ESTADO" }, { t: "NOME", m: "title" }, { t: "CPU", num: 1 }, { t: "RAM", num: 1 }, { t: "REDE ↓/↑", num: 1 }, { t: "STATUS" }, { t: "ACOES" }],
          list.map(function (c) {
            var on = c.state === "running";
            return h("tr", null,
              td(h("span", { class: "tag " + (on ? "run" : c.state === "exited" || c.state === "dead" ? "stop" : "other") }, c.state)),
              td([h("div", { class: "name" }, c.label), h("div", { class: "muted cmd", title: c.image }, c.image)], null, c.name),
              td(on ? pct(c.cpu) : "-", "num " + (on ? level(c.cpu, 50, 90) : "")),
              td(on ? bytes(c.mem_used) : "-", "num"),
              td(on ? bytes(c.net_rx) + " / " + bytes(c.net_tx) : "-", "num"),
              td(c.status, "muted"),
              td([
                on ? null : h("button", { class: "btn small", title: "iniciar", onclick: function () { dockerAct(c.name, "start", c.label); } }, "▶ INICIAR"),
                on ? h("button", { class: "btn small", title: "reiniciar", onclick: function () { dockerAct(c.name, "restart", c.label); } }, "↻") : null,
                on ? h("button", { class: "btn small danger", title: "parar", onclick: function () { dockerAct(c.name, "stop", c.label); } }, "■") : null,
                " ",
                h("button", { class: "btn small", onclick: function () { openLogs(c.name, c.label); } }, "LOGS"),
                h("button", { class: "btn small", onclick: function () { openInspect(c.name, c.label); } }, "INFO")], "actions"));
          }), { empty: "nenhum container", cards: true })));
      return out;
    }
  };

  // ---------- PROCESSOS
  VIEWS.procs = {
    setup: function () {
      var q = h("input", { placeholder: "buscar por nome, PID ou usuario", value: state.procQuery, size: 32 });
      q.addEventListener("input", function () { state.procQuery = q.value; refresh(); });
      var s = h("select", null, [["cpu", "Ordenar por CPU"], ["mem", "Ordenar por memoria"], ["pid", "Ordenar por PID"]].map(function (o) {
        return h("option", { value: o[0], selected: o[0] === state.procSort }, o[1]);
      }));
      s.addEventListener("change", function () { state.procSort = s.value; refresh(); });
      return h("div", { class: "toolbar" }, q, s);
    },
    load: function () { return api("/api/processes?sort=" + state.procSort + "&q=" + encodeURIComponent(state.procQuery)); },
    render: function (list) {
      return box("PROCESSOS", "", table([{ t: "PID", num: 1, sort: "pid" }, { t: "USUARIO", m: "hide" }, { t: "CPU", num: 1, sort: "cpu" }, { t: "MEM", num: 1, sort: "mem" },
                    { t: "RAM", num: 1, m: "hide" }, { t: "THREADS", num: 1, m: "hide" }, { t: "COMANDO" }],
        list.map(function (p) {
          return h("tr", null, td(p.pid, "num"), td(p.user), td(p.cpu.toFixed(1) + "%", "num " + level(p.cpu, 50, 90)), td(p.mem.toFixed(1) + "%", "num " + level(p.mem, 30, 60)),
            td(bytes(p.rss), "num"), td(p.threads, "num"), td(p.cmd, "cmd", p.cmd));
        }), { onSort: function (k) { state.procSort = k; show("procs"); } }));
    }
  };

  // ---------- REDE
  VIEWS.net = {
    load: function () { return api("/api/network"); },
    render: function (d) {
      var st = d.conns.states;
      return h("div", { class: "grid wide" },
        box("INTERFACES", "span2", table([{ t: "INTERFACE", m: "title" }, { t: "↓ AGORA", num: 1 }, { t: "↑ AGORA", num: 1 }, { t: "RECEBIDO", num: 1 }, { t: "ENVIADO", num: 1 }, { t: "ERROS", num: 1 }],
          d.ifaces.filter(function (i) { return i.rx_total + i.tx_total > 0; }).map(function (i) {
            return h("tr", null, td(i.name, "name"), td(rate(i.rx_rate), "num"), td(rate(i.tx_rate), "num"), td(bytes(i.rx_total), "num"), td(bytes(i.tx_total), "num"), td(i.errors, "num " + (i.errors ? "warn" : "")));
          }), { cards: true })),
        box("PORTAS ABERTAS", "", table([{ t: "PORTA", num: 1 }, { t: "PROTO" }, { t: "ENDERECO" }, { t: "ACESSO" }],
          d.ports.map(function (p) {
            var pub = !/^(127\.|::1|localhost|\[?::1)/.test(p.addr) && !/%lo$/.test(p.addr);
            return h("tr", null, td(p.port, "num"), td(p.proto), td(p.addr), td(h("span", { class: "tag " + (pub ? "other" : "info") }, pub ? "INTERNET" : "LOCAL")));
          }))),
        box("CONEXOES", "", kv(Object.keys(st).sort().map(function (k) { return [k, st[k]]; })),
          h("hr", { class: "sep" }), h("p", { class: "label" }, "IPs com mais conexoes"),
          table([{ t: "IP" }, { t: "CONEXOES", num: 1 }], d.conns.top_peers.map(function (p) { return h("tr", null, td(p.ip), td(p.count, "num")); })),
          h("hr", { class: "sep" }), h("p", { class: "label" }, "Enderecos desta VM"),
          table([{ t: "INTERFACE" }, { t: "ENDERECO" }], d.ips.map(function (a) { return h("tr", null, td(a.iface), td(a.addr)); }))));
    }
  };

  // ---------- DISCOS
  VIEWS.disks = {
    load: function () { return api("/api/overview"); },
    render: function (d) {
      var n = d.now;
      pushLive("rd", n.io.read_rate); pushLive("wr", n.io.write_rate);
      return h("div", { class: "grid wide" },
        box("PARTICOES", "span2", h("div", { class: "stack" }, n.disks.map(function (x) {
          return h("div", null, h("div", { class: "row" }, h("span", { class: "mid" }, x.mount), h("span", { class: "muted" }, x.device + " · " + x.fs)),
            stat("USO", x.percent, pct(x.percent), { w: 80, c: 90 }),
            h("div", { class: "row muted" }, h("span", null, bytes(x.used) + " usados · " + bytes(x.free) + " livres · " + bytes(x.total) + " total"),
              h("span", { class: level(x.inodes_percent) }, "inodes " + pct(x.inodes_percent))));
        }))),
        box("LEITURA E ESCRITA", "span2", h("canvas", { class: "chart", id: "ch-io" }),
          h("p", { class: "muted" }, "verde = leitura · azul = escrita (ultimos minutos)"),
          table([{ t: "DISCO" }, { t: "LEITURA", num: 1 }, { t: "ESCRITA", num: 1 }, { t: "OCUPADO", num: 1 }], n.io.devices.map(function (x) {
            return h("tr", null, td(x.name), td(rate(x.read_rate), "num"), td(rate(x.write_rate), "num"), td(pct(x.busy), "num " + level(x.busy)));
          }))));
    },
    after: function () { drawChart($("ch-io"), [{ data: live.rd, fill: true }, { data: live.wr }], { axis: true, fmt: rate }); }
  };

  // ---------- SISTEMA
  VIEWS.system = {
    load: function () { return api("/api/system"); },
    render: function (d) {
      var s = d.static, u = d.updates;
      return h("div", { class: "grid wide" },
        box("MAQUINA", "", kv([["Hostname", s.hostname], ["Sistema", s.os], ["Kernel", s.kernel], ["Arquitetura", s.arch],
          ["Processador", s.cpu_model], ["vCPUs", s.cpu_count], ["Python", s.python],
          ["Temperaturas", d.temps.length ? d.temps.map(function (t) { return t.name + " " + t.c + "°C"; }).join(", ") : "n/d"]])),
        box("ATUALIZACOES DO SISTEMA", "",
          u.manager ? h("div", { class: "stack" },
            h("div", { class: "big " + (u.count ? "warn" : "ok") }, u.count ? u.count + " PACOTES" : "EM DIA!"),
            u.security ? h("p", { class: "crit" }, u.security + " atualizacoes de seguranca") : null,
            d.reboot_required ? h("p", { class: "warn" }, "⚠ A VM precisa reiniciar para concluir atualizacoes") : null,
            u.count ? h("p", { class: "muted cmd" }, (u.packages || []).join(", ")) : null,
            u.count ? h("p", null, "Para instalar, abra o ", h("a", { href: "#term", onclick: function (e) { e.preventDefault(); show("term"); } }, "TERMINAL"),
              " e rode: ", h("code", null, "sudo " + (u.manager === "apt" ? "apt update && sudo apt upgrade" : "dnf upgrade"))) : null)
            : h("p", { class: "muted" }, "Gerenciador de pacotes nao detectado.")),
        box("SERVICOS IMPORTANTES", "", table([{ t: "SERVICO" }, { t: "ESTADO" }, { t: "DESDE" }], d.services.map(function (x) {
          var on = x.active === "active";
          return h("tr", null, td(x.name, "name"), td(h("span", { class: "tag " + (on ? "run" : x.active === "failed" ? "stop" : "other") }, x.active)), td(x.since, "muted"));
        }))),
        box("FALHAS NO SYSTEMD", "", d.failed.length ? table([{ t: "UNIDADE" }, { t: "DESCRICAO" }], d.failed.map(function (f) {
          return h("tr", null, td(f.unit, "crit"), td(f.desc));
        })) : h("p", { class: "ok" }, "Nenhuma unidade com falha.")));
    }
  };

  // ---------- SEGURANCA
  VIEWS.security = {
    load: function () { return Promise.all([api("/api/security"), api("/api/me")]); },
    render: function (r) {
      var d = r[0], me = r[1], ssh = d.ssh;
      var kinds = { login_ok: "LOGIN OK", login_fail: "LOGIN FALHOU", ip_locked: "IP BLOQUEADO", alert: "ALERTA", settings: "CONFIG",
        start: "PAINEL INICIOU", sessions_revoked: "SESSOES ENCERRADAS", terminal: "TERMINAL ABERTO", term_unlock: "TERMINAL LIBERADO",
        term_unlock_fail: "SENHA ERRADA (TERMINAL)", panel_update: "ATUALIZACAO DO PAINEL" };
      return h("div", { class: "grid wide" },
        box("SEU ACESSO", "", kv([["Usuario", me.user], ["2FA", me.totp ? h("span", { class: "ok" }, "ATIVO") : h("span", { class: "warn" }, "DESATIVADO (sudo vmpanel 2fa-on)")],
            ["Seu IP", me.ip], ["Sessoes abertas", d.sessions.length]]),
          h("hr", { class: "sep" }),
          table([{ t: "IP", m: "title" }, { t: "ENTROU EM" }, { t: "NAVEGADOR" }], d.sessions.map(function (s) {
            return h("tr", null, td(s.ip), td(when(s.created)), td(s.ua, "cmd", s.ua));
          }), { cards: true }),
          h("p", null, h("button", { class: "btn danger", onclick: function () {
            ask("ENCERRAR SESSOES?", "Todas as sessoes abertas serao encerradas, inclusive esta.", "ENCERRAR", true).then(function (ok) {
              if (ok) post("/api/sessions/revoke").then(function () { location.href = "/login"; });
            });
          } }, "ENCERRAR TODAS AS SESSOES"))),
        box("ATAQUES SSH (24H)", "", !ssh.available ? h("p", { class: "muted" }, "Sem acesso ao log do SSH.") : h("div", { class: "stack" },
          h("div", { class: "big " + (ssh.failed_24h > 100 ? "warn" : "ok") }, ssh.failed_24h + " FALHAS"),
          ssh.failed_24h > 50 ? h("p", { class: "muted" }, "Dica: use so chave SSH (PasswordAuthentication no) e instale o fail2ban.") : null,
          table([{ t: "IP ATACANTE" }, { t: "TENTATIVAS", num: 1 }], ssh.top_ips.map(function (x) { return h("tr", null, td(x.ip), td(x.count, "num")); })),
          h("p", { class: "label" }, "Usuarios que tentaram"),
          h("p", { class: "muted" }, ssh.top_users.map(function (x) { return x.user + " (" + x.count + ")"; }).join(", ") || "-"))),
        box("REGISTRO DO PAINEL", "span2", table([{ t: "QUANDO" }, { t: "EVENTO", m: "title" }, { t: "IP" }, { t: "DETALHE" }], d.events.slice(0, MOBILE.matches ? 25 : 500).map(function (e) {
          return h("tr", null, td(when(e.ts)), td(kinds[e.kind] || e.kind.toUpperCase(), /fail|lock|alert/.test(e.kind) ? "warn" : ""), td(e.ip || "-"), td(e.detail, "cmd", e.detail));
        }), { cards: true })));
    }
  };

  // ---------- HISTORICO
  VIEWS.history = {
    setup: function () {
      return h("div", { class: "toolbar" }, ["1h", "6h", "24h", "7d", "30d"].map(function (r) {
        return h("button", { class: "btn" + (r === state.histRange ? " gold" : ""), onclick: function () { state.histRange = r; show("history"); } }, r.toUpperCase());
      }));
    },
    load: function () { return api("/api/history?range=" + state.histRange); },
    render: function (rows) {
      if (!rows.length) return box("HISTORICO", "", h("p", null, "Ainda sem dados. O painel grava um ponto por minuto; volte daqui a pouco."));
      function avg(k) { return rows.reduce(function (a, r) { return a + (r[k] || 0); }, 0) / rows.length; }
      function mx(k) { return rows.reduce(function (a, r) { return Math.max(a, r[k] || 0); }, 0); }
      return h("div", { class: "grid wide" },
        box("CPU", "", h("canvas", { class: "chart", id: "h-cpu" }), h("p", { class: "muted" }, "media " + pct(avg("cpu")) + " · pico " + pct(mx("cpu_max")))),
        box("MEMORIA", "", h("canvas", { class: "chart", id: "h-mem" }), h("p", { class: "muted" }, "media " + pct(avg("mem")) + " · max " + pct(mx("mem")) + " · azul = swap")),
        box("REDE", "", h("canvas", { class: "chart", id: "h-net" }), h("p", { class: "muted" }, "verde = download (media " + rate(avg("rx")) + ") · azul = upload (media " + rate(avg("tx")) + ")")),
        box("DISCO / E CARGA", "", h("canvas", { class: "chart", id: "h-disk" }), h("p", { class: "muted" }, "verde = disco (agora " + pct(rows[rows.length - 1].disk) + ") · azul = carga (max " + mx("load1").toFixed(2) + ")")));
    },
    after: function (rows) {
      if (!rows.length) return;
      var lbl = rows.map(function (r) {
        var d = new Date(r.ts * 1000);
        return state.histRange === "7d" || state.histRange === "30d" ? pad(d.getDate()) + "/" + pad(d.getMonth() + 1) : pad(d.getHours()) + ":" + pad(d.getMinutes());
      });
      function col(k) { return rows.map(function (r) { return r[k] || 0; }); }
      function p100(v) { return Math.round(v) + "%"; }
      drawChart($("h-cpu"), [{ data: col("cpu"), fill: true }, { data: col("cpu_max"), color: css("--warn") }], { max: 100, axis: true, labels: lbl, fmt: p100 });
      drawChart($("h-mem"), [{ data: col("mem"), fill: true, color: css("--magic") }, { data: col("swap") }], { max: 100, axis: true, labels: lbl, fmt: p100 });
      drawChart($("h-net"), [{ data: col("rx"), fill: true }, { data: col("tx") }], { axis: true, labels: lbl, fmt: rate });
      var maxLoad = Math.max.apply(null, col("load1").concat([1]));
      drawChart($("h-disk"), [{ data: col("disk"), fill: true }, { data: col("load1").map(function (v) { return v / maxLoad * 100; }) }], { max: 100, axis: true, labels: lbl, fmt: p100 });
    }
  };

  // ---------- TERMINAL
  var term = null, termWs = null, termFit = null, termResize = null, termCtrl = null;
  function termSend(data) { if (termWs && termWs.readyState === 1) termWs.send(JSON.stringify({ type: "input", data: data })); }
  // teclas que faltam no teclado do celular
  function keybar() {
    var ctrl = h("button", { class: "key", onclick: function () { ctrl.classList.toggle("on"); if (term) term.focus(); } }, "CTRL");
    termCtrl = ctrl;
    var keys = [["ESC", "\x1b"], ["TAB", "\t"], ["↑", "\x1b[A"], ["↓", "\x1b[B"], ["←", "\x1b[D"], ["→", "\x1b[C"],
                ["|", "|"], ["/", "/"], ["-", "-"], ["~", "~"], ["^C", "\x03"], ["^D", "\x04"]];
    return h("div", { class: "keybar" }, ctrl, keys.map(function (k) {
      return h("button", { class: "key", onclick: function () { buzz(); termSend(k[1]); if (term) term.focus(); } }, k[0]);
    }));
  }
  function loadXterm() {
    if (window.Terminal && window.FitAddon) return Promise.resolve();
    function js(src) {
      return new Promise(function (ok, bad) { var s = h("script", { src: src }); s.onload = ok; s.onerror = bad; document.head.appendChild(s); });
    }
    document.head.appendChild(h("link", { rel: "stylesheet", href: "/static/vendor/xterm.css" }));
    return js("/static/vendor/xterm.js")
      .then(function () { return js("/static/vendor/addon-fit.js"); });
  }
  function closeTerminal() {
    if (termWs) { try { termWs.close(); } catch (_) {} termWs = null; }
    if (term) { term.dispose(); term = null; }
    if (termResize) {
      window.removeEventListener("resize", termResize);
      if (window.visualViewport) window.visualViewport.removeEventListener("resize", termResize);
      termResize = null;
    }
    document.body.classList.remove("kbd");
  }
  function startTerminal(holder, status) {
    loadXterm().then(function () {
      closeTerminal();
      term = new window.Terminal({
        cursorBlink: true, fontSize: MOBILE.matches ? 12 : 14, scrollback: 5000,
        fontFamily: "'Cascadia Mono', 'DejaVu Sans Mono', Menlo, monospace",
        theme: { background: "#0d0e17", foreground: "#f4f4f4", cursor: "#ffcd75", selectionBackground: "#3b5dc9",
                 black: "#1a1c2c", red: "#b13e53", green: "#38b764", yellow: "#ffcd75", blue: "#3b5dc9", magenta: "#5d275d",
                 cyan: "#41a6f6", white: "#f4f4f4", brightBlack: "#566c86", brightRed: "#ef7d57", brightGreen: "#a7f070",
                 brightYellow: "#ffcd75", brightBlue: "#41a6f6", brightMagenta: "#b13e53", brightCyan: "#73eff7", brightWhite: "#ffffff" }
      });
      termFit = new window.FitAddon.FitAddon();
      term.loadAddon(termFit);
      term.open(holder);
      termFit.fit();
      var proto = location.protocol === "https:" ? "wss://" : "ws://";
      termWs = new WebSocket(proto + location.host + "/api/term?cols=" + term.cols + "&rows=" + term.rows);
      termWs.binaryType = "arraybuffer";
      termWs.onopen = function () {
        status.textContent = "CONECTADO"; status.className = "tag run";
        if (termResize) termResize();
        if (!MOBILE.matches) term.focus();   // no celular o teclado so abre quando tocar no terminal
      };
      termWs.onmessage = function (e) { term.write(typeof e.data === "string" ? e.data : new Uint8Array(e.data)); };
      termWs.onclose = function () {
        status.textContent = "DESCONECTADO"; status.className = "tag stop";
        if (term) term.write("\r\n\x1b[33m[sessao encerrada - clique em RECONECTAR]\x1b[0m\r\n");
      };
      term.onData(function (data) {
        if (termCtrl && termCtrl.classList.contains("on") && data.length === 1) {   // CTRL fixo: proxima letra vira Ctrl+letra
          var c = data.toUpperCase().charCodeAt(0);
          if (c >= 64 && c <= 95) data = String.fromCharCode(c - 64);
          termCtrl.classList.remove("on");
        }
        termSend(data);
      });
      termResize = function () {
        if (!term) return;
        if (MOBILE.matches) {   // no celular o terminal ocupa o que sobra acima do teclado virtual
          var vv = window.visualViewport, vh = vv ? vv.height : window.innerHeight;
          document.body.classList.toggle("kbd", vh < window.innerHeight * 0.8 || (vv && vh < screen.height * 0.6));
          var kb = holder.nextSibling, nav = $("bnav");
          var used = holder.getBoundingClientRect().top - (vv ? vv.offsetTop : 0) + (kb ? kb.offsetHeight : 0) +
                     (document.body.classList.contains("kbd") ? 0 : nav.offsetHeight) + 14;
          holder.style.height = Math.max(160, vh - used) + "px";
        }
        termFit.fit();
        if (termWs && termWs.readyState === 1) termWs.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      };
      window.addEventListener("resize", termResize);
      if (window.visualViewport) window.visualViewport.addEventListener("resize", termResize);
      termResize();
    }).catch(function () { toast("Nao consegui carregar o terminal", true); });
  }
  VIEWS.term = {
    load: function () { return api("/api/me"); },
    render: function (me) {
      if (!me.agent) return box("TERMINAL", "", h("p", { class: "warn" }, "O agente do painel nao esta rodando."),
        h("p", null, "Rode na VM: ", h("code", null, "curl -fsSL https://raw.githubusercontent.com/dhqdev/gerenciamento/HEAD/update.sh | sudo bash")));
      if (!me.term_unlocked) {
        var pw = h("input", { type: "password", placeholder: "sua senha do painel", autocomplete: "current-password", size: 30 });
        var msg = h("p", { role: "status" });
        var f = h("form", { class: "toolbar" }, pw, h("button", { class: "btn gold", type: "submit" }, "▶ ABRIR TERMINAL"));
        f.addEventListener("submit", function (e) {
          e.preventDefault();
          post("/api/term/unlock", { password: pw.value }).then(function () { show("term"); })
            .catch(function (er) { msg.textContent = er.message; msg.className = "crit"; pw.value = ""; });
        });
        setTimeout(function () { pw.focus(); }, 50);
        return box("TERMINAL BLOQUEADO", "", h("p", null, "O terminal da acesso total a VM. Confirme sua senha para liberar por 30 minutos."), f, msg);
      }
      var status = h("span", { class: "tag other" }, "CONECTANDO");
      var holder = h("div", { class: "term-wrap" });
      var wrap = h("div", { class: "stack" },
        h("div", { class: "toolbar" }, status,
          h("button", { class: "btn", onclick: function () { startTerminal(holder, status); } }, "↻ RECONECTAR"),
          h("span", { class: "muted hide-m" }, "Dica: copie com Ctrl+Shift+C e cole com Ctrl+Shift+V. Tudo que acontece aqui fica no registro do painel.")),
        holder, keybar());
      setTimeout(function () { startTerminal(holder, status); }, 30);
      return wrap;
    }
  };

  // ---------- CONFIG
  VIEWS.config = {
    load: function () { return api("/api/settings"); },
    render: function (s) {
      function num(k, label) { return h("label", { class: "f" }, h("span", null, label), h("input", { name: k, type: "number", min: 1, max: 1440, value: s[k] })); }
      function chk(k, label) { return h("label", { class: "chk" }, h("input", { name: k, type: "checkbox", checked: !!s[k] }), label); }
      function txt(k, label, ph) { return h("label", { class: "f" }, h("span", null, label), h("input", { name: k, value: s[k] || "", placeholder: ph || "", autocomplete: "off" })); }
      var msg = h("p", { role: "status" });
      var themeSel = h("select", null, THEMES.map(function (t) { return h("option", { value: t[0], selected: t[0] === prefs.theme }, t[1]); }));
      themeSel.addEventListener("change", function () { prefs.theme = themeSel.value; savePref("vmp_theme2", prefs.theme); applyPrefs(); });
      var form = h("form", null,
        h("div", { class: "grid wide" },
          box("ALERTAS", "",
            num("alert_cpu", "Avisar quando a CPU passar de (%)"), num("alert_mem", "Avisar quando a memoria passar de (%)"), num("alert_disk", "Avisar quando o disco passar de (%)"),
            num("alert_minutes", "Por quantos minutos seguidos (CPU/memoria)"), num("alert_cooldown_min", "Esperar quantos minutos antes de repetir o mesmo alerta"),
            chk("alert_container_down", "Avisar quando um container parar"), chk("alert_login", "Avisar a cada login no painel"),
            chk("oracle_idle_watch", "Vigiar a regra de VM ociosa da Oracle")),
          box("NOTIFICACOES", "",
            txt("discord_webhook", "Webhook do Discord", "https://discord.com/api/webhooks/..."),
            txt("telegram_token", "Token do bot do Telegram", "123456:ABC..."),
            txt("telegram_chat_id", "Chat ID do Telegram", "123456789"),
            h("p", { class: "muted" }, "Depois de salvos, os segredos aparecem como ********."),
            h("button", { class: "btn", type: "button", onclick: function () {
              post("/api/settings/test").then(function () { toast("Mensagem de teste enviada!"); })
                .catch(function (e) { toast("Falhou: " + e.message, true); });
            } }, "ENVIAR TESTE")),
          box("VISUAL (NESTE NAVEGADOR)", "",
            h("label", { class: "f" }, h("span", null, "Tema"), themeSel),
            h("label", { class: "chk" }, h("input", { type: "checkbox", checked: prefs.crt, onchange: function (e) { prefs.crt = e.target.checked; savePref("vmp_crt2", prefs.crt ? "1" : "0"); applyPrefs(); } }), "Efeito de TV antiga (scanlines)")),
          box("APP NO CELULAR", "",
            standalone() ? h("p", { class: "ok" }, "Voce esta usando o app instalado.") :
              h("p", null, "Instale o painel como app: abre em tela cheia, com icone proprio e menu embaixo."),
            standalone() ? null : (function (t) {
              return t ? h("div", { class: "tiles" }, t) : h("p", { class: "muted" },
                "No Chrome do Android: menu ⋮ > Instalar app. No iPhone: Compartilhar > Adicionar a Tela de Inicio.");
            })(installTile())),
          box("COMANDOS NA VM", "", h("pre", { class: "logs" },
            "# atualizar o painel\ncurl -fsSL https://raw.githubusercontent.com/dhqdev/gerenciamento/HEAD/update.sh | sudo bash\n\n" +
            "# remover o painel\ncurl -fsSL https://raw.githubusercontent.com/dhqdev/gerenciamento/HEAD/uninstall.sh | sudo bash\n\n" +
            "sudo vmpanel passwd        # trocar usuario/senha\n" +
            "sudo vmpanel 2fa-on        # ativar 2FA\n" +
            "sudo vmpanel terminal off  # desligar o terminal web\n" +
            "sudo vmpanel doctor        # diagnostico"))),
        h("p", null, h("button", { class: "btn gold", type: "submit" }, "✔ SALVAR")), msg);
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        var data = {};
        Array.prototype.forEach.call(form.querySelectorAll("input[name]"), function (i) { data[i.name] = i.type === "checkbox" ? i.checked : i.value; });
        post("/api/settings", data).then(function () { toast("Configuracoes salvas!"); })
          .catch(function (er) { toast("Erro: " + er.message, true); });
      });
      return form;
    }
  };

  // ------------------------------------------------------------------ atualizacao do painel
  function checkVersion() {
    return api("/api/version").then(function (v) {
      state.version = v;
      var b = $("btn-update");
      clear(b);
      add(b, ["★", h("span", { class: "t" }, " ATUALIZAR PAINEL"), v.ok && v.behind ? h("span", { class: "badge-new" }, "NEW") : null]);
      return v;
    }).catch(function () { return null; });
  }
  function openUpdate() {
    var body = h("div", { class: "stack" }, h("p", null, "Procurando atualizacoes no GitHub..."));
    openModal("ATUALIZAR PAINEL", null, body);
    checkVersion().then(function (v) {
      clear(body);
      if (!v || !v.ok) { add(body, [h("p", { class: "crit" }, (v && v.error) || "Nao consegui verificar a versao.")]); return; }
      if (!v.behind) {
        add(body, [h("p", { class: "mid ok" }, "VOCE JA ESTA NA ULTIMA VERSAO!"), h("p", { class: "muted" }, "Versao instalada: " + v.local)]);
        return;
      }
      add(body, [
        h("p", { class: "mid warn" }, v.behind + " NOVIDADE(S) DISPONIVEL(IS)"),
        h("pre", { class: "logs" }, v.changes.join("\n")),
        h("p", { class: "muted" }, "O painel reinicia sozinho durante a atualizacao (cerca de 30 segundos). Seus containers nao sao afetados."),
        h("p", null, h("button", { class: "btn gold", onclick: runUpdate }, "▶ ATUALIZAR AGORA"))
      ]);
    });
  }
  function runUpdate() {
    closeModal();
    var ov = $("overlay"), bar = $("ov-bar"), log = $("ov-log");
    ov.classList.remove("hidden");
    var p = 0, before = state.me && state.me.version, started = Date.now();
    bar.style.width = "0%";
    var tick = setInterval(function () { p = Math.min(95, p + 2); bar.style.width = p + "%"; }, 700);
    post("/api/update").catch(function (e) {
      clearInterval(tick);
      $("ov-title").textContent = "GAME OVER";
      $("ov-msg").textContent = "Nao consegui iniciar a atualizacao: " + e.message;
      setTimeout(function () { ov.classList.add("hidden"); }, 6000);
    });
    var poll = setInterval(function () {
      api("/api/update/log").then(function (d) { if (d.log) log.textContent = d.log.replace(/\x1b\[[0-9;]*m/g, ""); }).catch(function () {});
      fetch("/api/me", { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (me) {
        var elapsed = Date.now() - started;
        var done = me && elapsed > 8000 && /Atualizado:|nao subiu/.test(log.textContent);
        if (done || (me && elapsed > 150000)) {
          clearInterval(poll); clearInterval(tick);
          bar.style.width = "100%";
          $("ov-title").textContent = "STAGE CLEAR!";
          $("ov-msg").textContent = "Painel atualizado" + (me.version !== before ? " para a v" + me.version : "") + ". Recarregando...";
          setTimeout(function () { location.reload(); }, 1800);
        }
      }).catch(function () {});
    }, 2500);
  }

  // ------------------------------------------------------------------ celular: menu inferior, "MAIS" e puxar para atualizar
  var BNAV = ["dash", "docker", "procs", "term"];
  var SHORT = { dash: "STATUS", docker: "DOCKER", procs: "PROC", term: "TERM", more: "MAIS" };
  function buildBottomNav() {
    add($("bnav"), BNAV.concat(["more"]).map(function (id) {
      return h("button", { "data-id": id, onclick: function () { buzz(); if (id === "more") openMore(); else { if (modalOpen) closeModal(); show(id); } } },
        icon(id), h("span", null, SHORT[id]));
    }));
  }
  function isIOS() { return /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1); }
  function standalone() { return window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true; }
  function installTile() {
    if (standalone()) return null;
    if (window.vmpInstall) return tile("install", "INSTALAR APP", function () {
      var p = window.vmpInstall; window.vmpInstall = null; closeModal();
      p.prompt(); p.userChoice.then(function (c) { if (c.outcome === "accepted") toast("App instalado! Procure o VM PANEL na tela inicial."); });
    }, "gold");
    if (isIOS()) return tile("install", "INSTALAR APP", function () {
      openModal("INSTALAR NO IPHONE", null, h("div", { class: "stack" },
        h("p", null, "1. Toque no botao Compartilhar do Safari (o quadrado com a seta para cima)."),
        h("p", null, "2. Escolha \"Adicionar a Tela de Inicio\"."),
        h("p", null, "3. Abra o VM PANEL pelo icone novo: ele abre em tela cheia, como um app.")));
    }, "gold");
    return null;
  }
  function tile(ic, label, fn, cls) {
    return h("button", { class: "tile " + (cls || ""), onclick: function () { buzz(); fn(); } }, icon(ic), h("span", null, label));
  }
  function goTab(id) { closeModal(); setTimeout(function () { show(id); }, 60); }
  function openMore() {
    var tabs = TABS.filter(function (t) { return BNAV.indexOf(t.id) < 0; });
    var who = state.me ? state.me.user : "?";
    openModal("MENU", null, h("div", { class: "stack" },
      h("div", { class: "tiles" }, tabs.map(function (t) {
        return tile(t.id, t.name, function () { goTab(t.id); }, current && current.id === t.id ? "on" : "");
      })),
      h("hr", { class: "sep" }),
      h("div", { class: "tiles" },
        tile("refresh", "ATUALIZAR DADOS", function () { closeModal(); refresh().then(function () { toast("Dados atualizados"); }); }),
        tile("star", "ATUALIZAR PAINEL" + (state.version && state.version.behind ? " (NEW)" : ""), function () { closeModal(); setTimeout(openUpdate, 80); }),
        installTile(),
        tile("power", "SAIR", logout, "danger")),
      h("p", { class: "muted center" }, "PLAYER " + who + " · v" + ((state.me && state.me.version) || "?") + " · " + $("uptime").textContent)), { menu: true });
  }
  function logout() { post("/api/logout").then(function () { location.href = "/login"; }); }

  // puxar a tela para baixo atualiza (como nos apps)
  (function () {
    var y0 = null, dy = 0, ptr = $("ptr");
    window.addEventListener("touchstart", function (e) {
      y0 = (window.scrollY <= 0 && !modalOpen && current && current.id !== "term") ? e.touches[0].clientY : null; dy = 0;
    }, { passive: true });
    window.addEventListener("touchmove", function (e) {
      if (y0 === null) return;
      dy = e.touches[0].clientY - y0;
      if (dy > 20) { ptr.classList.add("show"); ptr.classList.toggle("ready", dy > 90); ptr.style.height = Math.min(60, dy / 2) + "px"; }
    }, { passive: true });
    window.addEventListener("touchend", function () {
      if (y0 === null) return;
      if (dy > 90) { buzz(); refresh().then(function () { toast("Dados atualizados"); }); }
      ptr.classList.remove("show", "ready"); ptr.style.height = "";
      y0 = null;
    });
  })();

  // ------------------------------------------------------------------ teclado e inicio
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { closeModal(); return; }
    var tag = (e.target.tagName || "").toLowerCase();
    if (current && current.id === "term") return;   // no terminal, todas as teclas vao para o shell
    if (tag === "input" || tag === "select" || tag === "textarea" || e.ctrlKey || e.metaKey || e.altKey) return;
    var t = TABS.filter(function (x) { return x.key === e.key; })[0];
    if (t) { show(t.id); e.preventDefault(); }
    else if (e.key === "r" || e.key === "R") { refresh(); e.preventDefault(); }
  });

  function init() {
    add($("tabs"), TABS.map(function (t) {
      return h("button", { "data-id": t.id, onclick: function () { show(t.id); } }, h("span", { class: "k" }, t.key), t.name);
    }));
    $("btn-refresh").addEventListener("click", function () { if (current) { refresh().then(function () { toast("Dados atualizados"); }); } });
    $("btn-update").addEventListener("click", openUpdate);
    $("btn-logout").addEventListener("click", logout);
    buildBottomNav();
    document.addEventListener("vmp-installable", function () { if (current && current.id === "config") refresh(); });
    api("/api/me").then(function (me) {
      state.me = me;
      var start = (location.hash || "").slice(1);
      show(TABS.some(function (t) { return t.id === start; }) ? start : "dash");
      setTimeout(checkVersion, 1500);
      setInterval(checkVersion, 30 * 60 * 1000);
    });
    setInterval(function () { $("clock").textContent = new Date().toLocaleTimeString("pt-BR"); }, 1000);
    var rt = null;
    window.addEventListener("resize", function () {
      clearTimeout(rt);
      rt = setTimeout(function () { if (current && current.id !== "term" && VIEWS[current.id].after) refresh(); }, 300);
    });
  }
  init();
})();
