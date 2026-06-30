// Counterscale analytics loader.
//
// Every page includes this one file (<script src="/assets/analytics.js" defer>),
// so the Worker URL and site id live in exactly ONE place — set them once below
// and the whole site is wired. New pages just need the same include.
//
// Until WORKER is set to your real Counterscale Worker URL, this is a NO-OP:
// nothing is requested and no tracking happens. After you deploy Counterscale
// (npx @counterscale/cli@latest install), paste its URL into WORKER and commit.
(function () {
  var WORKER = "https://counterscale.YOUR-SUBDOMAIN.workers.dev"; // <-- set after deploy
  var SITE_ID = "mrinaliniisin";

  if (WORKER.indexOf("YOUR-SUBDOMAIN") !== -1) return; // not configured yet — no-op

  var s = document.createElement("script");
  s.id = "counterscale-script";
  s.dataset.siteId = SITE_ID;
  s.src = WORKER.replace(/\/$/, "") + "/tracker.js";
  s.defer = true;
  document.head.appendChild(s);
})();
