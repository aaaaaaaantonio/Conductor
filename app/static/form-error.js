(function () {
  // Forms and actions report API errors inline instead of alert(): inside a
  // container (above its .modal-foot, if any) or right after an element
  // such as a list row. Loaded in <head> (base.html), before any page or
  // fragment script, so those can call window.formError right away.
  var VALIDATION_MESSAGES = {
    missing: "обязательное поле",
    int_parsing: "ожидается целое число",
    int_type: "ожидается целое число",
    float_parsing: "ожидается число",
    bool_parsing: "ожидается да или нет",
    string_type: "ожидается строка",
    string_too_short: "слишком короткое значение",
    literal_error: "недопустимое значение",
    enum: "недопустимое значение",
    json_invalid: "некорректный JSON",
  };

  function detailText(detail) {
    if (typeof detail === "string") return detail;
    // FastAPI validation errors: [{type, loc: [...], msg}, ...]
    if (Array.isArray(detail)) {
      return detail.map(function (d) {
        d = d || {};
        var loc = d.loc || [];
        var field = loc.length > 1 ? loc[loc.length - 1] : "";
        var text = VALIDATION_MESSAGES[d.type] || d.msg || String(d);
        return (field ? field + ": " : "") + text;
      }).join("; ");
    }
    return "";
  }

  function makeBox() {
    var box = document.createElement("div");
    box.className = "form-error";
    box.setAttribute("role", "alert");
    return box;
  }

  function ownBox(container) {
    for (var i = 0; i < container.children.length; i++) {
      if (container.children[i].classList.contains("form-error")) return container.children[i];
    }
    return null;
  }

  function isBox(el) {
    return !!el && el.classList.contains("form-error");
  }

  window.formError = {
    show: function (container, message) {
      var box = ownBox(container);
      if (!box) {
        box = makeBox();
        var foot = null;
        for (var i = 0; i < container.children.length; i++) {
          if (container.children[i].classList.contains("modal-foot")) foot = container.children[i];
        }
        container.insertBefore(box, foot);
      }
      box.textContent = message;
      box.scrollIntoView({ block: "nearest" });
    },
    showAfter: function (el, message) {
      var box = el.nextElementSibling;
      if (!isBox(box)) {
        box = makeBox();
        el.parentNode.insertBefore(box, el.nextSibling);
      }
      box.textContent = message;
      box.scrollIntoView({ block: "nearest" });
    },
    clear: function (container) {
      var box = ownBox(container);
      if (box) box.remove();
    },
    // Remove every inline error under `root` (default: the whole page).
    clearAll: function (root) {
      (root || document).querySelectorAll(".form-error").forEach(function (box) { box.remove(); });
    },
    // Resolves to the error text for a failed fetch() response.
    fromResponse: function (resp, fallback) {
      var generic = fallback + " (" + resp.status + ")";
      return resp.json().then(function (body) {
        return detailText(body && body.detail) || generic;
      }).catch(function () { return generic; });
    },
    // Wire a form: clear the message as soon as the user edits anything.
    bind: function (form) {
      form.addEventListener("input", function () { window.formError.clear(form); });
    },
  };
})();
