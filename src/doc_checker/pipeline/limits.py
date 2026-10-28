# src/doc_checker/pipeline/limits.py
from dataclasses import dataclass

@dataclass(frozen=True)
class SafetyLimits:
    # Transport / file level
    max_upload_bytes: int = 20 * 1024 * 1024      # 20 MB (matches API spec)
    max_pages: int = 40

    # Rasterization / decompression bombs
    max_pixels_per_page: int = 40_000_000         # ~8000x5000
    max_total_pixels: int = 150_000_000
    max_render_seconds: int = 20

    # ZIP / embedded-archive bombs (INSPECTION ONLY, never extract)
    max_zip_members: int = 500
    max_uncompressed_bytes: int = 100 * 1024 * 1024
    max_compression_ratio: float = 100.0

    # PDF object graph walk
    max_pdf_objects: int = 20_000
    max_object_depth: int = 24

    # Hard sandbox around the inspector process
    child_memory_bytes: int = 512 * 1024 * 1024
    child_cpu_seconds: int = 5
    wall_timeout_seconds: int = 15