// Gallery posts (post-layout: gallery): a big stage with a filmstrip of
// thumbnails under it, in the manner of Finder's gallery view. The page opens
// on a cover card with nothing selected; this script makes the strip
// selectable (click, arrow keys), swaps the cover for the chosen image, writes
// the image's caption and alt text over its bottom edge, and opens the stage
// image full-size in an overlay.
//
// Without it the cover stays and every thumbnail is a plain link to its image
// file — a strip of links rather than a gallery, but nothing is lost.
(() => {
  const strip = document.querySelector(".gallery-strip");
  const cover = document.querySelector(".gallery-cover");
  const stage = document.querySelector(".gallery-stage img");
  const stageLink = document.querySelector(".gallery-stage-link");
  const caption = document.querySelector(".gallery-stage-caption");
  if (!strip || !stage || !stageLink || !caption) return;

  const cards = Array.from(strip.querySelectorAll(".gallery-card"));
  const items = cards.map(card => {
    const img = card.querySelector("img");
    const fc = card.querySelector("figcaption");
    return {
      src: img.getAttribute("src"),
      alt: img.alt,
      // The caption is trusted markup from the post itself (a product link,
      // say), so it's carried as HTML; the alt is plain text.
      caption: fc ? fc.innerHTML : "",
      captionText: fc ? fc.textContent.trim() : "",
    };
  });
  if (!items.length) return;

  const el = {
    index: caption.querySelector(".gallery-stage-index"),
    title: caption.querySelector(".gallery-stage-title"),
    alt: caption.querySelector(".gallery-stage-alt"),
  };
  const fileName = src => decodeURIComponent(src.split("/").pop());
  let current = -1;   // nothing selected: the cover is showing

  function show(i, reveal) {
    i = (i + items.length) % items.length;
    const it = items[i];
    // First selection: the cover gives way to the stage image and its caption.
    if (cover) cover.hidden = true;
    stageLink.hidden = false;
    caption.hidden = false;
    cards.forEach((c, k) => {
      c.classList.toggle("selected", k === i);
      if (k === i) c.setAttribute("aria-current", "true"); else c.removeAttribute("aria-current");
    });
    stage.src = it.src; stage.alt = it.alt; stageLink.href = it.src;
    el.index.textContent = (i + 1) + " / " + items.length;
    if (it.caption) el.title.innerHTML = it.caption;
    else el.title.textContent = it.alt || fileName(it.src);
    // The alt line repeats the title when the caption came from the alt, so
    // it only shows when it says something the title doesn't.
    const showAlt = !!it.alt && it.alt !== it.captionText;
    el.alt.textContent = it.alt; el.alt.hidden = !showAlt;
    current = i;
    // Bring the thumbnail into view by scrolling the strip itself, never the
    // page: scrollIntoView would also nudge the document vertically.
    if (reveal) {
      const card = cards[i];
      strip.scrollTo({ left: card.offsetLeft - (strip.clientWidth - card.offsetWidth) / 2,
                       behavior: "smooth" });
    }
    if (dlg && dlg.open) fillOverlay();
  }

  const modified = e => e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button;
  cards.forEach((card, i) => {
    card.querySelector(".gallery-card-image").addEventListener("click", e => {
      if (modified(e)) return;            // new-tab clicks stay plain links
      e.preventDefault();
      show(i, true);
    });
  });

  // ---- Full-size overlay for the stage image -------------------------------
  let dlg = null;
  let fillOverlay = () => {};
  if (typeof HTMLDialogElement !== "undefined") {
    dlg = document.createElement("dialog");
    dlg.className = "lightbox";
    dlg.innerHTML =
      '<button class="lightbox-close" type="button" aria-label="Close">&times;</button>' +
      '<img alt=""><p class="lightbox-caption"></p>';
    document.body.appendChild(dlg);
    const big = dlg.querySelector("img");
    const cap = dlg.querySelector(".lightbox-caption");
    fillOverlay = () => {
      const it = items[current];
      big.src = it.src; big.alt = it.alt;
      if (it.caption) cap.innerHTML = it.caption; else cap.textContent = it.alt;
      cap.hidden = !cap.textContent.trim();
    };
    stageLink.addEventListener("click", e => {
      if (modified(e)) return;
      e.preventDefault();
      fillOverlay();
      dlg.showModal();
    });
    dlg.querySelector(".lightbox-close").addEventListener("click", () => dlg.close());
    // A click on the backdrop lands on the dialog element itself (its padding
    // is zero, so anything inside the box targets a child).
    dlg.addEventListener("click", e => { if (e.target === dlg) dlg.close(); });
    dlg.addEventListener("close", () => { big.removeAttribute("src"); });
  }

  // ---- Keyboard: arrows step through the strip, Escape closes the overlay --
  document.addEventListener("keydown", e => {
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (e.key === "ArrowRight") { e.preventDefault(); show(current + 1, true); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); show(current < 0 ? items.length - 1 : current - 1, true); }
    else if (e.key === "Escape" && dlg && dlg.open) { e.preventDefault(); dlg.close(); }
  });
})();
