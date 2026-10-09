/* Review composer — one box: write a few words, tap a suggestion to use it,
   post on Google. Spec section 39 (AI review assist). No dependencies. */
(function () {
  "use strict";

  var form = document.getElementById("assist-form");
  if (!form) return;

  var box = document.getElementById("review-draft");
  var count = document.getElementById("draft-count");
  var suggestBtn = document.getElementById("suggest-btn");
  var errorBox = document.getElementById("composer-error");
  var variantsWrap = document.getElementById("variants-wrap");
  var variantsList = document.getElementById("variants");
  var providerLabel = document.getElementById("variants-provider");
  var copyBtn = document.getElementById("copy-btn");
  var googleOpen = document.getElementById("google-open");
  var status = document.getElementById("composer-status");
  var assistUrl = form.getAttribute("action");
  var csrf = form.querySelector("[name=csrfmiddlewaretoken]").value;

  var smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function say(msg) {
    status.textContent = msg;
  }

  function showError(msg) {
    errorBox.textContent = msg;
    errorBox.hidden = false;
  }

  function clearError() {
    errorBox.hidden = true;
    errorBox.textContent = "";
  }

  function syncCount() {
    count.textContent = box.value.length + " / 2000";
  }

  function copyText(text, onDone) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(onDone, function () { fallbackCopy(text, onDone); });
    } else {
      fallbackCopy(text, onDone);
    }
  }

  function fallbackCopy(text, onDone) {
    var helper = document.createElement("textarea");
    helper.value = text;
    helper.setAttribute("readonly", "");
    helper.style.position = "fixed";
    helper.style.opacity = "0";
    document.body.appendChild(helper);
    helper.select();
    try { document.execCommand("copy"); } catch (e) { /* nothing else to try */ }
    document.body.removeChild(helper);
    onDone();
  }

  function flashCopied(btn, restore) {
    btn.textContent = "Copied";
    setTimeout(function () { btn.textContent = restore; }, 1600);
  }

  box.addEventListener("input", function () {
    syncCount();
    clearError();
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    clearError();

    var text = box.value.trim();
    if (text.length < 3) {
      showError("Write at least a few words about your visit first.");
      box.focus();
      return;
    }

    suggestBtn.disabled = true;
    suggestBtn.setAttribute("aria-busy", "true");
    var restore = suggestBtn.textContent;
    suggestBtn.textContent = "Preparing suggestions...";

    fetch(assistUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrf
      },
      body: JSON.stringify({ text: text })
    })
      .then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) {
            throw new Error(data.error || "Could not prepare suggestions just now.");
          }
          return data;
        });
      })
      .then(function (data) {
        renderVariants(data.variants || [], data.provider || "");
        say("Suggestions ready — tap one to use it.");
      })
      .catch(function (err) {
        showError(err.message || "Could not prepare suggestions just now.");
      })
      .then(function () {
        suggestBtn.disabled = false;
        suggestBtn.removeAttribute("aria-busy");
        suggestBtn.textContent = restore;
      });
  });

  function renderVariants(variants, provider) {
    variantsList.innerHTML = "";
    providerLabel.textContent = provider === "local"
      ? "Your words, tidied"
      : "AI suggestions";

    // Only the first 3 suggestions are shown (client feedback 2026-10-09).
    variants.slice(0, 3).forEach(function (text) {
      var row = document.createElement("button");
      row.type = "button";
      row.className = "variant-row";
      row.setAttribute("aria-pressed", "false");

      var body = document.createElement("span");
      body.className = "variant-row__text";
      body.textContent = text;

      var hint = document.createElement("span");
      hint.className = "variant-row__hint";
      hint.textContent = "Tap to use";

      row.appendChild(body);
      row.appendChild(hint);

      row.addEventListener("click", function () {
        // tap to use: the suggestion loads straight into the one box
        box.value = text;
        syncCount();
        clearError();
        Array.prototype.forEach.call(variantsList.children, function (el) {
          el.classList.remove("variant-row--used");
          el.setAttribute("aria-pressed", "false");
          var h = el.querySelector(".variant-row__hint");
          if (h) h.textContent = "Tap to use";
        });
        row.classList.add("variant-row--used");
        row.setAttribute("aria-pressed", "true");
        hint.textContent = "In your review";
        say("Loaded into your review — edit it if you like, then open Google.");
        box.focus();
        box.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "center" });
      });

      variantsList.appendChild(row);
    });

    variantsWrap.hidden = false;
    variantsWrap.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
  }

  copyBtn.addEventListener("click", function () {
    var text = box.value.trim();
    if (!text) {
      showError("Your review is empty — write a few words or tap a suggestion first.");
      box.focus();
      return;
    }
    clearError();
    copyText(text, function () {
      flashCopied(copyBtn, "Copy review");
      say("Copied — paste it into Google's review box.");
    });
  });

  googleOpen.addEventListener("click", function () {
    var text = box.value.trim();
    if (text) {
      copyText(text, function () {
        say("Review copied — paste it into Google's review box.");
      });
    } else {
      say("Opening Google — write your review directly there.");
    }
  });
})();
