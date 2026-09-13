"use strict";

document.documentElement.classList.add("js-enabled");
const copyButton = document.getElementById("copy-citation");
const copyStatus = document.getElementById("copy-status");
let resetTimer;

copyButton.addEventListener("click", async () => {
  const citation = document.getElementById("bibtex");
  clearTimeout(resetTimer);
  try {
    await navigator.clipboard.writeText(citation.textContent);
    copyStatus.textContent = "BibTeX copied to clipboard.";
    copyButton.textContent = "Copied ✓";
    resetTimer = setTimeout(() => {
      copyButton.textContent = "Copy BibTeX ⧉";
    }, 2500);
  } catch {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(citation);
    selection.removeAllRanges();
    selection.addRange(range);
    copyStatus.textContent = "Copy the selected citation, or use Download .bib.";
  }
});
