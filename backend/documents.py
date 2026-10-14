"""Turn an uploaded file into what a person would actually see on it.

Accepted: PDF, images (PNG, JPEG, WebP) and plain text (.txt, .md). The type is decided
from the file's bytes, not its name.

PDFs keep only visible text. Every character is checked, and these are dropped:
  - invisible render mode (PDF text mode 3 or 7)
  - text outside the page
  - tiny or zero-size fonts (under 3 pt, or squeezed to almost no width)
  - text the same color as what is behind it (white on white, gray on a gray box...)
  - text covered by a shape or image drawn on top of it
Each kind of dropped text is recorded on the document as a hidden-text flag, with a short
preview for the user. Dropped text is never sent to a model.

Pages that are mostly pictures (scans, photos of reports) are rendered to an image and
sent to vision instead of using their text layer. Images go straight to vision.
Invisible Unicode (zero-width, bidirectional and tag characters) is removed from all
text, and is flagged the same way.
"""

from __future__ import annotations

import hashlib
import io
import statistics
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pypdfium2 as pdfium
from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LTChar, LTComponent, LTCurve, LTFigure, LTImage, LTPage
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from PIL import Image, ImageOps

from . import defenses

MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_PDF_PAGES = 15
MAX_IMAGE_SIDE = 2000
RENDER_DPI = 150

TINY_FONT_PT = 3.0
MIN_CONTRAST = 1.25          # WCAG contrast ratio; white on #EEEEEE is about 1.16
IMAGE_PAGE_AREA = 0.30       # a page this covered by pictures is read with vision
MIN_TEXT_CHARS = 30          # ...as is a page with pictures and almost no visible text

TEXT_EXTENSIONS = {".txt", ".md", ".text"}
Kind = Literal["pdf", "image", "text"]
HiddenReason = Literal[
    "invisible_render_mode", "outside_page", "tiny_font", "background_color", "covered_by_shape", "invisible_unicode"
]
REASON_LABELS: dict[str, str] = {
    "invisible_render_mode": "text set to be invisible",
    "outside_page": "text placed outside the page",
    "tiny_font": "tiny or zero-size text",
    "background_color": "text the same color as its background",
    "covered_by_shape": "text covered by a shape or image",
    "invisible_unicode": "invisible Unicode characters",
}


class UnsupportedFile(ValueError):
    """The upload is not a file type the app reads; the message is shown to the user."""


@dataclass
class HiddenTextFlag:
    reason: HiddenReason
    page: int | None
    char_count: int
    preview: str  # for the user and the audit log only; never sent to a model

    @property
    def label(self) -> str:
        return REASON_LABELS[self.reason]


@dataclass
class Segment:
    """One page (or the whole file) of readable content."""
    page: int | None
    source: Literal["text", "vision"]
    text: str = ""
    image: bytes | None = None      # set when source == "vision"
    media_type: str | None = None


@dataclass
class DocumentText:
    filename: str
    sha256: str
    kind: Kind
    page_count: int
    segments: list[Segment]
    hidden_text: list[HiddenTextFlag] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def needs_vision(self) -> list[Segment]:
        return [s for s in self.segments if s.source == "vision" and not s.text]

    @property
    def text(self) -> str:
        """Everything readable, in page order (vision pages once transcribed)."""
        if len(self.segments) == 1:
            return self.segments[0].text
        return "\n\n".join(f"--- page {s.page} ---\n{s.text}" for s in self.segments)

    @property
    def read_by(self) -> str:
        sources = {s.source for s in self.segments}
        return "+".join(sorted(sources))


# ---- entry point ------------------------------------------------------------------------

def read_document(filename: str, data: bytes) -> DocumentText:
    if len(data) == 0:
        raise UnsupportedFile(f"{filename}: the file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise UnsupportedFile(f"{filename}: larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    kind = sniff_kind(filename, data)
    sha = hashlib.sha256(data).hexdigest()
    if kind == "pdf":
        doc = _read_pdf(filename, data, sha)
    elif kind == "image":
        doc = _read_image(filename, data, sha)
    else:
        doc = _read_text(filename, data, sha)
    suffix = Path(filename).suffix.lower()
    expected = {".pdf": "pdf", ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image"}
    if suffix in expected and expected[suffix] != kind or (suffix in TEXT_EXTENSIONS and kind != "text"):
        doc.notes.append(f"The file name says {suffix} but the content is {kind}; read as {kind}.")
    return doc


def read_path(path: Path) -> DocumentText:
    return read_document(path.name, path.read_bytes())


def sniff_kind(filename: str, data: bytes) -> Kind:
    head = data[:16]
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"\xff\xd8\xff") or (
        head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    ):
        return "image"
    if head[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1"):
        raise UnsupportedFile(f"{filename}: HEIC photos are not supported; export as JPEG or PNG.")
    if Path(filename).suffix.lower() in TEXT_EXTENSIONS and b"\x00" not in data[:4096]:
        return "text"
    raise UnsupportedFile(f"{filename}: only PDF, PNG, JPEG, WebP and .txt/.md files are accepted.")


# ---- text and invisible Unicode ---------------------------------------------------------

def clean_text(text: str, page: int | None = None) -> tuple[str, HiddenTextFlag | None]:
    """Remove invisible format characters (zero-width, bidi, tag) and stray control codes.

    Unicode tag characters (U+E0000-E007F) can spell out hidden ASCII; the preview decodes
    them so the user can see what was hidden.
    """
    kept: list[str] = []
    removed = 0
    decoded_tags: list[str] = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat == "Cf" or (cat == "Cc" and ch not in "\n\t\r"):
            removed += 1
            cp = ord(ch)
            if 0xE0020 <= cp <= 0xE007E:
                decoded_tags.append(chr(cp - 0xE0000))
            continue
        kept.append(ch)
    cleaned = "".join(kept).replace("\r\n", "\n").replace("\r", "\n")
    if not removed:
        return cleaned, None
    preview = f"{removed} invisible character(s) removed"
    if decoded_tags:
        preview += f'; hidden tag text read: "{"".join(decoded_tags)[:300]}"'
    return cleaned, HiddenTextFlag("invisible_unicode", page, removed, preview)


def _read_text(filename: str, data: bytes, sha: str) -> DocumentText:
    try:
        raw = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raw = data.decode("latin-1")
    text, flag = clean_text(raw)
    if not defenses.current().code:  # code layer off (safety tests only): keep the invisible characters
        text = raw.replace("\r\n", "\n")
    doc = DocumentText(filename, sha, "text", 1, [Segment(None, "text", text.strip())])
    if flag:
        doc.hidden_text.append(flag)
    return doc


# ---- images -----------------------------------------------------------------------------

def _prepare_image(data: bytes) -> tuple[bytes, str]:
    """Upright, RGB, at most MAX_IMAGE_SIDE pixels on the long side."""
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
    except Exception as exc:
        raise UnsupportedFile(f"The image could not be opened ({type(exc).__name__}).") from exc
    is_png = img.format == "PNG"
    img = img.convert("RGB")
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    out = io.BytesIO()
    if is_png:
        img.save(out, "PNG", optimize=True)
        return out.getvalue(), "image/png"
    img.save(out, "JPEG", quality=90)
    return out.getvalue(), "image/jpeg"


def _read_image(filename: str, data: bytes, sha: str) -> DocumentText:
    image, media_type = _prepare_image(data)
    return DocumentText(filename, sha, "image", 1, [Segment(None, "vision", image=image, media_type=media_type)])


# ---- PDFs: visible text only ------------------------------------------------------------

class _Aggregator(PDFPageAggregator):
    """Records the text render mode on each character (pdfminer does not keep it)."""

    def render_string(self, textstate, seq, ncs, graphicstate):  # type: ignore[override]
        container = self.cur_item
        start = len(container._objs)
        super().render_string(textstate, seq, ncs, graphicstate)
        for obj in container._objs[start:]:
            if isinstance(obj, LTChar):
                obj.render_mode = textstate.render  # type: ignore[attr-defined]


def _flatten(container, out: list[LTComponent]) -> None:
    """All objects in drawing order, including those inside form XObjects."""
    for obj in container:
        if isinstance(obj, LTFigure):
            _flatten(obj, out)
        else:
            out.append(obj)


def _to_rgb(color) -> tuple[float, float, float] | None:
    if color is None:
        return (0.0, 0.0, 0.0)
    if isinstance(color, (int, float)):
        v = float(color)
        return (v, v, v)
    if isinstance(color, (list, tuple)):
        vals = [float(c) for c in color if isinstance(c, (int, float))]
        if len(vals) == 1:
            return (vals[0],) * 3  # type: ignore[return-value]
        if len(vals) == 3:
            return (vals[0], vals[1], vals[2])
        if len(vals) == 4:
            c, m, y, k = vals
            return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None  # patterns and other color spaces: unknown, treated as visible


def _luminance(rgb: tuple[float, float, float]) -> float:
    def channel(v: float) -> float:
        v = min(max(v, 0.0), 1.0)
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _contains(box: LTComponent, x: float, y: float, tol: float = 0.5) -> bool:
    return box.x0 - tol <= x <= box.x1 + tol and box.y0 - tol <= y <= box.y1 + tol


def _char_color(ch: LTChar) -> tuple[float, float, float] | None:
    gs = ch.graphicstate
    mode = getattr(ch, "render_mode", 0)
    return _to_rgb(gs.scolor if mode in (1, 5) else gs.ncolor)


def _classify_page(page: LTPage) -> tuple[list[LTChar], dict[str, list[LTChar]], float]:
    """Split a page's characters into visible ones and dropped ones (by reason).

    Also returns the fraction of the page area covered by images.
    """
    objs: list[LTComponent] = []
    _flatten(page, objs)
    covers: list[tuple[int, LTComponent, tuple[float, float, float] | None]] = []
    page_area = max(page.width * page.height, 1.0)
    image_area = 0.0
    for i, obj in enumerate(objs):
        if isinstance(obj, LTImage):
            covers.append((i, obj, None))
            image_area += obj.width * obj.height
        elif isinstance(obj, LTCurve) and obj.fill and obj.width > 1 and obj.height > 1:
            covers.append((i, obj, _to_rgb(obj.non_stroking_color)))

    visible: list[LTChar] = []
    dropped: dict[str, list[LTChar]] = {}
    white = (1.0, 1.0, 1.0)
    for i, obj in enumerate(objs):
        if not isinstance(obj, LTChar):
            continue
        # Spaces go through the same checks (so a hidden line leaves no blank line behind)
        # but are not counted in the flags.
        cx, cy = (obj.x0 + obj.x1) / 2, (obj.y0 + obj.y1) / 2
        reason: str | None = None
        if getattr(obj, "render_mode", 0) in (3, 7):
            reason = "invisible_render_mode"
        elif not _contains(page, cx, cy, tol=0):
            reason = "outside_page"
        elif obj.size < TINY_FONT_PT or obj.width < 0.2:
            reason = "tiny_font"
        else:
            below = [c for c in covers if c[0] < i and _contains(c[1], cx, cy)]
            above = [c for c in covers if c[0] > i and _contains(c[1], cx, cy)]
            background = below[-1][2] if below else white
            color = _char_color(obj)
            if color is not None and background is not None and _contrast(color, background) < MIN_CONTRAST:
                reason = "background_color"
            elif above:
                reason = "covered_by_shape"
        if reason:
            dropped.setdefault(reason, []).append(obj)
        else:
            visible.append(obj)
    return visible, dropped, min(image_area / page_area, 1.0)


def chars_to_text(chars: list[LTChar]) -> str:
    """Rebuild lines from positioned characters, keeping table columns roughly aligned."""
    if not chars:
        return ""
    ordered = sorted(chars, key=lambda c: (-(c.y0 + c.y1) / 2, c.x0))
    lines: list[list[LTChar]] = []
    line_y: list[float] = []
    for c in ordered:
        yc = (c.y0 + c.y1) / 2
        if lines and abs(line_y[-1] - yc) <= max(1.0, 0.4 * c.size):
            lines[-1].append(c)
        else:
            lines.append([c])
            line_y.append(yc)
    out: list[str] = []
    prev_y: float | None = None
    for line, y in zip(lines, line_y):
        line.sort(key=lambda c: c.x0)
        widths = [c.width for c in line if c.get_text().strip()]
        avg_w = statistics.median(widths) if widths else 5.0
        height = statistics.median(c.size for c in line)
        if prev_y is not None and prev_y - y > 1.9 * height:
            out.append("")
        parts: list[str] = []
        prev_x1: float | None = None
        for c in line:
            t = c.get_text()
            if prev_x1 is not None and t.strip() and c.x0 - prev_x1 > 0.3 * avg_w and not (parts and parts[-1] == " "):
                parts.append(" " * min(8, max(1, round((c.x0 - prev_x1) / avg_w))))
            parts.append(t)
            prev_x1 = c.x1
        out.append("".join(parts).rstrip())
        prev_y = y
    return "\n".join(out).strip()


def _render_page(pdf: pdfium.PdfDocument, index: int) -> bytes:
    bitmap = pdf[index].render(scale=RENDER_DPI / 72)
    img = bitmap.to_pil().convert("RGB")
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def _read_pdf(filename: str, data: bytes, sha: str) -> DocumentText:
    try:
        rendered = pdfium.PdfDocument(data)
    except Exception as exc:
        raise UnsupportedFile(f"{filename}: the PDF could not be opened (damaged or password-protected).") from exc
    total_pages = len(rendered)
    manager = PDFResourceManager()
    device = _Aggregator(manager, laparams=None)
    interpreter = PDFPageInterpreter(manager, device)

    doc = DocumentText(filename, sha, "pdf", min(total_pages, MAX_PDF_PAGES), [])
    if total_pages > MAX_PDF_PAGES:
        doc.notes.append(f"Only the first {MAX_PDF_PAGES} of {total_pages} pages were read.")
    for number, page in enumerate(PDFPage.get_pages(io.BytesIO(data), maxpages=MAX_PDF_PAGES), start=1):
        interpreter.process_page(page)
        layout = device.get_result()
        visible, dropped, image_fraction = _classify_page(layout)
        if not defenses.current().code:  # code layer off (safety tests only): read hidden text as if visible
            visible = visible + [c for chars in dropped.values() for c in chars]
        for reason, chars in dropped.items():
            count = sum(1 for c in chars if c.get_text().strip())
            if count:
                preview = chars_to_text(chars)
                doc.hidden_text.append(HiddenTextFlag(reason, number, count, preview[:300]))  # type: ignore[arg-type]
        text, unicode_flag = clean_text(chars_to_text(visible), page=number)
        if not defenses.current().code:
            text = chars_to_text(visible)
        if unicode_flag:
            doc.hidden_text.append(unicode_flag)
        visible_count = sum(1 for c in visible if c.get_text().strip())
        if image_fraction >= IMAGE_PAGE_AREA or (image_fraction > 0 and visible_count < MIN_TEXT_CHARS):
            doc.segments.append(Segment(number, "vision", image=_render_page(rendered, number - 1), media_type="image/png"))
        elif visible_count == 0:
            doc.segments.append(Segment(number, "text", ""))
        else:
            doc.segments.append(Segment(number, "text", text))
    rendered.close()
    if not any(s.text or s.image for s in doc.segments):
        doc.notes.append("No readable content was found in this PDF.")
    return doc
