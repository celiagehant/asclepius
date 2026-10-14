"""Render the synthetic documents into data/test_cases/<case>/documents/.

    .venv/bin/python scripts/make_test_cases.py

Only needed if you edit `synthetic_documents.py`; the rendered files are committed.
The questionnaires (profile.json) and answer keys (expected.json) are hand-written
and are not touched by this script.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from synthetic_documents import BANNER, CASES  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "test_cases"
MONO_FONTS = ["/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Courier.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "C:/Windows/Fonts/consola.ttf"]


def _with_banner(text: str) -> str:
    return f"{BANNER}\n\n{text.rstrip()}\n\n{BANNER}\n"


def write_txt(path: Path, text: str) -> None:
    path.write_text(_with_banner(text), encoding="utf-8")


def write_pdf(path: Path, text: str) -> None:
    pdf = FPDF(format="letter")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Courier", size=9)
    for line in _with_banner(text).splitlines():
        pdf.cell(0, 4.4, line.encode("latin-1", "replace").decode("latin-1"), new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def _page_image(text: str, rng: random.Random, photo: bool) -> Image.Image:
    font = next((ImageFont.truetype(f, 21) for f in MONO_FONTS if Path(f).exists()), None)
    font = font or ImageFont.load_default(size=21)
    lines = _with_banner(text).splitlines()
    width, line_h, margin = 1275, 30, 70
    height = max(1650, margin * 2 + line_h * len(lines))
    paper = (250, 249, 244) if photo else (255, 255, 255)
    img = Image.new("RGB", (width, height), paper)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((margin, margin + i * line_h), line, fill=(25, 25, 30), font=font)
    if photo:
        # A little like a phone photo or scan: slight tilt, soft focus, a few specks.
        for _ in range(250):
            x, y = rng.randrange(width), rng.randrange(height)
            draw.point((x, y), fill=(200, 200, 195))
        img = img.rotate(rng.uniform(-0.8, 0.8), expand=True, fillcolor=(232, 230, 224))
        img = img.filter(ImageFilter.GaussianBlur(0.6))
    return img


def write_image(path: Path, text: str, rng: random.Random) -> None:
    photo = path.suffix == ".jpg"
    img = _page_image(text, rng, photo=photo)
    if photo:
        img.save(path, quality=82)
    else:
        img.save(path, optimize=True)


def write_scan_pdf(path: Path, text: str, rng: random.Random) -> None:
    img = _page_image(text, rng, photo=True).convert("L")
    img.save(path, "PDF", resolution=150)


def main() -> None:
    rng = random.Random(409)
    for case_id, documents in CASES.items():
        doc_dir = OUT_DIR / case_id / "documents"
        doc_dir.mkdir(parents=True, exist_ok=True)
        for old in doc_dir.iterdir():
            old.unlink()
        for filename, text in documents:
            path = doc_dir / filename
            if path.suffix == ".txt":
                write_txt(path, text)
            elif path.suffix in (".png", ".jpg"):
                write_image(path, text, rng)
            elif filename.endswith("_scanned.pdf"):
                write_scan_pdf(path, text, rng)
            else:
                write_pdf(path, text)
            print(f"  {case_id}/documents/{filename}  ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
