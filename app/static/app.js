(function () {
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

  document.body.addEventListener("htmx:sseMessage", function (e) {
    // Only append a live log-line event to the log panel if it belongs to
    // the job currently open there — the SSE connection carries every
    // running job's output, not just the selected one.
    if (e.detail.type !== "log-line") return;
    var target = document.querySelector("#job-log-body .log[data-job]");
    if (!target) return;
    var tmp = document.createElement("div");
    tmp.innerHTML = e.detail.data;
    var lineEl = tmp.firstElementChild;
    if (!lineEl || lineEl.dataset.job !== target.dataset.job) return;
    target.appendChild(lineEl);
    target.scrollTop = target.scrollHeight;
  });

  // Team accordion (agent-testing tree): only one team open at a time.
  document.body.addEventListener("click", function (e) {
    var toggle = e.target.closest(".team-toggle");
    if (!toggle) return;
    var group = toggle.closest(".team-group");
    var wasOpen = group.classList.contains("open");
    group.parentElement.querySelectorAll(".team-group").forEach(function (g) {
      g.classList.remove("open");
    });
    if (!wasOpen) group.classList.add("open");
  });

  // Test-launch modal (agent-testing): opened by clicking a test in the tree,
  // closed via the × button, the Cancel button inside the loaded card, or
  // clicking the overlay backdrop.
  var modal = document.getElementById("test-modal");
  if (modal) {
    document.body.addEventListener("click", function (e) {
      var link = e.target.closest(".tree-test");
      if (link) {
        document.querySelectorAll(".tree-test").forEach(function (t) {
          t.classList.remove("selected");
        });
        link.classList.add("selected");
        modal.classList.add("open");
        return;
      }
      if (e.target === modal || e.target.closest(".modal-close, .modal-cancel")) {
        modal.classList.remove("open");
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") modal.classList.remove("open");
    });
  }
})();
