# src/doc_checker/schemas.py
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from pathlib import Path

class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float

class Finding(BaseModel):
    page_number: int
    region_bbox: Optional[BoundingBox] = None
    detector_id: str
    detector_version: str
    reason: str
    raw_score: float = Field(ge=0.0, le=1.0)
    finding_code: str

class SecurityReport(BaseModel):
    verdict: Literal["allowed", "needs_review", "blocked"] = "blocked"
    sha256: str = ""
    size_bytes: int = 0
    declared_extension: str = ""
    detected_signature: str = "unknown"
    signature_matches_extension: bool = False
    page_count: Optional[int] = None
    image_dimensions: List[List[int]] = []
    reasons: List[str] = []
    finding_codes: List[str] = []
    sandbox_level: str = "process_only"
    quarantined_to: Optional[Path] = None

class DocumentContext(BaseModel):
    """The central object passed through the entire pipeline."""
    doc_id: str
    original_path: Path
    
    # Stage 0: Security
    security_report: Optional[SecurityReport] = None
    
    # Stage 1: Normalization
    page_image_paths: List[Path] = []
    
    # Stage 2: Classification
    render_class: Optional[Literal["native_text", "scanned", "unknown"]] = None
    doc_type: Optional[Literal["bank_statement", "salary_slip", "pan_card", "unknown"]] = None
    
    # Stage 3: Extraction
    extracted_text: List[str] = [] # Text per page
    extracted_tables: List[List[List[str]]] = [] # Tables per page (list of rows, list of cells)
    
    # Stage 4 & 5: Detection & Aggregation (Future)
    findings: List[Finding] = []
    triage_band: Optional[Literal["low_risk", "needs_review", "high_risk"]] = None
    calibrated_score: Optional[float] = None