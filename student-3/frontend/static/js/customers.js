(function () {
  "use strict";

  function revealPanel(panel) {
    panel.classList.remove("panel-updated");
    window.requestAnimationFrame(function () {
      panel.classList.add("panel-updated");
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
      panel.focus({ preventScroll: true });
    });
  }

  document.body.addEventListener("htmx:beforeSwap", function (event) {
    var status = event.detail.xhr.status;
    if (status >= 400 && status < 600 && event.detail.xhr.responseText) {
      event.detail.shouldSwap = true;
      event.detail.isError = false;
    }
  });

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (["customer-detail", "ai-panel", "customer-form"].indexOf(event.target.id) !== -1) {
      revealPanel(event.target);
    }

    if (event.target.id === "alerts") {
      var alert = event.target.querySelector('[data-auto-dismiss="true"]');
      if (!alert) return;
      window.setTimeout(function () {
        alert.style.opacity = "0";
        window.setTimeout(function () { alert.remove(); }, 400);
      }, 4000);
    }
  });
})();
