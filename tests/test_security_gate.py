# tests/test_security_gate.py
import zipfile
from pathlib import Path
import pytest
import pikepdf
from PIL import Image

from doc_checker.pipeline.security_gate import security_gate
from doc_checker.pipeline.limits import SafetyLimits


def _good_pdf(p: Path):
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page(page_size=(595, 842))
        pdf.save(p)


def test_clean_pdf_allowed(tmp_path):
    p = tmp_path / "clean.pdf"; _good_pdf(p)
    r = security_gate(p, tmp_path / "q")
    assert r.verdict == "allowed"
    assert r.page_count == 1


def test_renamed_executable_blocked(tmp_path):
    p = tmp_path / "statement.pdf"
    p.write_bytes(b"\x7fELF" + b"\x00" * 500)
    r = security_gate(p, tmp_path / "q")
    assert r.verdict == "blocked"
    assert "UNSUPPORTED_OR_EXECUTABLE_PAYLOAD" in r.finding_codes
    assert r.quarantined_to.exists()


def test_zip_bomb_blocked_without_extraction(tmp_path):
    p = tmp_path / "payload.zip"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("huge.txt", b"0" * (20 * 1024 * 1024))
    r = security_gate(p, tmp_path / "q",
                      SafetyLimits(max_uncompressed_bytes=5 * 1024 * 1024))
    assert r.verdict == "blocked"
    assert any("BOMB" in c for c in r.finding_codes)


def test_png_pixel_bomb_blocked(tmp_path):
    p = tmp_path / "scan.png"
    im = Image.new("L", (9000, 9000))   # header only, never rendered
    im.save(p)
    r = security_gate(p, tmp_path / "q",
                      SafetyLimits(max_pixels_per_page=40_000_000))
    assert r.verdict == "blocked"
    assert "IMAGE_PIXEL_BOMB" in r.finding_codes


def test_path_traversal_zip_blocked(tmp_path):
    p = tmp_path / "x.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("../../etc/passwd", "nope")
    r = security_gate(p, tmp_path / "q")
    assert "ZIP_PATH_TRAVERSAL" in r.finding_codes