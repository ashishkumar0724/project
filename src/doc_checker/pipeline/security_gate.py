# src/doc_checker/pipeline/security_gate.py
from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from PIL import Image

from ..schemas import SecurityReport
from .limits import SafetyLimits

try:
    import resource
    HAS_RESOURCE = True
except ImportError:
    HAS_RESOURCE = False

SIGNATURES = {
    b"%PDF": "pdf",
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpeg",
    b"PK\x03\x04": "zip",
    b"\x1f\x8b": "gzip",
    b"\xd0\xcf\x11\xe0": "ole",
    b"\x7fELF": "elf",
    b"MZ": "pe",
}

EXT_TO_SIG = {"pdf": "pdf", "png": "png", "jpg": "jpeg", "jpeg": "jpeg"}

PDF_BLOCK_KEYS = {
    "/JS", "/JavaScript", "/Launch", "/EmbeddedFile", "/EmbeddedFiles",
    "/GoToR", "/SubmitForm", "/RichMedia", "/XFA", "/AA", "/OpenAction",
}
PDF_REVIEW_KEYS = {"/AcroForm", "/Annots", "/Metadata"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sniff(path: Path) -> str:
    with path.open("rb") as f:
        head = f.read(64)
    for magic, name in SIGNATURES.items():
        if head.lstrip(b"\r\n\t ").startswith(magic):
            return name
    return "unknown"


def _check_zip_bomb_metadata(path: Path, limits: SafetyLimits) -> list[str]:
    bad = []
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > limits.max_zip_members:
                bad.append(f"ZIP_MEMBER_FLOOD: {len(infos)} entries")
            total = 0
            for i in infos:
                total += i.file_size
                ratio = i.file_size / max(i.compress_size, 1)
                if ratio > limits.max_compression_ratio:
                    bad.append(f"ZIP_RATIO_BOMB: {i.filename!r} ratio={ratio:.0f}")
                if total > limits.max_uncompressed_bytes:
                    bad.append("ZIP_EXPANSION_BOMB: declared uncompressed size exceeds budget")
                name = Path(i.filename)
                if name.is_absolute() or ".." in name.parts:
                    bad.append(f"ZIP_PATH_TRAVERSAL: {i.filename!r}")
                if (i.external_attr >> 16) & 0o170000 == 0o120000:
                    bad.append(f"ZIP_SYMLINK: {i.filename!r}")
    except Exception as e:
        bad.append(f"ZIP_PARSE_FAILED: {type(e).__name__}")
    return bad


def _walk_pdf(path: Path, limits: SafetyLimits) -> tuple[list[str], list[str], int]:
    """Object-graph walk. Fixed: uses objgen for deduplication to prevent infinite loops."""
    import pikepdf

    blocked, review = [], []
    with pikepdf.Pdf.open(path) as pdf:
        if pdf.is_encrypted:
            return ["PDF_ENCRYPTED_UNINSPECTABLE"], [], 0

        pages = len(pdf.pages)
        if pages > limits.max_pages:
            blocked.append(f"PDF_PAGE_BOMB: {pages} pages")

        stack = [pdf.trailer]
        seen_objgens = set()  # Track unique PDF objects by (num, gen)
        processed_count = 0

        while stack:
            if processed_count > limits.max_pdf_objects:
                blocked.append("PDF_OBJECT_FLOOD")
                break

            obj = stack.pop()
            
            # Deduplication: skip if we've already visited this specific PDF object
            if hasattr(obj, 'objgen'):
                if obj.objgen in seen_objgens:
                    continue
                seen_objgens.add(obj.objgen)
            
            processed_count += 1

            if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
                for key in obj.keys():
                    k = f"/{key}"
                    if k in PDF_BLOCK_KEYS:
                        blocked.append(f"PDF_ACTIVE_CONTENT: {k}")
                    elif k in PDF_REVIEW_KEYS:
                        review.append(f"PDF_REVIEW_FEATURE: {k}")
                    if k in ("/Length", "/Filter"):
                        continue
                    try:
                        stack.append(obj[key])
                    except Exception:
                        pass
            elif isinstance(obj, pikepdf.Array):
                for item in obj:
                    stack.append(item)

    return list(dict.fromkeys(blocked)), list(dict.fromkeys(review)), pages


def _image_headers(path: Path, limits: SafetyLimits) -> tuple[list[list[int]], list[str]]:
    dims, bad = [], []
    try:
        with Image.open(path) as im:
            w, h = im.size
            dims.append([w, h])
            if w * h > limits.max_pixels_per_page:
                bad.append(f"IMAGE_PIXEL_BOMB: {w}x{h} = {w*h} pixels")
            if getattr(im, "n_frames", 1) > limits.max_pages:
                bad.append("IMAGE_FRAME_FLOOD")
    except Exception:
        bad.append("IMAGE_HEADER_INVALID")
    return dims, bad


def _run_inspection(file_path_str: str, quarantine_dir_str: str, limits_dict: dict) -> dict:
    path = Path(file_path_str)
    quarantine_dir = Path(quarantine_dir_str)
    limits = SafetyLimits(**limits_dict)
    
    report_dict = {
        "verdict": "blocked", "sha256": "", "size_bytes": 0,
        "declared_extension": "", "detected_signature": "unknown",
        "signature_matches_extension": False, "page_count": None,
        "image_dimensions": [], "reasons": [], "finding_codes": [],
        "sandbox_level": "rlimit" if HAS_RESOURCE else "process_only",
        "quarantined_to": None,
    }
    
    try:
        report_dict["size_bytes"] = path.stat().st_size
        report_dict["sha256"] = _sha256(path)
        report_dict["declared_extension"] = path.suffix.lower().lstrip(".")
        report_dict["detected_signature"] = _sniff(path)
        expected = EXT_TO_SIG.get(report_dict["declared_extension"])
        report_dict["signature_matches_extension"] = (report_dict["detected_signature"] == expected)

        reasons, codes = [], []

        if report_dict["size_bytes"] > limits.max_upload_bytes:
            codes.append("SIZE_EXCEEDED")
        if not report_dict["signature_matches_extension"]:
            codes.append("SIGNATURE_EXTENSION_MISMATCH")
        if report_dict["detected_signature"] in {"elf", "pe", "ole", "gzip", "unknown"}:
            codes.append("UNSUPPORTED_OR_EXECUTABLE_PAYLOAD")
        if "\x00" in path.name or path.name.count(".") > 1:
            codes.append("SUSPICIOUS_FILENAME")

        if report_dict["detected_signature"] == "pdf" and not codes:
            blocked, review, pages = _walk_pdf(path, limits)
            report_dict["page_count"] = pages
            codes += blocked
            reasons += review
        elif report_dict["detected_signature"] == "zip":
            codes += _check_zip_bomb_metadata(path, limits)
        elif report_dict["detected_signature"] in {"png", "jpeg"}:
            dims, bad = _image_headers(path, limits)
            report_dict["image_dimensions"] = dims
            codes += bad

        with path.open("rb") as f:
            f.seek(max(0, report_dict["size_bytes"] - 4096))
            tail = f.read()
        if report_dict["detected_signature"] == "pdf" and b"%%EOF" in tail:
            after = tail.split(b"%%EOF")[-1].strip()
            if len(after) > 64:
                reasons.append("PDF_TRAILING_DATA: possible polyglot payload")

        report_dict["reasons"] = reasons
        report_dict["finding_codes"] = codes + [r.split(":")[0] for r in reasons if r.startswith("PDF_TRAILING")]

        if codes:
            report_dict["verdict"] = "blocked"
        elif reasons:
            report_dict["verdict"] = "needs_review"
        else:
            report_dict["verdict"] = "allowed"

    except Exception as e:
        report_dict["verdict"] = "blocked"
        report_dict["finding_codes"].append("INSPECTOR_CRASHED")
        report_dict["reasons"].append(f"Inspector failed safely: {type(e).__name__}")

    return report_dict


def security_gate(file_path: Path,
                  quarantine_dir: Path = Path("quarantine"),
                  limits: Optional[SafetyLimits] = None) -> SecurityReport:
    from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeoutError
    
    limits = limits or SafetyLimits()
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    file_path = Path(file_path).resolve()

    limits_dict = {
        "max_upload_bytes": limits.max_upload_bytes, "max_pages": limits.max_pages,
        "max_pixels_per_page": limits.max_pixels_per_page, "max_total_pixels": limits.max_total_pixels,
        "max_render_seconds": limits.max_render_seconds, "max_zip_members": limits.max_zip_members,
        "max_uncompressed_bytes": limits.max_uncompressed_bytes, "max_compression_ratio": limits.max_compression_ratio,
        "max_pdf_objects": limits.max_pdf_objects, "max_object_depth": limits.max_object_depth,
        "child_memory_bytes": limits.child_memory_bytes, "child_cpu_seconds": limits.child_cpu_seconds,
        "wall_timeout_seconds": limits.wall_timeout_seconds,
    }

    try:
        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_inspection, str(file_path), str(quarantine_dir), limits_dict)
            report_dict = future.result(timeout=limits.wall_timeout_seconds)
    except FuturesTimeoutError:
        report_dict = {"verdict": "blocked", "finding_codes": ["INSPECTION_TIMEOUT"], "reasons": ["Timeout"], "sandbox_level": "process_only"}
    except Exception as e:
        report_dict = {"verdict": "blocked", "finding_codes": ["INSPECTOR_CRASHED"], "reasons": [str(e)], "sandbox_level": "process_only"}

    report = SecurityReport(**report_dict)

    if report.verdict != "allowed":
        qpath = quarantine_dir / f"{report.sha256 or 'unknown'}.quarantined"
        try:
            shutil.move(str(file_path), str(qpath))
            qpath.chmod(0o600)
            report.quarantined_to = qpath
        except Exception:
            pass

    return report