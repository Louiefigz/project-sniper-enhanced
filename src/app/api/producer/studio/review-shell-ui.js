// Pinned StudioHeader/RenderQueue Export controls and CompositionsTab's
// aria-label="Render ${name}". This improves UX; the HTTP guard is authority.
(function () {
  "use strict";
  const tooltip = "Studio is review-only. Render updated video in Sniper for full QC.";
  const motionLabel = "Set motion destination";
  const motionTooltip = "Native motion-path editing is not qualified offline. Use Sniper motion controls.";
  const mark = "data-sniper-review-blocked";
  const selector = 'button[aria-label^="Render "],button[aria-label="Set motion destination"],button.bg-studio-accent,button.bg-panel-accent,button[' + mark + ']';

  function blocked(button) {
    if (!button || button.tagName !== "BUTTON") return false;
    if (button.hasAttribute(mark)) return true;
    if (button.getAttribute("aria-label") === motionLabel) return true;
    if ((button.getAttribute("aria-label") || "").startsWith("Render ")) return true;
    return exportControl(button);
  }

  function exportControl(button) {
    // Export text alone is not authority: an unrelated editing control must
    // not be disabled. These classes belong to the two audited components.
    if (button.textContent.trim() !== "Export") return false;
    return button.classList.contains("bg-studio-accent")
      || button.classList.contains("bg-panel-accent");
  }

  function refresh() {
    document.querySelectorAll(selector).forEach(function (button) {
      if (!blocked(button)) return;
      if (!button.disabled) button.disabled = true;
      if (!button.hasAttribute(mark)) button.setAttribute(mark, "true");
      if (button.getAttribute("aria-disabled") !== "true") button.setAttribute("aria-disabled", "true");
      const title = button.getAttribute("aria-label") === motionLabel ? motionTooltip : tooltip;
      if (button.title !== title) button.title = title;
      if (button.style.opacity !== "0.45") button.style.opacity = "0.45";
      if (button.style.cursor !== "not-allowed") button.style.cursor = "not-allowed";
    });
  }

  function stopAction(event) {
    if (event.type === "keydown" && event.key !== "Enter" && event.key !== " ") return;
    const button = event.target instanceof Element ? event.target.closest("button") : null;
    if (!blocked(button)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  }

  document.addEventListener("click", stopAction, true);
  document.addEventListener("keydown", stopAction, true);
  // React replaces these buttons on panel changes. Update only changed
  // attributes to avoid an observer loop; iframe documents are not traversed.
  new MutationObserver(refresh).observe(document.documentElement, {
    subtree: true, childList: true, characterData: true, attributes: true,
    attributeFilter: ["disabled", "class", "title", "aria-label", "style"],
  });
  refresh();
})();
