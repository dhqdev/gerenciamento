/* VM//PANEL - frontend (JS puro, sem dependencias) */
(function () {
  "use strict";

  // ------------------------------------------------------------------ utilitarios
  var $ = function (id) { return document.getElementById(id); };

  function h(tag, attrs) {
    var el = document.createElement(tag);
    var kids = Array.prototype.slice.call(arguments, 2);
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
    add(el, kids);
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

  var UNITS = ["B", "KB", "MB", "GB", "TB", "PB"];
  function bytes(n) {
    n = Number(n) || 0;
    var i = 0;
    while (n >= 1024 && i < UNITS.length - 1) { n /= 1024; i++; }
    return (i === 0 ? n.toFixed(0) : n.toFixed(n >= 100 ? 0 : 1)) + " " + UNITS[i];
  }
  function rate(n) { return bytes(n) + "/s"; }
  function pct(n) { return (Number(n) || 0).toFixed(1) + "%"; }
  function dur(s) {
    s = Math.floor(s || 0);
    var d = Math.floor(s / 86400), hh = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
    return (d ? d + "d " : "") + pad(hh) + "h" + pad(m) + "m";
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function when(ts) {
    var d = new Date(ts * 1000);
    return d.toLocaleDateString("pt-BR") + " " + d.toLocaleTimeString("pt-BR");
  }
  function level(p, w, c) { return p >= (c || 90) ? "crit" : p >= (w || 75) ? "warn" : "ok"; }
  function bar(p, width) {
    width = width || 24;
    p = Math.max(0, Math.min(100, Number(p) || 0));
    var full = Math.round(p / 100 * width);
    return "[" + "█".repeat(full) + "░".repeat(width - full) + "]";
  }
  function barLine(label, p, extra, width) {
    return h("div", { class: "row " + level(p) },
      h("span", { class: "bar" }, (label ? label + " " : "") + bar(p, width)),
      h("span", null, pct(p) + (extra ? "  " + extra : "")));
  }
  function box(title, cls) {
    var b = h("section", { class: "box " + (cls || "") }, h("h2", null, title));
    add(b, Array.prototype.slice.call(arguments, 2));
    return b;
  }
  function kv(pairs) {
    var d = h("div", { class: "kv" });
    pairs.forEach(function (p) { add(d, [h("span", null, p[0]), h("span", null, p[1] === undefined || p[1] === null ? "-" : p[1])]); });
    return d;
  }
  function table(cols, rows, opts) {
    opts = opts || {};
    var thead = h("tr", null, cols.map(function (c) {
      var th = h("th", { class: (c.num ? "num " : "") + (c.sort ? "sort" : "") }, c.t);
      if (c.sort && opts.onSort) th.addEventListener("click", function () { opts.onSort(c.sort); });
      return th;
    }));
    var body = rows.length ? rows : [h("tr", null, h("td", { colspan: cols.length, class: "dim" }, opts.empty || "(vazio)"))];
    return h("div", { class: "tbl-wrap" }, h("table", null, h("thead", null, thead), h("tbody", null, body)));
  }
  function td(v, cls) { return h("td", { class: cls || null }, v); }

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
      if (r.status === 401) { location.href = "/login"; throw new Error("401"); }
      return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || (d.errors || []).join("; ") || r.status); return d; });
    });
  }

  // ------------------------------------------------------------------ preferencias
  var prefs = { theme: "green", crt: true, boot: true };
  try {
    prefs.theme = localStorage.getItem("vmp_theme") || "green";
    prefs.crt = localStorage.getItem("vmp_crt") !== "0";
    prefs.boot = localStorage.getItem("vmp_bootanim") !== "0";
  } catch (_) {}
  function savePref(k, v) { try { localStorage.setItem(k, v); } catch (_) {} }
  function applyPrefs() {
    document.documentElement.setAttribute("data-theme", prefs.theme);
    document.body.classList.toggle("crt", prefs.crt);
  }
  applyPrefs();
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  // ------------------------------------------------------------------ graficos (canvas)
  function drawChart(canvas, series, opts) {
    opts = opts || {};
    var dpr = window.devicePixelRatio || 1;
    var w = canvas.clientWidth, hgt = canvas.clientHeight;
    if (!w || !hgt) return;
    canvas.width = w * dpr; canvas.height = hgt * dpr;
    var c = canvas.getContext("2d");
    c.scale(dpr, dpr);
    c.clearRect(0, 0, w, hgt);
    var fg = css("--fg"), faint = css("--fg-faint"), dim = css("--fg-dim");
    var max = opts.max || 0;
    series.forEach(function (s) { s.data.forEach(function (v) { if (v > max) max = v; }); });
    if (!max) max = 1;
    var left = opts.axis ? 64 : 0;
    var pw = w - left, ph = hgt - (opts.axis ? 16 : 2);
    c.strokeStyle = faint; c.setLineDash([2, 4]); c.lineWidth = 1;
    c.font = "14px " + css("--font-small");
    c.fillStyle = dim;
    for (var i = 0; i <= 4; i++) {
      var y = Math.round(1 + ph - ph * i / 4) + .5;
      c.beginPath(); c.moveTo(left, y); c.lineTo(w, y); c.stroke();
      if (opts.axis) c.fillText((opts.fmt || String)(max * i / 4), 2, Math.max(12, y + 4));
    }
    c.setLineDash([]);
    if (opts.labels && opts.labels.length) {
      var n = opts.labels.length, step = Math.max(1, Math.floor(n / 6));
      for (var j = 0; j < n; j += step) c.fillText(opts.labels[j], left + pw * j / Math.max(1, n - 1) - 10, hgt - 2);
    }
    series.forEach(function (s, idx) {
      var d = s.data;
      if (!d.length) return;
      c.strokeStyle = s.color || (idx === 0 ? fg : dim);
      c.lineWidth = 1.6;
      c.shadowColor = c.strokeStyle; c.shadowBlur = 6;
      if (s.dash) c.setLineDash([4, 3]); else c.setLineDash([]);
      c.beginPath();
      d.forEach(function (v, k) {
        var x = left + (d.length === 1 ? pw : pw * k / (d.length - 1));
        var yy = 1 + ph - ph * Math.min(v, max) / max;
        if (k) c.lineTo(x, yy); else c.moveTo(x, yy);
      });
      c.stroke();
      if (s.fill) {
        c.lineTo(left + pw, 1 + ph); c.lineTo(left, 1 + ph); c.closePath();
        c.globalAlpha = .12; c.fillStyle = c.strokeStyle; c.fill(); c.globalAlpha = 1;
      }
      c.shadowBlur = 0;
    });
  }

  // historico ao vivo (ultimos ~5 min, coletados no navegador)
  var live = { cpu: [], mem: [], rx: [], tx: [], rd: [], wr: [] };
  function pushLive(k, v) { live[k].push(v); if (live[k].length > 150) live[k].shift(); }

  // ------------------------------------------------------------------ console de comandos
  var out = $("out");
  function print(text, cls) {
    out.appendChild(h("div", { class: cls || null }, text));
    out.scrollTop = out.scrollHeight;
  }

  // ------------------------------------------------------------------ views
  var state = { me: null, overview: null, procSort: "cpu", procQuery: "", dockerQuery: "", histRange: "24h" };

  var TABS = [
    { id: "dash", key: "1", name: "PAINEL", every: 2000 },
    { id: "docker", key: "2", name: "DOCKER", every: 5000 },
    { id: "procs", key: "3", name: "PROCESSOS", every: 3000 },
    { id: "net", key: "4", name: "REDE", every: 3000 },
    { id: "disks", key: "5", name: "DISCOS", every: 5000 },
    { id: "system", key: "6", name: "SISTEMA", every: 15000 },
    { id: "security", key: "7", name: "SEGURANCA", every: 30000 },
    { id: "history", key: "8", name: "HISTORICO", every: 60000 },
    { id: "config", key: "9", name: "CONFIG", every: 0 }
  ];
  var current = null, timer = null, body = null;

  function show(id) {
    var tab = TABS.filter(function (t) { return t.id === id; })[0] || TABS[0];
    current = tab;
    try { history.replaceState(null, "", "#" + tab.id); } catch (_) {}
    Array.prototype.forEach.call($("tabs").children, function (b) { b.classList.toggle("on", b.dataset.id === tab.id); });
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
    Promise.resolve(VIEWS[tab.id].load()).then(function (d) {
      if (tab !== current) return;
      var node = VIEWS[tab.id].render(d);
      clear(body).appendChild(node);
      if (VIEWS[tab.id].after) VIEWS[tab.id].after(d);
    }).catch(function (e) {
      if (tab !== current) return;
      clear(body).appendChild(box("ERRO", "", h("p", { class: "crit" }, String(e.message || e))));
    }).then(function () {
      if (tab === current && tab.every && !document.hidden) timer = setTimeout(refresh, tab.every);
    });
  }
  document.addEventListener("visibilitychange", function () { if (!document.hidden && current) refresh(); });

  function containerActions(c) {
    var running = c.state === "running";
    return h("span", null,
      running ? null : h("button", { class: "btn small", title: "iniciar", onclick: function () { dockerAct(c.name, "start"); } }, "▶"),
      running ? h("button", { class: "btn small", title: "reiniciar", onclick: function () { dockerAct(c.name, "restart"); } }, "↻") : null,
      running ? h("button", { class: "btn small danger", title: "parar", onclick: function () { dockerAct(c.name, "stop"); } }, "■") : null,
      " ",
      h("button", { class: "btn small", title: "logs", onclick: function () { openLogs(c.name); } }, "LOG"),
      h("button", { class: "btn small", title: "detalhes", onclick: function () { openInspect(c.name); } }, "INFO"));
  }
  function dockerAct(name, act) {
    if ((act === "stop" || act === "restart") && !confirm(act.toUpperCase() + " " + name + "?")) return;
    print("> docker " + act + " " + name + " ...", "dim");
    return post("/api/docker/action", { id: name, action: act }).then(function () {
      print("OK: " + name + " " + act);
      if (current) refresh();
    }).catch(function (e) { print("ERRO: " + e.message, "crit"); });
  }
  function stateBadge(s) {
    return h("span", { class: "badge " + (s === "running" ? "run" : s === "exited" || s === "dead" ? "stop" : "other") }, s);
  }

  // ---------- modal
  var modalTimer = null;
  function openModal(title, tools, content) {
    $("modal-title").textContent = title;
    add(clear($("modal-tools")), [tools, h("button", { class: "btn", onclick: closeModal }, "[ FECHAR ESC ]")]);
    add(clear($("modal-body")), [content]);
    $("modal").classList.remove("hidden");
  }
  function closeModal() { clearInterval(modalTimer); $("modal").classList.add("hidden"); }
  $("modal").addEventListener("click", function (e) { if (e.target.id === "modal") closeModal(); });

  function openLogs(name) {
    var pre = h("pre", { class: "logs" }, "carregando...");
    var tail = h("select", null, [100, 200, 500, 1000, 2000].map(function (n) { return h("option", { value: n, selected: n === 200 }, n + " linhas"); }));
    var follow = h("input", { type: "checkbox", checked: true });
    var filter = h("input", { placeholder: "filtrar (grep)" });
    var lastText = "";
    function paint() {
      var q = filter.value.toLowerCase();
      var txt = q ? lastText.split("\n").filter(function (l) { return l.toLowerCase().indexOf(q) >= 0; }).join("\n") : lastText;
      var atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
      pre.textContent = txt || "(sem logs)";
      if (atBottom) pre.scrollTop = pre.scrollHeight;
    }
    function load() {
      api("/api/docker/logs?id=" + encodeURIComponent(name) + "&tail=" + tail.value).then(function (d) {
        lastText = d.logs; paint();
      }).catch(function (e) { pre.textContent = "ERRO: " + e.message; });
    }
    tail.addEventListener("change", load);
    filter.addEventListener("input", paint);
    openModal("LOGS: " + name, [tail, h("label", { class: "chk" }, follow, "seguir (3s)"), filter], pre);
    load();
    setTimeout(function () { pre.scrollTop = pre.scrollHeight; }, 300);
    clearInterval(modalTimer);
    modalTimer = setInterval(function () { if (follow.checked) load(); }, 3000);
  }
  function openInspect(name) {
    api("/api/docker/inspect?id=" + encodeURIComponent(name)).then(function (d) {
      openModal("CONTAINER: " + d.name, null, h("div", null,
        kv([["ID", d.id], ["Imagem", d.image], ["Status", d.status], ["Health", d.health || "-"],
            ["Criado", d.created], ["Iniciado", d.started], ["Restarts", d.restart_count],
            ["Politica restart", d.restart_policy || "-"], ["Redes", d.networks.join(", ")], ["Comando", d.cmd]]),
        h("h3", null, "VOLUMES / MOUNTS"),
        table([{ t: "ORIGEM" }, { t: "DESTINO" }, { t: "RW" }], d.mounts.map(function (m) {
          return h("tr", null, td(m.src, "cmd"), td(m.dst), td(m.rw ? "rw" : "ro"));
        }))));
    }).catch(function (e) { print("ERRO: " + e.message, "crit"); });
  }
  function openImages() {
    api("/api/docker/images").then(function (imgs) {
      var total = imgs.reduce(function (a, i) { return a + i.size; }, 0);
      openModal("IMAGENS DOCKER (" + imgs.length + " / " + bytes(total) + ")", null,
        table([{ t: "ID" }, { t: "TAGS" }, { t: "TAMANHO", num: 1 }, { t: "CRIADA" }], imgs.map(function (i) {
          return h("tr", null, td(i.id), td(i.tags.join(", "), "cmd"), td(bytes(i.size), "num"), td(when(i.created)));
        })));
    }).catch(function (e) { print("ERRO: " + e.message, "crit"); });
  }

  var VIEWS = {};

  // ---------- PAINEL
  VIEWS.dash = {
    load: function () { return api("/api/overview"); },
    render: function (d) {
      state.overview = d;
      var n = d.now || {};
      if (!n.cpu) return box("AGUARDANDO", "", h("p", null, "Coletando a primeira amostra..."));
      var s = d.static, m = n.memory;
      pushLive("cpu", n.cpu.percent); pushLive("mem", m.percent);
      pushLive("rx", n.net.rx_rate); pushLive("tx", n.net.tx_rate);
      pushLive("rd", n.io.read_rate); pushLive("wr", n.io.write_rate);
      updateHeader(d);

      var cores = h("div", { class: "cores" }, n.cpu.cores.map(function (p, i) {
        return h("div", { class: level(p) }, "#" + pad(i) + " " + bar(p, 8) + " " + Math.round(p) + "%");
      }));
      var alerts = (d.alerts || []).slice();
      if (d.reboot_required) alerts.push("Reinicio pendente (atualizacoes do kernel)");
      var o = d.oracle || {};
      var dk = d.docker || {};

      return h("div", { class: "grid" },
        box("CPU", "",
          h("div", { class: "row" }, h("span", { class: "big " + level(n.cpu.percent) }, pct(n.cpu.percent)),
            h("span", { class: "dim" }, "LOAD " + n.load.map(function (x) { return x.toFixed(2); }).join(" "), h("br"),
              s.cpu_count + " NUCLEOS", n.cpu.steal > 0.5 ? h("span", { class: "warn" }, " STEAL " + pct(n.cpu.steal)) : null)),
          h("div", { class: "bar " + level(n.cpu.percent) }, bar(n.cpu.percent, 34)),
          h("canvas", { class: "spark", id: "sp-cpu" }), cores),
        box("MEMORIA", "",
          h("div", { class: "row" }, h("span", { class: "big " + level(m.percent) }, pct(m.percent)),
            h("span", { class: "dim" }, bytes(m.used) + " / " + bytes(m.total), h("br"), "LIVRE " + bytes(m.available))),
          h("div", { class: "bar " + level(m.percent) }, bar(m.percent, 34)),
          h("canvas", { class: "spark", id: "sp-mem" }),
          kv([["CACHE", bytes(m.cached)], ["BUFFERS", bytes(m.buffers)],
              ["SWAP", m.swap_total ? bytes(m.swap_used) + " / " + bytes(m.swap_total) + " (" + pct(m.swap_percent) + ")" : "desativado"]])),
        box("DISCOS", "", n.disks.map(function (x) {
          return h("div", null, h("div", { class: "row" }, h("span", null, x.mount), h("span", { class: "dim" }, bytes(x.used) + " / " + bytes(x.total))),
            barLine("", x.percent, null, 28));
        }), h("div", { class: "row dim mt" }, h("span", null, "IO ↓ " + rate(n.io.read_rate)), h("span", null, "↑ " + rate(n.io.write_rate)))),
        box("REDE", "",
          h("div", { class: "row" }, h("span", { class: "big" }, "↓" + rate(n.net.rx_rate)), h("span", { class: "big dim" }, "↑" + rate(n.net.tx_rate))),
          h("canvas", { class: "spark", id: "sp-net" }),
          n.net.ifaces.map(function (i) {
            return h("div", { class: "row dim" }, h("span", null, i.name), h("span", null, "RX " + bytes(i.rx_total) + "  TX " + bytes(i.tx_total)));
          })),
        box("DOCKER", "", dk.available ? [
          h("div", { class: "row" }, h("span", { class: "big" }, (dk.info.running || 0) + "/" + (dk.info.containers || 0)),
            h("span", { class: "dim" }, "RODANDO", h("br"), dk.info.images + " IMAGENS · v" + dk.info.version)),
          dk.info.stopped ? h("div", { class: "warn" }, dk.info.stopped + " container(s) parado(s)") : null,
          table([{ t: "TOP CPU" }, { t: "CPU", num: 1 }, { t: "MEM", num: 1 }], dk.top.map(function (c) {
            return h("tr", null, td(c.name), td(pct(c.cpu), "num"), td(bytes(c.mem_used), "num"));
          }))
        ] : h("p", { class: "dim" }, "Docker nao disponivel neste host.")),
        box("SISTEMA", "",
          kv([["HOST", s.hostname], ["OS", s.os], ["KERNEL", s.kernel], ["ARQ", s.arch], ["CPU", s.cpu_model],
              ["PROCESSOS", n.procs.total + " (" + n.procs.running + " exec" + (n.procs.zombie ? ", " + n.procs.zombie + " zumbi" : "") + ")"],
              ["TEMP", n.temps.length ? n.temps.map(function (t) { return t.c + "°C"; }).join(" ") : "n/d"]])),
        box("ALERTAS", "", alerts.length ? alerts.map(function (a) { return h("div", { class: "warn" }, "! " + a); })
          : h("div", null, "TUDO NOMINAL. NENHUM ALERTA ATIVO.")),
        box("ORACLE ALWAYS FREE", "",
          h("p", { class: "dim mb" }, "A Oracle pode recuperar instancias ociosas (CPU p95 < 20% em 7 dias)."),
          o.cpu_p95 === null || o.cpu_p95 === undefined ? h("div", { class: "dim" }, "Coletando dados... (" + (o.days || 0) + " dias)") :
            kv([["CPU p95 7d", h("span", { class: o.cpu_p95 < 20 ? "warn" : "ok" }, pct(o.cpu_p95))],
                ["MEM p95 7d", o.mem_p95 === null ? "-" : pct(o.mem_p95)], ["DADOS", o.days + " dias"],
                ["STATUS", o.at_risk ? h("span", { class: "warn" }, "RISCO DE RECUPERACAO") : "OK"]])));
    },
    after: function () {
      drawChart($("sp-cpu"), [{ data: live.cpu, fill: true }], { max: 100 });
      drawChart($("sp-mem"), [{ data: live.mem, fill: true }], { max: 100 });
      drawChart($("sp-net"), [{ data: live.rx, fill: true }, { data: live.tx, dash: true }]);
    }
  };

  function updateHeader(d) {
    var s = d.static;
    clear($("hostline"));
    add($("hostline"), [h("b", null, s.hostname), " · " + s.os + " · " + s.arch + " · " + s.cpu_count + " vCPU · ",
      bytes(d.now.memory.total) + " RAM · USER ", h("b", null, (state.me && state.me.user) || "?"), " · v" + d.version]);
    $("uptime").textContent = "UPTIME " + dur(d.now.uptime);
    $("ps1").textContent = ((state.me && state.me.user) || "user") + "@" + s.hostname + ":~$";
  }

  // ---------- DOCKER
  VIEWS.docker = {
    setup: function () {
      var q = h("input", { placeholder: "filtrar containers", value: state.dockerQuery });
      q.addEventListener("input", function () { state.dockerQuery = q.value; refresh(); });
      return h("div", { class: "toolbar" }, q,
        h("button", { class: "btn", onclick: openImages }, "[ IMAGENS ]"),
        h("button", { class: "btn", onclick: function () {
          api("/api/docker/df").then(function (d) {
            openModal("USO DE DISCO DO DOCKER", null, kv([["Imagens", bytes(d.images)], ["  recuperavel", bytes(d.images_reclaimable)],
              ["Containers (rw)", bytes(d.containers)], ["Volumes", bytes(d.volumes) + " (" + d.volumes_count + ")"], ["Build cache", bytes(d.build_cache)]]));
          }).catch(function (e) { print("ERRO: " + e.message, "crit"); });
        } }, "[ DISCO ]"));
    },
    load: function () { return api("/api/docker"); },
    render: function (d) {
      if (!d.available) return box("DOCKER", "", h("p", { class: "warn" }, d.error || "Docker indisponivel"),
        h("p", { class: "dim" }, "Instale o Docker e rode 'vmpanel doctor' para dar acesso ao painel."));
      var q = state.dockerQuery.toLowerCase();
      var list = d.containers.filter(function (c) { return !q || (c.name + c.image + c.project).toLowerCase().indexOf(q) >= 0; });
      var i = d.info;
      return h("div", null,
        h("p", { class: "dim" }, "Docker v" + i.version + " · " + i.running + " rodando · " + i.stopped + " parados · " +
          i.images + " imagens · driver " + i.driver),
        table([{ t: "ESTADO" }, { t: "NOME" }, { t: "PROJETO" }, { t: "IMAGEM" }, { t: "CPU", num: 1 }, { t: "MEMORIA", num: 1 },
               { t: "REDE RX/TX", num: 1 }, { t: "PORTAS" }, { t: "STATUS" }, { t: "ACOES" }],
          list.map(function (c) {
            return h("tr", null, td(stateBadge(c.state)), td(c.name), td(c.project || "-", "dim"), td(c.image, "cmd"),
              td(c.state === "running" ? pct(c.cpu) : "-", "num " + level(c.cpu)),
              td(c.state === "running" ? bytes(c.mem_used) + (c.mem_limit ? " (" + pct(c.mem_percent) + ")" : "") : "-", "num"),
              td(c.state === "running" ? bytes(c.net_rx) + " / " + bytes(c.net_tx) : "-", "num"),
              td(c.ports.join(" ") || "-", "cmd"), td(c.status, "dim"), td(containerActions(c)));
          }), { empty: "nenhum container" }));
    }
  };

  // ---------- PROCESSOS
  VIEWS.procs = {
    setup: function () {
      var q = h("input", { placeholder: "buscar (nome, pid, usuario)", value: state.procQuery });
      q.addEventListener("input", function () { state.procQuery = q.value; refresh(); });
      var s = h("select", null, [["cpu", "ordenar: CPU"], ["mem", "ordenar: MEMORIA"], ["pid", "ordenar: PID"]].map(function (o) {
        return h("option", { value: o[0], selected: o[0] === state.procSort }, o[1]);
      }));
      s.addEventListener("change", function () { state.procSort = s.value; refresh(); });
      return h("div", { class: "toolbar" }, q, s);
    },
    load: function () { return api("/api/processes?sort=" + state.procSort + "&q=" + encodeURIComponent(state.procQuery)); },
    render: function (list) {
      return table([{ t: "PID", num: 1, sort: "pid" }, { t: "USUARIO" }, { t: "CPU%", num: 1, sort: "cpu" }, { t: "MEM%", num: 1, sort: "mem" },
                    { t: "RSS", num: 1 }, { t: "THR", num: 1 }, { t: "S" }, { t: "COMANDO" }],
        list.map(function (p) {
          return h("tr", null, td(p.pid, "num"), td(p.user), td(p.cpu.toFixed(1), "num " + level(p.cpu, 50, 90)), td(p.mem.toFixed(1), "num " + level(p.mem, 30, 60)),
            td(bytes(p.rss), "num"), td(p.threads, "num"), td(p.state), td(p.cmd, "cmd"));
        }), { onSort: function (k) { state.procSort = k; show("procs"); } });
    }
  };

  // ---------- REDE
  VIEWS.net = {
    load: function () { return api("/api/network"); },
    render: function (d) {
      var st = d.conns.states;
      return h("div", { class: "grid wide" },
        box("INTERFACES", "span2", table([{ t: "IFACE" }, { t: "↓ RX/s", num: 1 }, { t: "↑ TX/s", num: 1 }, { t: "RX TOTAL", num: 1 }, { t: "TX TOTAL", num: 1 }, { t: "ERROS", num: 1 }],
          d.ifaces.map(function (i) {
            return h("tr", null, td(i.name), td(rate(i.rx_rate), "num"), td(rate(i.tx_rate), "num"), td(bytes(i.rx_total), "num"), td(bytes(i.tx_total), "num"), td(i.errors, "num"));
          }))),
        box("ENDERECOS IP", "", table([{ t: "IFACE" }, { t: "TIPO" }, { t: "ENDERECO" }], d.ips.map(function (a) {
          return h("tr", null, td(a.iface), td(a.family), td(a.addr));
        }))),
        box("CONEXOES TCP", "", kv(Object.keys(st).sort().map(function (k) { return [k, st[k]]; })),
          h("h3", null, "TOP IPS CONECTADOS"),
          table([{ t: "IP" }, { t: "CONEXOES", num: 1 }], d.conns.top_peers.map(function (p) { return h("tr", null, td(p.ip), td(p.count, "num")); }))),
        box("PORTAS ABERTAS (LISTEN)", "span2", table([{ t: "PROTO" }, { t: "ENDERECO" }, { t: "PORTA", num: 1 }, { t: "EXPOSTA?" }],
          d.ports.map(function (p) {
            var pub = !/^(127\.|::1|localhost|\[?::1)/.test(p.addr) && !/%lo$/.test(p.addr);
            return h("tr", null, td(p.proto), td(p.addr), td(p.port, "num"), td(pub ? "PUBLICA" : "local", pub ? "warn" : "dim"));
          }))));
    }
  };

  // ---------- DISCOS
  VIEWS.disks = {
    load: function () { return api("/api/overview"); },
    render: function (d) {
      var n = d.now;
      return h("div", { class: "grid wide" },
        box("SISTEMAS DE ARQUIVOS", "span2", table([{ t: "MONTAGEM" }, { t: "DISPOSITIVO" }, { t: "TIPO" }, { t: "USO" }, { t: "USADO", num: 1 }, { t: "LIVRE", num: 1 }, { t: "TOTAL", num: 1 }, { t: "INODES", num: 1 }],
          n.disks.map(function (x) {
            return h("tr", null, td(x.mount), td(x.device, "dim"), td(x.fs, "dim"), td(bar(x.percent, 20) + " " + pct(x.percent), "bar " + level(x.percent, 75, 90)),
              td(bytes(x.used), "num"), td(bytes(x.free), "num"), td(bytes(x.total), "num"), td(pct(x.inodes_percent), "num " + level(x.inodes_percent)));
          }))),
        box("ATIVIDADE DE DISCO", "span2", h("canvas", { class: "chart", id: "ch-io" }),
          h("p", { class: "dim" }, "linha cheia = leitura · tracejada = escrita (ultimos minutos)"),
          table([{ t: "DISCO" }, { t: "LEITURA/s", num: 1 }, { t: "ESCRITA/s", num: 1 }, { t: "OCUPADO", num: 1 }], n.io.devices.map(function (x) {
            return h("tr", null, td(x.name), td(rate(x.read_rate), "num"), td(rate(x.write_rate), "num"), td(pct(x.busy), "num " + level(x.busy)));
          }))));
    },
    after: function (d) {
      pushLive("rd", d.now.io.read_rate); pushLive("wr", d.now.io.write_rate);
      drawChart($("ch-io"), [{ data: live.rd, fill: true }, { data: live.wr, dash: true }], { axis: true, fmt: rate });
    }
  };

  // ---------- SISTEMA
  VIEWS.system = {
    load: function () { return api("/api/system"); },
    render: function (d) {
      var s = d.static, u = d.updates;
      return h("div", { class: "grid wide" },
        box("MAQUINA", "", kv([["Hostname", s.hostname], ["Sistema", s.os], ["Kernel", s.kernel], ["Arquitetura", s.arch],
          ["CPU", s.cpu_model], ["vCPUs", s.cpu_count], ["Python", s.python],
          ["Temperaturas", d.temps.length ? d.temps.map(function (t) { return t.name + " " + t.c + "°C"; }).join(", ") : "n/d"]])),
        box("ATUALIZACOES", "",
          u.manager ? h("div", null,
            h("div", { class: "big " + (u.count ? "warn" : "") }, u.count + " pacote(s)"),
            u.security ? h("div", { class: "crit" }, u.security + " de seguranca") : null,
            d.reboot_required ? h("div", { class: "warn" }, "! REINICIO NECESSARIO") : null,
            h("p", { class: "dim mono" }, (u.packages || []).join(" ") || "sistema em dia"),
            h("p", { class: "dim" }, "Para atualizar: sudo " + (u.manager === "apt" ? "apt update && sudo apt upgrade" : "dnf upgrade")))
            : h("p", { class: "dim" }, "Gerenciador de pacotes nao detectado.")),
        box("SERVICOS", "", table([{ t: "SERVICO" }, { t: "ESTADO" }, { t: "DESDE" }], d.services.map(function (x) {
          return h("tr", null, td(x.name), td(x.active + "/" + x.sub, x.active === "active" ? "" : x.active === "failed" ? "crit" : "warn"), td(x.since, "dim"));
        }))),
        box("UNIDADES COM FALHA", "", d.failed.length ? table([{ t: "UNIDADE" }, { t: "DESCRICAO" }], d.failed.map(function (f) {
          return h("tr", null, td(f.unit, "crit"), td(f.desc));
        })) : h("p", null, "Nenhuma unidade systemd com falha.")));
    }
  };

  // ---------- SEGURANCA
  VIEWS.security = {
    load: function () { return Promise.all([api("/api/security"), api("/api/me")]); },
    render: function (r) {
      var d = r[0], me = r[1], ssh = d.ssh;
      var kinds = { login_ok: "LOGIN OK", login_fail: "LOGIN FALHOU", ip_locked: "IP BLOQUEADO", alert: "ALERTA", settings: "CONFIG", start: "INICIO", sessions_revoked: "SESSOES ENCERRADAS" };
      return h("div", { class: "grid wide" },
        box("PAINEL", "", kv([["Usuario", me.user], ["2FA (TOTP)", me.totp ? "ATIVO" : h("span", { class: "warn" }, "DESATIVADO - rode 'sudo vmpanel 2fa-on'")],
            ["Seu IP", me.ip], ["Sessoes ativas", d.sessions.length]]),
          table([{ t: "IP" }, { t: "INICIO" }, { t: "NAVEGADOR" }], d.sessions.map(function (s) {
            return h("tr", null, td(s.ip), td(when(s.created)), td(s.ua, "cmd"));
          })),
          h("p", null, h("button", { class: "btn danger", onclick: function () {
            if (confirm("Encerrar TODAS as sessoes (inclusive esta)?")) post("/api/sessions/revoke").then(function () { location.href = "/login"; });
          } }, "[ ENCERRAR TODAS AS SESSOES ]"))),
        box("SSH - ULTIMAS 24H", "", !ssh.available ? h("p", { class: "dim" }, "Sem acesso ao journal do SSH.") : h("div", null,
          h("div", { class: "big " + (ssh.failed_24h > 100 ? "warn" : "") }, ssh.failed_24h + " falhas"),
          ssh.failed_24h > 50 ? h("p", { class: "dim" }, "Dica: use so chave SSH (PasswordAuthentication no) e instale o fail2ban.") : null,
          table([{ t: "IP ATACANTE" }, { t: "TENTATIVAS", num: 1 }], ssh.top_ips.map(function (x) { return h("tr", null, td(x.ip), td(x.count, "num")); })),
          h("h3", null, "USUARIOS TENTADOS"),
          h("p", { class: "mono dim" }, ssh.top_users.map(function (x) { return x.user + "(" + x.count + ")"; }).join(" ") || "-"),
          h("h3", null, "LOGINS ACEITOS"),
          h("pre", { class: "logs" }, ssh.accepted.join("\n") || "-"))),
        box("USUARIOS LOGADOS NA VM", "", h("pre", { class: "logs" }, d.who.join("\n") || "ninguem via terminal")),
        box("AUDITORIA DO PAINEL", "span2", table([{ t: "QUANDO" }, { t: "EVENTO" }, { t: "IP" }, { t: "DETALHE" }], d.events.map(function (e) {
          return h("tr", null, td(when(e.ts)), td(kinds[e.kind] || e.kind.toUpperCase(), /fail|lock|alert/.test(e.kind) ? "warn" : ""), td(e.ip || "-"), td(e.detail, "cmd"));
        }))));
    }
  };

  // ---------- HISTORICO
  VIEWS.history = {
    setup: function () {
      return h("div", { class: "toolbar" }, ["1h", "6h", "24h", "7d", "30d"].map(function (r) {
        return h("button", { class: "btn" + (r === state.histRange ? " on" : ""), onclick: function () { state.histRange = r; show("history"); } },
          (r === state.histRange ? "> " : "") + r.toUpperCase());
      }));
    },
    load: function () { return api("/api/history?range=" + state.histRange); },
    render: function (rows) {
      if (!rows.length) return box("HISTORICO", "", h("p", null, "Sem dados ainda. O painel grava uma amostra por minuto; volte em alguns minutos."));
      function avg(k) { return rows.reduce(function (a, r) { return a + (r[k] || 0); }, 0) / rows.length; }
      function mx(k) { return rows.reduce(function (a, r) { return Math.max(a, r[k] || 0); }, 0); }
      return h("div", { class: "grid wide" },
        box("CPU %", "", h("canvas", { class: "chart", id: "h-cpu" }), h("p", { class: "dim" }, "media " + pct(avg("cpu")) + " · pico " + pct(mx("cpu_max")) + " · tracejado = pico")),
        box("MEMORIA %", "", h("canvas", { class: "chart", id: "h-mem" }), h("p", { class: "dim" }, "media " + pct(avg("mem")) + " · max " + pct(mx("mem")) + " · tracejado = swap")),
        box("REDE", "", h("canvas", { class: "chart", id: "h-net" }), h("p", { class: "dim" }, "↓ media " + rate(avg("rx")) + " · ↑ media " + rate(avg("tx")))),
        box("DISCO / (%) E LOAD", "", h("canvas", { class: "chart", id: "h-disk" }), h("p", { class: "dim" }, "disco atual " + pct(rows[rows.length - 1].disk) + " · load max " + mx("load1").toFixed(2) + " (tracejado)")));
    },
    after: function (rows) {
      if (!rows.length) return;
      var lbl = rows.map(function (r) {
        var d = new Date(r.ts * 1000);
        return state.histRange === "7d" || state.histRange === "30d" ? pad(d.getDate()) + "/" + pad(d.getMonth() + 1) : pad(d.getHours()) + ":" + pad(d.getMinutes());
      });
      function col(k) { return rows.map(function (r) { return r[k] || 0; }); }
      drawChart($("h-cpu"), [{ data: col("cpu"), fill: true }, { data: col("cpu_max"), dash: true }], { max: 100, axis: true, labels: lbl, fmt: function (v) { return Math.round(v) + "%"; } });
      drawChart($("h-mem"), [{ data: col("mem"), fill: true }, { data: col("swap"), dash: true }], { max: 100, axis: true, labels: lbl, fmt: function (v) { return Math.round(v) + "%"; } });
      drawChart($("h-net"), [{ data: col("rx"), fill: true }, { data: col("tx"), dash: true }], { axis: true, labels: lbl, fmt: rate });
      var maxLoad = Math.max.apply(null, col("load1").concat([1]));
      drawChart($("h-disk"), [{ data: col("disk"), fill: true }, { data: col("load1").map(function (v) { return v / maxLoad * 100; }), dash: true }],
        { max: 100, axis: true, labels: lbl, fmt: function (v) { return Math.round(v) + "%"; } });
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
      var form = h("form", null,
        h("div", { class: "grid wide" },
          box("LIMITES DE ALERTA", "",
            num("alert_cpu", "CPU acima de (%)"), num("alert_mem", "Memoria acima de (%)"), num("alert_disk", "Disco acima de (%)"),
            num("alert_minutes", "Por quantos minutos seguidos (CPU/MEM)"), num("alert_cooldown_min", "Intervalo minimo entre alertas iguais (min)"),
            chk("alert_container_down", "Avisar quando um container parar"), chk("alert_login", "Avisar a cada login no painel"),
            chk("oracle_idle_watch", "Vigiar regra de instancia ociosa da Oracle")),
          box("NOTIFICACOES", "",
            txt("discord_webhook", "Webhook do Discord", "https://discord.com/api/webhooks/..."),
            txt("telegram_token", "Token do bot do Telegram", "123456:ABC..."),
            txt("telegram_chat_id", "Chat ID do Telegram", "123456789"),
            h("p", { class: "dim" }, "Os segredos aparecem como ******** depois de salvos."),
            h("button", { class: "btn", type: "button", onclick: function () {
              msg.textContent = "Enviando teste..."; msg.className = "";
              post("/api/settings/test").then(function () { msg.textContent = "Teste enviado!"; })
                .catch(function (e) { msg.textContent = "Falhou: " + e.message; msg.className = "crit"; });
            } }, "[ ENVIAR TESTE ]")),
          box("APARENCIA (neste navegador)", "",
            h("label", { class: "f" }, h("span", null, "Tema de fosforo"), themeSelect()),
            h("label", { class: "chk" }, h("input", { type: "checkbox", checked: prefs.crt, onchange: function (e) { prefs.crt = e.target.checked; savePref("vmp_crt", prefs.crt ? "1" : "0"); applyPrefs(); } }), "Efeito CRT (scanlines)"),
            h("label", { class: "chk" }, h("input", { type: "checkbox", checked: prefs.boot, onchange: function (e) { prefs.boot = e.target.checked; savePref("vmp_bootanim", prefs.boot ? "1" : "0"); } }), "Animacao de boot no login")),
          box("LINHA DE COMANDO NA VM", "", h("pre", { class: "logs" },
            "sudo vmpanel status      # estado do servico\n" +
            "sudo vmpanel logs        # logs ao vivo\n" +
            "sudo vmpanel update      # atualiza do GitHub\n" +
            "sudo vmpanel passwd      # troca usuario/senha\n" +
            "sudo vmpanel 2fa-on      # ativa 2FA\n" +
            "sudo vmpanel domain X    # troca o dominio\n" +
            "sudo vmpanel doctor      # diagnostico\n" +
            "sudo vmpanel uninstall   # remove o painel"))),
        h("p", null, h("button", { class: "btn", type: "submit" }, "[ SALVAR CONFIGURACOES ]")), msg);
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        var data = {};
        Array.prototype.forEach.call(form.querySelectorAll("input[name]"), function (i) {
          data[i.name] = i.type === "checkbox" ? i.checked : i.value;
        });
        post("/api/settings", data).then(function () { msg.textContent = "SALVO."; msg.className = ""; })
          .catch(function (er) { msg.textContent = "ERRO: " + er.message; msg.className = "crit"; });
      });
      return form;
    }
  };

  var THEMES = ["green", "amber", "cyan", "white", "pink"];
  function themeSelect() {
    var s = h("select", null, THEMES.map(function (t) { return h("option", { value: t, selected: t === prefs.theme }, t.toUpperCase()); }));
    s.addEventListener("change", function () { setTheme(s.value); });
    return s;
  }
  function setTheme(t) {
    if (THEMES.indexOf(t) < 0) return false;
    prefs.theme = t; savePref("vmp_theme", t); applyPrefs();
    if (current && VIEWS[current.id].after && state.overview) refresh();
    return true;
  }

  // ------------------------------------------------------------------ comandos
  var COMMANDS = {
    help: function () {
      print([
        "COMANDOS DISPONIVEIS:",
        "  1-9 | goto <aba>            troca de aba (painel, docker, processos, rede, discos, sistema, seguranca, historico, config)",
        "  ps [filtro]                 processos (abre a aba com o filtro)",
        "  start|stop|restart <ct>     controla um container docker",
        "  logs <ct>                   logs de um container",
        "  inspect <ct>                detalhes de um container",
        "  images                      imagens docker",
        "  free | df | uptime | whoami resumo rapido no console",
        "  theme <green|amber|cyan|white|pink>",
        "  crt on|off                  efeito de scanlines",
        "  clear                       limpa o console",
        "  logout                      sair",
        "ATALHOS: teclas 1-9 trocam de aba, '/' foca o console, ESC fecha janelas."
      ].join("\n"));
    },
    clear: function () { clear(out); },
    goto: function (a) {
      var t = TABS.filter(function (x) { return x.id === a[0] || x.name.toLowerCase() === (a[0] || "").toLowerCase() || x.key === a[0]; })[0];
      if (t) show(t.id); else print("aba desconhecida: " + a[0], "warn");
    },
    ps: function (a) { state.procQuery = a.join(" "); show("procs"); },
    start: function (a) { if (!a[0]) return print("uso: start <container>", "warn"); dockerAct(a[0], "start"); },
    stop: function (a) { if (!a[0]) return print("uso: stop <container>", "warn"); dockerAct(a[0], "stop"); },
    restart: function (a) { if (!a[0]) return print("uso: restart <container>", "warn"); dockerAct(a[0], "restart"); },
    logs: function (a) { if (!a[0]) return print("uso: logs <container>", "warn"); openLogs(a[0]); },
    inspect: function (a) { if (!a[0]) return print("uso: inspect <container>", "warn"); openInspect(a[0]); },
    images: function () { openImages(); },
    theme: function (a) { if (!setTheme(a[0])) print("temas: " + THEMES.join(", "), "warn"); },
    crt: function (a) { prefs.crt = a[0] !== "off"; savePref("vmp_crt", prefs.crt ? "1" : "0"); applyPrefs(); },
    whoami: function () { print((state.me && state.me.user) + " (ip " + (state.me && state.me.ip) + ")"); },
    uptime: function () { api("/api/overview").then(function (d) { print("up " + dur(d.now.uptime) + ", load " + d.now.load.join(" ")); }); },
    free: function () {
      api("/api/overview").then(function (d) {
        var m = d.now.memory;
        print("MEM  total " + bytes(m.total) + "  usado " + bytes(m.used) + "  livre " + bytes(m.available) + "\nSWAP total " + bytes(m.swap_total) + "  usado " + bytes(m.swap_used));
      });
    },
    df: function () {
      api("/api/overview").then(function (d) {
        print(d.now.disks.map(function (x) { return (x.mount + "                ").slice(0, 16) + bar(x.percent, 20) + " " + pct(x.percent) + "  " + bytes(x.free) + " livre"; }).join("\n"));
      });
    },
    logout: function () { post("/api/logout").then(function () { location.href = "/login"; }); },
    sudo: function () { print("nice try. ;)", "warn"); },
    exit: function () { COMMANDS.logout(); }
  };
  var cmdHist = [], cmdPos = 0;
  $("cmdform").addEventListener("submit", function (e) {
    e.preventDefault();
    var input = $("cmd"), line = input.value.trim();
    input.value = "";
    if (!line) return;
    cmdHist.push(line); cmdPos = cmdHist.length;
    print($("ps1").textContent + " " + line, "dim");
    var parts = line.split(/\s+/), name = parts.shift().toLowerCase();
    if (/^[1-9]$/.test(name)) return COMMANDS.goto([name]);
    var fn = COMMANDS[name];
    if (fn) fn(parts); else print(name + ": comando nao encontrado. digite 'help'.", "warn");
  });
  $("cmd").addEventListener("keydown", function (e) {
    if (e.key === "ArrowUp" && cmdPos > 0) { cmdPos--; e.target.value = cmdHist[cmdPos]; e.preventDefault(); }
    else if (e.key === "ArrowDown") { cmdPos = Math.min(cmdHist.length, cmdPos + 1); e.target.value = cmdHist[cmdPos] || ""; e.preventDefault(); }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { closeModal(); return; }
    var tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "select" || tag === "textarea" || e.ctrlKey || e.metaKey || e.altKey) return;
    if (/^[1-9]$/.test(e.key)) { show(TABS[Number(e.key) - 1].id); e.preventDefault(); }
    else if (e.key === "/") { $("cmd").focus(); e.preventDefault(); }
  });

  // ------------------------------------------------------------------ boot
  function boot() {
    var el = $("boot");
    var lines = [
      "VM//PANEL BIOS v1.0  (C) RETRO SYSTEMS",
      "CHECKING MEMORY ........ OK",
      "DETECTING CPU .......... OK",
      "MOUNTING /proc ......... OK",
      "LINKING DOCKER SOCKET .. OK",
      "LOADING PHOSPHOR ....... OK",
      "",
      "WELCOME, " + ((state.me && state.me.user) || "OPERATOR").toUpperCase() + "."
    ];
    el.classList.remove("hidden");
    var i = 0;
    (function step() {
      if (i >= lines.length) { setTimeout(function () { el.classList.add("hidden"); }, 450); return; }
      el.textContent += lines[i++] + "\n";
      setTimeout(step, 110);
    })();
  }

  function init() {
    add($("tabs"), TABS.map(function (t) {
      return h("button", { "data-id": t.id, onclick: function () { show(t.id); } }, h("span", { class: "k" }, t.key + ":"), t.name);
    }));
    api("/api/me").then(function (me) {
      state.me = me;
      var fresh = false;
      try { fresh = sessionStorage.getItem("vmp_boot") === "1"; sessionStorage.removeItem("vmp_boot"); } catch (_) {}
      if (fresh && prefs.boot) boot();
      var start = (location.hash || "").slice(1);
      show(TABS.some(function (t) { return t.id === start; }) ? start : "dash");
      print("VM//PANEL v" + me.version + " pronto. digite 'help' para ver os comandos.", "dim");
    });
    setInterval(function () { $("clock").textContent = new Date().toLocaleTimeString("pt-BR"); }, 1000);
    window.addEventListener("resize", function () { if (current && VIEWS[current.id].after) refresh(); });
  }
  init();
})();
