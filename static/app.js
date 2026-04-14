(function () {
  const body = document.body;
  const loadingOverlay = document.getElementById("loading-overlay");
  const lockForms = document.querySelectorAll(".js-lock-form");
  const scrollStorageKey = "deckbuilder_ui_scroll_y";

  function saveScrollPosition() {
    try {
      window.sessionStorage.setItem(scrollStorageKey, String(window.scrollY || 0));
    } catch (error) {
      // Ignore storage issues in the local UI.
    }
  }

  function restoreScrollPosition() {
    try {
      const rawValue = window.sessionStorage.getItem(scrollStorageKey);
      if (!rawValue) {
        return;
      }
      window.sessionStorage.removeItem(scrollStorageKey);
      const scrollY = Number.parseInt(rawValue, 10);
      if (Number.isFinite(scrollY)) {
        window.setTimeout(function () {
          window.scrollTo(0, scrollY);
        }, 0);
      }
    } catch (error) {
      // Ignore storage issues in the local UI.
    }
  }

  function lockUi(submittingForm) {
    saveScrollPosition();
    if (loadingOverlay) {
      loadingOverlay.classList.remove("hidden");
    }
    document.body.classList.add("is-loading");
    document.querySelectorAll("button, input").forEach((element) => {
      if (submittingForm && submittingForm.contains(element)) {
        return;
      }
      element.disabled = true;
    });

    if (submittingForm) {
      submittingForm.dataset.submitted = "true";
      submittingForm.querySelectorAll('input[type="text"]').forEach((element) => {
        element.readOnly = true;
      });
      submittingForm.querySelectorAll('button[type="submit"]').forEach((element) => {
        element.disabled = true;
      });
    }

    if (document.activeElement && typeof document.activeElement.blur === "function") {
      document.activeElement.blur();
    }
  }

  lockForms.forEach((form) => {
    form.addEventListener("submit", function (event) {
      if (form.dataset.submitted === "true") {
        event.preventDefault();
        return;
      }
      lockUi(form);
    });
  });

  if (body && body.dataset.autoRefreshLoading === "true") {
    window.setTimeout(function () {
      saveScrollPosition();
      window.location.reload();
    }, 3000);
  }

  restoreScrollPosition();
})();
