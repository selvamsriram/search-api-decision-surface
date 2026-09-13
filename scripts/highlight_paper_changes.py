#!/usr/bin/env python3
"""Annotate both PDFs using the actual submitted PDF as the comparison source.

Ignores review line/page numbers and ordinary line wrapping. Yellow/red mark
new/old unmatched text; blue marks matching passages relocated in reading order.
The original PDFs are read-only. Requires PyMuPDF.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
import hashlib
import json
import re
import unicodedata

import pymupdf as fitz


ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "Submitted_72_Equal_Accuracy_Unequal_Evid.pdf"
NEW = ROOT / "output/pdf/camera-ready.pdf"


@dataclass
class Token:
    text: str
    locations: list = field(default_factory=list)

    @property
    def normalized(self):
        text = unicodedata.normalize("NFKC", self.text).replace("\u00ad", "")
        text = text.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'}))
        return re.sub(r"(?<=[A-Za-z])-(?=[A-Za-z])", "", text)


def tokens(document):
    result = []
    for page_id, page in enumerate(document):
        for x0, y0, x1, y1, word, block, line, _ in page.get_text("words", sort=False):
            if word.isdigit() and (x1 < 65 or x0 > 530 or y0 > 790):
                continue
            location = (page_id, (x0, y0, x1, y1), (page_id, block, line))
            if (result and len(result[-1].text) > 1
                    and result[-1].text.endswith(("-", "_"))
                    and result[-1].locations[-1][2] != location[2]):
                previous = result[-1]
                previous.text = previous.text.removesuffix("-") + word
                previous.locations.append(location)
            else:
                result.append(Token(word, [location]))
    return result


def classify(old, new):
    a = [t.normalized for t in old]
    b = [t.normalized for t in new]
    sa, sb = ["same"] * len(a), ["same"] * len(b)
    changes = []
    for tag, i, j, k, l in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        sa[i:j], sb[k:l] = ["old"] * (j - i), ["new"] * (l - k)
        changes.append({"kind": tag, "old_range": [i, j], "new_range": [k, l]})
    # Detect exact passages relocated by float, section, or table movement.
    # Keep separators between unmatched runs so matches cannot cross kept text.
    def unmatched(words, statuses):
        values, indices = [], []
        for i, (word, state) in enumerate(zip(words, statuses)):
            if state != "same":
                values.append(word); indices.append(i)
            elif values and indices[-1] is not None:
                values.append(object()); indices.append(None)
        return values, indices
    av, ai = unmatched(a, sa)
    bv, bi = unmatched(b, sb)
    for match in SequenceMatcher(None, av, bv, autojunk=False).get_matching_blocks():
        if match.size < 8:
            continue
        for offset in range(match.size):
            sa[ai[match.a + offset]] = "moved"
            sb[bi[match.b + offset]] = "moved"
    return sa, sb, changes


def annotate(document, words, statuses, side):
    colors = {"old": (1, .55, .55), "new": (1, .9, .1), "moved": (.45, .78, 1)}
    groups = defaultdict(list)
    for token, status in zip(words, statuses):
        if status == "same":
            continue
        for page, rect, line in token.locations:
            groups[(page, line, status)].append(fitz.Rect(rect))
    for (page, _, status), rects in groups.items():
        # Separate nonadjacent changed phrases on the same printed line.
        runs = []
        for rect in sorted(rects, key=lambda r: r.x0):
            if runs and rect.x0 - runs[-1].x1 < 6:
                runs[-1] |= rect
            else:
                runs.append(rect)
        for rect in runs:
            pdf_page = document[page]
            annotation = pdf_page.add_highlight_annot(rect)
            annotation.set_colors(stroke=colors[status])
            annotation.set_opacity(.32)
            annotation.set_info(title="Submitted vs. camera-ready", content={
                "new": "Added or revised wording in the camera-ready version.",
                "old": "Removed or revised wording from the submitted version.",
                "moved": "Matching text relocated in reading order (including floats/tables).",
            }[status])
            annotation.update()
    for i, page in enumerate(document):
        legend = ("REVIEW COPY | Yellow: added/revised | Blue: moved text" if side == "new" else
                  "SUBMITTED COMPARISON | Red: removed/revised | Blue: moved text")
        page.insert_text((70.9, 37), legend, fontsize=8, color=(.18, .23, .30))
        page.insert_text((70.9, 49), "Comparison ignores review numbering and line wrapping. See change log for formatting and links.",
                         fontsize=7, color=(.3, .35, .4))


def image_inventory(document):
    images = []
    for page_id, page in enumerate(document):
        for item in page.get_images(full=True):
            digest = hashlib.sha256(document.extract_image(item[0])["image"]).hexdigest()
            for rect in page.get_image_rects(item[0]):
                images.append((page_id, rect, digest, item[2:4]))
    return images


def main():
    old, new = fitz.open(OLD), fitz.open(NEW)
    aw, bw = tokens(old), tokens(new)
    sa, sb, edits = classify(aw, bw)
    images_old, images_new = image_inventory(old), image_inventory(new)
    annotate(old, aw, sa, "old"); annotate(new, bw, sb, "new")
    image_changes = []
    for document, inventory, other, color in [
        (old, images_old, images_new, (1, .3, .3)),
        (new, images_new, images_old, (.9, .6, 0)),
    ]:
        other_hashes = {im[2] for im in other}
        for page_id, rect, digest, dimensions in inventory:
            if digest in other_hashes:
                continue
            pdf_page = document[page_id]
            annotation = pdf_page.add_rect_annot(rect)
            annotation.set_colors(stroke=color)
            annotation.set_border(width=1.8)
            annotation.set_info(title="Changed figure", content="Figure 3: corrected decision-cell counts after the Gate 2 action audit.")
            annotation.update()
            image_changes.append({"side": "old" if document is old else "new",
                                  "page": page_id + 1, "pixel_dimensions": dimensions})
    old.save(ROOT / "output/pdf/submitted-highlighted.pdf", garbage=4, deflate=True)
    new.save(ROOT / "output/pdf/camera-ready-highlighted.pdf", garbage=4, deflate=True)
    report = {
        "baseline": str(OLD.relative_to(ROOT)),
        "baseline_sha256": hashlib.sha256(OLD.read_bytes()).hexdigest(),
        "camera_ready_sha256": hashlib.sha256(NEW.read_bytes()).hexdigest(),
        "old_word_status": dict(Counter(sa)), "new_word_status": dict(Counter(sb)),
        "image_changes": image_changes,
        "formatting_changes": ["Author block and PDF metadata", "Review line/page numbers removed",
                               "Official ACL spacing restored", "Section 4 schema enlarged",
                               "Limitations moved after conclusion", "Reference hyperlinks added"],
        "edits": [{**e,
                   "old_text": " ".join(t.text for t in aw[slice(*e['old_range'])]),
                   "new_text": " ".join(t.text for t in bw[slice(*e['new_range'])])}
                  for e in edits],
    }
    (ROOT / "output/comparison-manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "edits"}, indent=2))


if __name__ == "__main__":
    main()
