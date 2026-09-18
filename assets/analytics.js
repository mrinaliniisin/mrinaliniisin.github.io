// Counterscale analytics loader.
//
// Every page includes this one file (<script src="/assets/analytics.js" defer>),
// so the Worker URL and site id live in exactly ONE place — set them once below
// and the whole site is wired. New pages just need the same include.
//
// If WORKER is reset to the YOUR-SUBDOMAIN placeholder this becomes a NO-OP:
// nothing is requested and no tracking happens. Deploy/upgrade steps are in
// analytics/README.md (don't use the counterscale installer; it's broken).
(function () {
  var WORKER = "https://counterscale.mustardseed.workers.dev";
  var SITE_ID = "mrinaliniisin";

  if (WORKER.indexOf("YOUR-SUBDOMAIN") !== -1) return; // not configured yet — no-op

  var s = document.createElement("script");
  s.id = "counterscale-script";
  s.dataset.siteId = SITE_ID;
  s.src = WORKER.replace(/\/$/, "") + "/tracker.js";
  s.defer = true;
  document.head.appendChild(s);
})();
