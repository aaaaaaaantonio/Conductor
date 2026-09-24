(function () {
  // hx-boost re-fetches and re-executes this script on every tab navigation
  // (it swaps <body>'s innerHTML but document.body itself persists), so
  // without this guard every boosted nav click stacks another copy of every
  // delegated listener below onto the same body element — e.g. the team
  // toggle below would flip its "open" class twice per click and appear to
  // do nothing.
  if (window.__testRunnerAppInit) return;
  window.__testRunnerAppInit = true;

  function setActiveJobRow(list, jobId) {
    list.querySelectorAll(".job-row").forEach(function (row) {
      row.classList.toggle("selected", Number(row.dataset.job) === jobId);
    });
  }

  document.body.addEventListener("click", function (e) {
    var row = e.target.closest(".job-row");
    if (!row) return;
    var list = row.closest("#job-list");
    if (list) setActiveJobRow(list, Number(row.dataset.job));
  });

  document.body.addEventListener("htmx:afterSwap", function (e) {
    // Re-apply the selection highlight after the job list refreshes
    // (periodic sse:job-status trigger), so the row stays marked selected
    // even though the fragment swap replaced it with a fresh element.
    if (e.target.id !== "job-list") return;
    var activeLog = document.querySelector("#job-log-body .log[data-job]");
    if (activeLog) setActiveJobRow(e.target, Number(activeLog.dataset.job));
  });

  // Sidebar connection indicator: hidden by default (pages without
  // sse-connect never open a stream), shown once the page's stream opens.
  function setSseStatus(ok) {
    var el = document.getElementById("sse-status");
    if (!el) return;
    el.hidden = false;
    el.classList.toggle("down", !ok);
    el.querySelector(".sb-sse-text").textContent = ok ? "Live-обновления" : "Нет связи с сервером";
  }
  document.body.addEventListener("htmx:sseOpen", function () { setSseStatus(true); });
  document.body.addEventListener("htmx:sseError", function () { setSseStatus(false); });

  // A Jenkins launch reply is prepended to the log panel (a per-page feed).
  // On the Python tab that panel may be showing a VM job's log instead —
  // clear it first so the reply doesn't land on top of an unrelated log.
  document.body.addEventListener("htmx:beforeSwap", function (e) {
    var target = e.detail.target;
    if (!target || target.id !== "job-log-body") return;
    if (e.detail.xhr.getResponseHeader("HX-Reswap") !== "afterbegin") return;
    if (target.querySelector(".log[data-job]")) target.innerHTML = "";
  });

  // Same status -> class mapping as fragments/job_log.html.
  var STATUS_CLASSES = { running: "run", success: "ok", failed: "fail" };

  function updateLogHeadStatus(log, event) {
    if (String(event.job_id) !== log.dataset.job) return;
    var head = log.parentNode.querySelector(".log-head");
    if (!head) return;
    var dot = head.querySelector(".dot");
    dot.classList.remove("run", "ok", "fail");
    if (STATUS_CLASSES[event.status]) dot.classList.add(STATUS_CLASSES[event.status]);
    head.querySelector(".job-id").textContent = event.status;
  }

  document.body.addEventListener("htmx:sseMessage", function (e) {
    // Only append a live log-line event to the log panel if it belongs to
    // the job currently open there — the SSE connection carries every
    // running job's output, not just the selected one.
    var target = document.querySelector("#job-log-body .log[data-job]");
    if (!target) return;
    if (e.detail.type === "job-status") {
      updateLogHeadStatus(target, JSON.parse(e.detail.data));
      return;
    }
    if (e.detail.type !== "log-line") return;
    var tmp = document.createElement("div");
    tmp.innerHTML = e.detail.data;
    var lineEl = tmp.firstElementChild;
    if (!lineEl || lineEl.dataset.job !== target.dataset.job) return;
    // Match the server-rendered lines (fragments/job_log.html): numbered,
    // and replacing the "log is empty" hint once output starts.
    var hint = target.querySelector(".log-empty-hint");
    if (hint) hint.remove();
    var ln = document.createElement("span");
    ln.className = "ln";
    ln.textContent = target.querySelectorAll(".ln").length + 1;
    lineEl.insertBefore(ln, lineEl.firstChild);
    target.appendChild(lineEl);
    target.scrollTop = target.scrollHeight;
  });

  // Team tree (agent-testing): each team toggles independently.
  document.body.addEventListener("click", function (e) {
    var toggle = e.target.closest(".team-toggle");
    if (!toggle) return;
    toggle.closest(".team-group").classList.toggle("open");
  });

  // Test-launch modal (agent-testing): opened by clicking a test in the tree,
  // closed via the × button, the Cancel button inside the loaded card, or
  // clicking the overlay backdrop. #test-modal only exists on the
  // agent-testing page, so it's looked up fresh on every event rather than
  // captured once — this script only runs once per session (see the guard
  // above), but a boosted nav can still swap in a brand-new #test-modal
  // element each time the user revisits that page, and a captured reference
  // would go stale and silently stop working after the first visit.
  document.body.addEventListener("click", function (e) {
    var modal = document.getElementById("test-modal");
    if (!modal) return;
    var link = e.target.closest(".modal-trigger");
    if (link) {
      if (link.classList.contains("tree-test") && !link.classList.contains("tree-add")) {
        document.querySelectorAll(".tree-test").forEach(function (t) {
          t.classList.remove("selected");
        });
        link.classList.add("selected");
      }
      modal.classList.add("open");
      return;
    }
    if (e.target === modal || e.target.closest(".modal-close, .modal-cancel")) {
      modal.classList.remove("open");
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    var modal = document.getElementById("test-modal");
    if (modal) modal.classList.remove("open");
  });
})();
