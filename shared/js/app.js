/* =========================================================================
   ASD 2026 - Group 40 - shared client-side helpers.
   Loaded by the unified home page and by every student frontend.
   ========================================================================= */
(function () {
  "use strict";

  /** Render the feature tiles on the unified home page from services.json. */
  async function renderFeatureTiles(targetId) {
    const target = document.getElementById(targetId);
    if (!target) return;
    try {
      const res = await fetch("config/services.json", { cache: "no-store" });
      const cfg = await res.json();
      target.innerHTML = cfg.features.map(featureCard).join("");
    } catch (err) {
      target.innerHTML =
        '<div class="alert error">Could not load shared/config/services.json: ' + err + "</div>";
    }
  }

  function featureCard(f) {
    const ready = f.status === "ready";
    const pill = ready
      ? '<span class="status-pill ready">Release 0 ready</span>'
      : '<span class="status-pill pending">not implemented</span>';
    const inner =
      pill +
      "<h3>" + f.feature + "</h3>" +
      "<p>" + f.description + "</p>" +
      '<div class="owner">Student ' + f.student + " &middot; " + f.owner + "</div>";
    return ready
      ? '<a class="card feature-card" href="' + f.frontend + '">' + inner + "</a>"
      : '<div class="card feature-card" style="opacity:.62">' + inner + "</div>";
  }

  window.ASD = { renderFeatureTiles: renderFeatureTiles };
})();
