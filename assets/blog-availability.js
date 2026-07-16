// Blog index: a card's post is sometimes committed to blog/index.html before
// the post file itself is pushed (or it's still sitting locally, untracked).
// Rather than ship a dead link, fall back to a "coming soon" state for those.
//
// Locally (running under server.py), the file usually *does* exist on disk
// even when uncommitted, so a plain fetch would find it and miss the case
// entirely — the whole point is to preview what a visitor would see once
// this is pushed as-is. So server.py's own /api/blog-status (git HEAD vs.
// disk) is the primary signal; only when that endpoint isn't there (static
// hosting, e.g. the live GitHub Pages site, which has no server to ask) do
// we fall back to checking whether each post actually resolves.
(() => {
  const cards = Array.from(document.querySelectorAll(".post-grid .card")).map(card => {
    const link = card.querySelector(".card-link");
    return link && link.getAttribute("href") ? { card, link, href: link.getAttribute("href") } : null;
  }).filter(Boolean);
  if (!cards.length) return;

  fetch("/api/blog-status", { cache: "no-store" })
    .then(res => (res.ok ? res.json() : Promise.reject()))
    .then(({ uncommitted }) => {
      const stale = new Set(uncommitted || []);
      cards.forEach(({ card, link, href }) => { if (stale.has(href)) markComingSoon(card, link); });
    })
    .catch(() => {
      cards.forEach(({ card, link, href }) => {
        fetch(href, { method: "HEAD", cache: "no-store" })
          .then(res => { if (!res.ok) markComingSoon(card, link); })
          .catch(() => {});   // network hiccup — don't guess, leave the card as-is
      });
    });

  function markComingSoon(card, link) {
    card.classList.add("coming-soon");
    link.removeAttribute("href");
    link.setAttribute("aria-disabled", "true");
    const meta = card.querySelector(".desc");
    if (meta) meta.textContent = "Coming soon, to be notified hit the 🔔";
  }
})();
