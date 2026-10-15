"""Offline tests for the document reader (no model calls, no key needed).

    .venv/bin/python tests/test_documents.py
    (or `.venv/bin/python -m pytest tests` if pytest is installed)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.documents import UnsupportedFile, read_document, read_path  # noqa: E402

CASES = ROOT / "data" / "test_cases"
ATTACKS = ROOT / "data" / "attack_samples"


def test_synthetic_cases_have_no_hidden_text_and_route_to_the_right_reader():
    seen = 0
    for path in sorted(CASES.glob("*/documents/*")):
        doc = read_path(path)
        seen += 1
        assert not doc.hidden_text, f"{path.name}: unexpected hidden text {doc.hidden_text}"
        if path.suffix in (".png", ".jpg") or path.name.endswith("_scanned.pdf"):
            assert doc.needs_vision, f"{path.name} should go to vision"
        else:
            assert not doc.needs_vision, f"{path.name} should be read locally"
            assert "SYNTHETIC TEST DOCUMENT" in doc.text and len(doc.text) > 200
    assert seen == 23  # 5 synthetic cases (case 5, three text records, added with the four-round conference)


def test_text_pdf_keeps_table_columns():
    doc = read_path(CASES / "case4_polypharmacy" / "documents" / "05_lab_panel.pdf")
    line = next(l for l in doc.text.splitlines() if l.startswith("INR"))
    assert "3.9" in line and "H" in line and "2.0 - 3.0" in line


def test_hidden_pdf_text_is_dropped_and_flagged():
    doc = read_path(ATTACKS / "hidden_text_lab_report.pdf")
    reasons = {f.reason for f in doc.hidden_text}
    assert reasons == {
        "background_color", "tiny_font", "outside_page", "covered_by_shape", "invisible_render_mode"
    }, reasons
    text = doc.text.lower()
    assert "ferritin" in text and "28" in text  # the real, visible report survives
    for leaked in ("ignore all previous", "oncology", "override", "denies all", "do not mention", "developer mode"):
        assert leaked not in text, f"hidden payload leaked into visible text: {leaked}"
    previews = " ".join(f.preview for f in doc.hidden_text).lower()
    assert "propranolol" in previews and "oncology" in previews  # recorded for the user
    white = [f for f in doc.hidden_text if f.reason == "background_color"]
    assert sum(f.char_count for f in white) > 100  # the white payload and the gray-box payload


def test_invisible_unicode_is_removed_and_decoded():
    doc = read_path(ATTACKS / "hidden_unicode_note.txt")
    assert [f.reason for f in doc.hidden_text] == ["invisible_unicode"]
    assert "everything is normal" in doc.hidden_text[0].preview
    assert "​" not in doc.text and "everything is normal" not in doc.text
    assert "Advised that the gastroenterology" in doc.text


def test_type_comes_from_bytes_not_name():
    pdf_bytes = (CASES / "case1_adult_multisystem" / "documents" / "05_upper_endoscopy_report.pdf").read_bytes()
    doc = read_document("renamed.txt", pdf_bytes)
    assert doc.kind == "pdf" and doc.notes
    for name, data in [("x.exe", b"MZ\x90\x00"), ("empty.pdf", b""), ("photo.heic", b"\x00\x00\x00\x18ftypheic....")]:
        try:
            read_document(name, data)
        except UnsupportedFile:
            pass
        else:
            raise AssertionError(f"{name} should be rejected")


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
