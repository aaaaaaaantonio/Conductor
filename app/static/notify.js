(function () {
  // Tells the user that a VM job they launched from this browser finished
  // while Conductor was in the background: a red counter on the tab icon,
  // a sound and, if allowed, a system notification. Settings live in this
  // browser only. Like app.js, hx-boost re-runs this script on every nav.
  if (window.__conductorNotifyInit) return;
  window.__conductorNotifyInit = true;

  var SETTINGS_KEY = "conductor:notify";
  var MINE_KEY = "conductor:my-jobs";
  var DEFAULTS = { sound: "twotone", badge: true, os: false, errorsOnly: false };
  var STATUS_TEXT = { success: "Успешно", failed: "Ошибка" };
  var SOURCE_TEXT = { python: "Python", agent_test: "Тестирование агентов" };

  function loadSettings() {
    try {
      return Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem(SETTINGS_KEY)) || {});
    } catch (e) {
      return Object.assign({}, DEFAULTS);
    }
  }
  var settings = loadSettings();

  function saveSettings() {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch (e) {}
  }

  // ---------- jobs launched from this browser ----------
  // Shared by all Conductor tabs via localStorage; the first tab to see a
  // job finish takes it off the list, so several open tabs notify once.
  var memoryMine = [];

  function readMine() {
    try {
      return JSON.parse(localStorage.getItem(MINE_KEY)) || [];
    } catch (e) {
      return memoryMine;
    }
  }

  function writeMine(ids) {
    memoryMine = ids.slice(-50);
    try {
      localStorage.setItem(MINE_KEY, JSON.stringify(memoryMine));
    } catch (e) {}
  }

  function track(id) {
    var ids = readMine();
    if (ids.indexOf(id) < 0) ids.push(id);
    writeMine(ids);
  }

  function claim(id) {
    var ids = readMine();
    var i = ids.indexOf(id);
    if (i < 0) return false;
    ids.splice(i, 1);
    writeMine(ids);
    return true;
  }

  // VM launches announce the new job: the Python form via an HX-Trigger
  // header, agent tests by dispatching the same event themselves.
  document.body.addEventListener("job-launched", function (e) {
    if (e.detail && e.detail.id) track(Number(e.detail.id));
  });

  // ---------- tab icon counter ----------
  var unread = 0;
  var favicon = document.getElementById("favicon");
  var baseIcon = favicon ? favicon.href : "";
  var TITLE_PREFIX = /^\(\d+\+?\) /;

  function drawBadgeIcon(n) {
    var canvas = document.createElement("canvas");
    canvas.width = canvas.height = 64;
    var c = canvas.getContext("2d");
    // Same picture as static/favicon.svg, plus the counter.
    c.fillStyle = "#2f6f5e";
    c.beginPath();
    if (c.roundRect) c.roundRect(0, 0, 64, 64, 16); else c.rect(0, 0, 64, 64);
    c.fill();
    c.fillStyle = "#fff";
    c.beginPath(); c.moveTo(22, 16); c.lineTo(48, 32); c.lineTo(22, 48); c.closePath(); c.fill();
    var label = n > 9 ? "9+" : String(n);
    c.fillStyle = "#e5322d";
    c.strokeStyle = "#fff";
    c.lineWidth = 3;
    c.beginPath(); c.arc(42, 22, 21, 0, Math.PI * 2); c.fill(); c.stroke();
    c.fillStyle = "#fff";
    c.font = "bold " + (label.length > 1 ? 24 : 32) + "px system-ui, sans-serif";
    c.textAlign = "center";
    c.textBaseline = "middle";
    c.fillText(label, 42, 24);
    return canvas.toDataURL("image/png");
  }

  function renderBadge() {
    var n = settings.badge ? unread : 0;
    if (favicon) favicon.href = n ? drawBadgeIcon(n) : baseIcon;
    var title = document.title.replace(TITLE_PREFIX, "");
    document.title = n ? "(" + (n > 9 ? "9+" : n) + ") " + title : title;
  }

  function clearBadge() {
    if (!unread) return;
    unread = 0;
    renderBadge();
  }
  document.addEventListener("visibilitychange", function () { if (!document.hidden) clearBadge(); });
  window.addEventListener("focus", clearBadge);

  // ---------- sounds (synthesized, no files) ----------
  var audio = null;

  function audioContext() {
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    if (!audio) audio = new Ctx();
    if (audio.state === "suspended") audio.resume();
    return audio;
  }
  // Browsers only allow sound after the user has interacted with the page;
  // unlock it on the first click or key press (e.g. the launch button).
  function unlockAudio() {
    audioContext();
    document.removeEventListener("pointerdown", unlockAudio);
    document.removeEventListener("keydown", unlockAudio);
  }
  document.addEventListener("pointerdown", unlockAudio);
  document.addEventListener("keydown", unlockAudio);

  function tone(freq, at, dur, opts) {
    opts = opts || {};
    var t = audio.currentTime + at;
    var osc = audio.createOscillator();
    var gain = audio.createGain();
    osc.type = opts.type || "sine";
    osc.frequency.setValueAtTime(freq, t);
    if (opts.glide) osc.frequency.exponentialRampToValueAtTime(opts.glide, t + dur);
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(opts.vol || 0.25, t + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    osc.connect(gain).connect(audio.destination);
    osc.start(t);
    osc.stop(t + dur + 0.02);
  }

  function bell(freq, at, vol) {
    // A fundamental plus quieter, faster-decaying inharmonic overtones.
    vol = vol || 0.22;
    tone(freq, at, 1.4, { vol: vol });
    tone(freq * 2.76, at, 0.6, { vol: vol * 0.35 });
    tone(freq * 5.4, at, 0.3, { vol: vol * 0.15 });
  }

  function notes(freqs, step, dur, opts) {
    freqs.forEach(function (f, i) { tone(f, i * step, dur, opts); });
  }

  var SOUNDS = {
    none: { name: "Без звука" },
    twotone: {
      name: "Два тона",
      success: function () { notes([660, 880], 0.16, 0.3); },
      failed: function () { notes([440, 294], 0.16, 0.3); },
    },
    bell: {
      name: "Колокольчик",
      success: function () { bell(1047, 0); bell(1568, 0.18, 0.16); },
      failed: function () { bell(523, 0); bell(392, 0.22, 0.18); },
    },
    marimba: {
      name: "Маримба",
      success: function () { notes([784, 988, 1175], 0.09, 0.22, { type: "triangle", vol: 0.35 }); },
      failed: function () { notes([587, 494, 392], 0.11, 0.25, { type: "triangle", vol: 0.35 }); },
    },
    chord: {
      name: "Аккорд",
      success: function () { notes([523, 659, 784, 1047], 0.08, 0.7, { vol: 0.14 }); },
      failed: function () { notes([440, 523, 659], 0.1, 0.8, { vol: 0.15 }); tone(415, 0.3, 0.9, { vol: 0.12 }); },
    },
    retro: {
      name: "8-бит",
      success: function () {
        tone(988, 0, 0.08, { type: "square", vol: 0.1 });
        tone(1319, 0.08, 0.3, { type: "square", vol: 0.1 });
      },
      failed: function () {
        tone(392, 0, 0.12, { type: "square", vol: 0.1 });
        tone(330, 0.13, 0.12, { type: "square", vol: 0.1 });
        tone(262, 0.26, 0.35, { type: "square", vol: 0.1, glide: 196 });
      },
    },
    drop: {
      name: "Капля",
      success: function () { tone(500, 0, 0.18, { glide: 1400, vol: 0.3 }); },
      failed: function () { tone(400, 0, 0.25, { glide: 150, vol: 0.3, type: "triangle" }); },
    },
    alarm: {
      name: "Тревога только на ошибку",
      success: function () { tone(1200, 0, 0.05, { vol: 0.12 }); },
      failed: function () { notes([880, 880, 880], 0.22, 0.16, { type: "sawtooth", vol: 0.09 }); },
    },
  };

  function playSound(name, status) {
    var sound = SOUNDS[name];
    if (!sound || !sound.success || !audioContext()) return;
    try {
      sound[status === "success" ? "success" : "failed"]();
    } catch (e) {}
  }

  // ---------- system notifications ----------
  function openJob(jobId) {
    window.focus();
    if (document.getElementById("job-log-body") && window.htmx) {
      htmx.ajax("GET", "/jobs/" + jobId + "/fragments/log", { target: "#job-log-body", swap: "innerHTML" });
    } else {
      window.location.href = "/history";
    }
  }

  function systemNotify(event) {
    if (!settings.os || !("Notification" in window) || Notification.permission !== "granted") return;
    var parts = [SOURCE_TEXT[event.source] || event.source];
    if (event.duration !== null && event.duration !== undefined) parts.push(window.conductorFormatDuration(event.duration));
    var title = event.test
      ? "🔔 Проверка уведомления Conductor"
      : (event.status === "success" ? "✅" : "❌") + " Запуск #" + event.job_id + " — " + STATUS_TEXT[event.status];
    try {
      var n = new Notification(title, {
        body: parts.join(" · "),
        tag: "conductor-job-" + event.job_id,
        icon: "/static/favicon.svg",
      });
      n.onclick = function () {
        if (event.test) window.focus(); else openJob(event.job_id);
        n.close();
      };
    } catch (e) {}
  }

  function notify(event) {
    if (settings.errorsOnly && event.status !== "failed") return;
    unread++;
    renderBadge();
    playSound(settings.sound, event.status);
    systemNotify(event);
    // A test fired while the user stayed on the tab: no focus event will
    // come to clear it.
    if (event.test && !document.hidden && document.hasFocus()) setTimeout(clearBadge, 4000);
  }

  document.body.addEventListener("htmx:sseMessage", function (e) {
    if (e.detail.type !== "job-status") return;
    var event = JSON.parse(e.detail.data);
    if (!STATUS_TEXT[event.status] && event.status !== "cancelled") return;
    if (!claim(Number(event.job_id))) return;
    // A job the user stopped themselves needs no reminder.
    if (event.status === "cancelled") return;
    // Looking at Conductor right now: the log panel already shows it.
    if (!document.hidden && document.hasFocus()) return;
    notify(event);
  });

  // ---------- settings panel ----------
  function panel() { return document.getElementById("notify-panel"); }

  function setOsHint(text) {
    var hint = panel().querySelector("[data-notify-os-hint]");
    hint.textContent = text || "";
    hint.hidden = !text;
  }

  function osUnavailableReason() {
    if (!("Notification" in window)) return "Этот браузер не поддерживает уведомления.";
    if (!window.isSecureContext) {
      return "Браузер разрешает уведомления только по HTTPS или на localhost. " +
        "Открой Conductor через SSH-туннель (localhost) или поставь HTTPS.";
    }
    if (Notification.permission === "denied") {
      return "Уведомления запрещены для этого сайта — разреши их в настройках сайта (значок слева от адреса).";
    }
    return "";
  }

  function syncPanel() {
    var p = panel();
    var select = p.querySelector('[data-notify="sound"]');
    if (!select.options.length) {
      Object.keys(SOUNDS).forEach(function (key) {
        var opt = document.createElement("option");
        opt.value = key;
        opt.textContent = SOUNDS[key].name;
        select.appendChild(opt);
      });
    }
    select.value = SOUNDS[settings.sound] ? settings.sound : DEFAULTS.sound;
    p.querySelector('[data-notify="badge"]').checked = settings.badge;
    p.querySelector('[data-notify="errorsOnly"]').checked = settings.errorsOnly;
    var os = p.querySelector('[data-notify="os"]');
    var reason = osUnavailableReason();
    os.checked = settings.os && !reason && Notification.permission === "granted";
    setOsHint(settings.os ? reason : "");
    p.querySelectorAll("[data-notify-play]").forEach(function (b) { b.disabled = settings.sound === "none"; });
  }

  function setPanelOpen(open) {
    var p = panel();
    var toggle = document.getElementById("notify-toggle");
    if (!p || !toggle) return;
    if (open) syncPanel();
    p.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
  }

  document.body.addEventListener("click", function (e) {
    var p = panel();
    if (!p) return;
    if (e.target.closest("#notify-toggle")) {
      setPanelOpen(p.hidden);
      return;
    }
    if (e.target.closest("[data-notify-close]")) {
      setPanelOpen(false);
      return;
    }
    var play = e.target.closest("[data-notify-play]");
    if (play) {
      playSound(settings.sound, play.dataset.notifyPlay);
      return;
    }
    if (e.target.closest("[data-notify-test]")) {
      // Lets the user switch away and see exactly what a real one looks like.
      setTimeout(function () {
        notify({ test: true, job_id: 0, status: settings.errorsOnly ? "failed" : "success", source: "python", duration: 252 });
      }, 3000);
      return;
    }
    if (!p.hidden && !p.contains(e.target)) setPanelOpen(false);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && panel() && !panel().hidden) setPanelOpen(false);
  });

  document.body.addEventListener("change", function (e) {
    var el = e.target.closest("[data-notify]");
    if (!el || !panel() || !panel().contains(el)) return;
    var key = el.dataset.notify;
    if (key === "sound") {
      settings.sound = el.value;
      playSound(settings.sound, "success");
    } else if (key === "os") {
      var reason = el.checked ? osUnavailableReason() : "";
      settings.os = el.checked && !reason;
      if (reason) {
        saveSettings();
        syncPanel();
        setOsHint(reason);
        return;
      }
      if (settings.os && Notification.permission !== "granted") {
        Notification.requestPermission().then(function () { syncPanel(); });
      }
    } else {
      settings[key] = el.checked;
      if (key === "badge") renderBadge();
    }
    saveSettings();
    syncPanel();
  });
})();
