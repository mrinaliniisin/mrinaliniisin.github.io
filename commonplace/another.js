// "Another one" — shows a random other factoid under the one being read.
// Reads factoids.json (the sync's own index), so new factoids join in
// automatically and frozen hand-tidied pages need nothing but this <script>.
(function () {
  var article = document.querySelector("main article");
  if (!article) return;
  var here = location.pathname.split("/").pop().replace(/\.html$/, "");

  var css = document.createElement("style");
  css.textContent =
    ".cpb-another { margin-top: 44px; padding-top: 22px; border-top: 1px solid #e7e4dd; }" +
    ".cpb-another-head { display: flex; justify-content: space-between; align-items: baseline;" +
    "  font-size: 13px; color: #a8a29e; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 10px; }" +
    ".cpb-another-head button { font: inherit; text-transform: none; letter-spacing: 0; color: #6b6560;" +
    "  background: none; border: 0; padding: 0; cursor: pointer; }" +
    ".cpb-another-head button:hover { color: #2d5a27; }" +
    ".cpb-another a { display: block; background: #fff; border: 1px solid #d9d6cf; border-radius: 12px;" +
    "  padding: 18px 20px; text-decoration: none; color: inherit;" +
    "  transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease; }" +
    ".cpb-another a:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,.06); border-color: #2d5a27; }" +
    ".cpb-another h2 { font-size: 17px; font-weight: 600; line-height: 1.35; margin: 0; }" +
    ".cpb-another a:hover h2 { color: #2d5a27; }";
  document.head.appendChild(css);

  fetch("/commonplace/factoids.json")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var pool = (data.factoids || []).filter(function (f) { return f.slug !== here; });
      if (!pool.length) return;

      var box = document.createElement("aside");
      box.className = "cpb-another";
      box.innerHTML = '<div class="cpb-another-head"><span>Another from the book</span>' +
        '<button type="button" aria-label="Show a different one">↻ shuffle</button></div>' +
        '<a><h2></h2></a>';
      var link = box.querySelector("a"), title = box.querySelector("h2");
      var last = null;

      function show() {
        var f;
        do { f = pool[Math.floor(Math.random() * pool.length)]; } while (pool.length > 1 && f === last);
        last = f;
        link.href = "/commonplace/" + f.slug + ".html";
        title.textContent = f.name;
      }

      box.querySelector("button").addEventListener("click", show);
      show();
      article.after(box);
    })
    .catch(function () {});
})();
