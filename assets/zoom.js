// Standalone pages (PAGE_TEMPLATE in server.py): every image in the body shows
// as a smaller preview, and a click opens it full-size in an overlay over the
// text. Reuses the gallery's .lightbox dialog styles in blog.css.
//
// The preview size is keyed on the .zoomable class this script adds, so
// without it the images simply stay full-width — nothing is lost.
(() => {
  if (typeof HTMLDialogElement === "undefined") return;
  const imgs = Array.from(document.querySelectorAll(".post-body img"));
  if (!imgs.length) return;

  const dlg = document.createElement("dialog");
  dlg.className = "lightbox";
  dlg.innerHTML =
    '<button class="lightbox-close" type="button" aria-label="Close">&times;</button>' +
    '<img alt=""><p class="lightbox-caption"></p>';
  document.body.appendChild(dlg);
  const big = dlg.querySelector("img");
  const cap = dlg.querySelector(".lightbox-caption");

  const modified = e => e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button;
  imgs.forEach(img => {
    img.classList.add("zoomable");
    // A real link to the file, so a new-tab click still opens the image.
    let link = img.closest("a");
    if (!link) {
      link = document.createElement("a");
      link.href = img.getAttribute("src");
      img.replaceWith(link);
      link.appendChild(img);
    }
    link.classList.add("zoom-link");
    link.setAttribute("aria-label", "View full size" + (img.alt ? ": " + img.alt : ""));
    link.addEventListener("click", e => {
      if (modified(e)) return;
      e.preventDefault();
      big.src = img.currentSrc || img.src; big.alt = img.alt;
      cap.textContent = img.alt; cap.hidden = !img.alt;
      dlg.showModal();
    });
  });

  dlg.querySelector(".lightbox-close").addEventListener("click", () => dlg.close());
  // A click on the backdrop lands on the dialog element itself (its padding
  // is zero, so anything inside the box targets a child).
  dlg.addEventListener("click", e => { if (e.target === dlg) dlg.close(); });
  dlg.addEventListener("close", () => { big.removeAttribute("src"); });
})();
