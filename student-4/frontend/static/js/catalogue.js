/* Inventory and Stock (Student 4) - small client-side helpers.
   All rendering is server-side via HTMX; this only handles the two
   interactions that are purely local to the browser. */
(function () {
  "use strict";

  /* 1. Copy an AI suggestion into the product form (human-in-the-loop:
        nothing is saved until the student presses Create/Save). */
  document.body.addEventListener("click", function (event) {
    var button = event.target.closest("[data-apply-ai]");
    if (!button) return;

    var skuField = document.getElementById("sku");
    var quantityField = document.getElementById("quantity");

    if (skuField) skuField.value = button.dataset.sku || skuField.value;
    if (quantityField) quantityField.value = button.dataset.quantity || quantityField.value;

    button.textContent = "Applied to the form";
    button.disabled = true;
    if (skuField) skuField.focus();
  });

  /* 2. Fade success banners away; errors stay until the next action. */
  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.target.id !== "alerts") return;
    var alert = event.target.querySelector('[data-auto-dismiss="true"]');
    if (!alert) return;
    window.setTimeout(function () {
      alert.style.transition = "opacity .4s";
      alert.style.opacity = "0";
      window.setTimeout(function () { alert.remove(); }, 400);
    }, 4000);
  });
})();
