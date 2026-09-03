/* Reviews and Ratings (Student 5) - small client-side helpers.
   All rendering is server-side via HTMX; this only fades success banners. */
(function () {
  "use strict";

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
