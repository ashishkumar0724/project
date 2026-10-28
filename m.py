#!/usr/bin/env python3
"""
Project Bootstrap Script for AI Loan Document Checker
Creates the complete project structure with all necessary files.
Files are created RELATIVE TO THIS SCRIPT'S LOCATION.
"""

import os
import sys
from pathlib import Path

def create_file(path: Path, content: str):
    """Create a file with the given content, creating parent directories if needed."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        # Verify the file was actually created
        if path.exists():
            print(f"✅ Created: {path}")
        else:
            print(f"❌ FAILED to create: {path}")
    except Exception as e:
        print(f"❌ ERROR creating {path}: {e}")

def setup_project():
    """Set up the complete project structure."""
    
    # CRITICAL FIX: Use the script's location, NOT the current working directory
    base_dir = Path(__file__).parent.resolve()
    
    print(f"\n📍 Script location: {__file__}")
    print(f"📍 Files will be created in: {base_dir}")
    print(f"📍 Current working directory: {Path.cwd()}")
    print("=" * 70)
    
    # Directory structure
    directories = [
        "src/doc_checker/pipeline/detectors",
        "src/doc_checker/ui",
        "temp_outputs",
        "temp_uploads",
        "tests"
    ]
    
    # Create directories
    print("\n📁 Creating directories...")
    for directory in directories:
        dir_path = base_dir / directory
        dir_path.mkdir(parents=True, exist_ok=True)
        if dir_path.exists():
            print(f"  ✅ {directory}")
        else:
            print(f"  ❌ FAILED: {directory}")
    
    # Create __init__.py files
    init_files = [
        "src/doc_checker/__init__.py",
        "src/doc_checker/pipeline/__init__.py",
        "src/doc_checker/pipeline/detectors/__init__.py",
        "src/doc_checker/ui/__init__.py",
        "tests/__init__.py"
    ]
    
    print("\n📄 Creating __init__.py files...")
    for init_file in init_files:
        create_file(base_dir / init_file, "")
    
    # Create schemas.py
    schemas_content = '''from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from pathlib import Path

class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float

class Finding(BaseModel):
    """The universal output of any detector."""
    page_number: int
    region_bbox: Optional[BoundingBox] = None
    detector_id: str
    detector_version: str
    reason: str
    raw_score: float = Field(ge=0.0, le=1.0)
    finding_code: str

class DocumentContext(BaseModel):
    """The central object passed through the entire pipeline."""
    doc_id: str
    original_path: Path
    
    # Stage 2: Classification
    doc_type: Optional[Literal["bank_statement", "salary_slip", "pan_card", "unknown"]] = None
    is_native_pdf: bool = False
    
    # Stage 1 & 3: Normalization & Extraction
    page_image_paths: List[Path] = []
    extracted_text: List[str] = []
    
    # Stage 4 & 5: Detection & Aggregation
    findings: List[Finding] = []
    triage_band: Optional[Literal["low_risk", "needs_review", "high_risk"]] = None
    calibrated_score: Optional[float] = None
'''
    print("\n📄 Creating schemas.py...")
    create_file(base_dir / "src/doc_checker/schemas.py", schemas_content)
    
    # Create normalizer.py
    normalizer_content = '''import pypdfium2 as pdfium
from pathlib import Path
import uuid
from ..schemas import DocumentContext

def normalize_document(file_path: Path, output_dir: Path) -> DocumentContext:
    """
    Stage 1: Ingest and normalise.
    Persists original bytes, renders pages to 300 dpi images.
    """
    doc_id = str(uuid.uuid4())
    doc_ctx = DocumentContext(doc_id=doc_id, original_path=file_path)
    
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load PDF
    pdf = pdfium.PdfDocument(str(file_path))
    n_pages = len(pdf)
    
    # Rasterize each page at 300 DPI (Scale factor: 300 / 72 = 4.166)
    scale_factor = 300 / 72 
    
    for i in range(n_pages):
        page = pdf[i]
        bitmap = page.render(scale=scale_factor)
        pil_image = bitmap.to_pil()
        
        # Save as PNG for downstream image forensics
        img_path = output_dir / f"{doc_id}_page_{i+1}.png"
        pil_image.save(img_path)
        doc_ctx.page_image_paths.append(img_path)
        
    pdf.close()
    return doc_ctx
'''
    print("\n📄 Creating normalizer.py...")
    create_file(base_dir / "src/doc_checker/pipeline/normalizer.py", normalizer_content)
    
    # Create app.py (Streamlit UI)
    app_content = '''import streamlit as st
from pathlib import Path
import sys

# Add src to path so we can import our modules
sys.path.append(str(Path(__file__).parent.parent.parent))

from doc_checker.pipeline.normalizer import normalize_document

st.set_page_config(page_title="AI Loan Doc Checker", layout="wide")
st.title("🏦 Module 1: AI Document Checker")
st.markdown("### Step 1: Ingestion & Normalization (300 DPI Rasterization)")

# --- File Upload ---
uploaded_file = st.file_uploader("Upload a Loan Document (PDF)", type=["pdf"])

if uploaded_file is not None:
    # 1. Save uploaded file temporarily
    temp_dir = Path("temp_uploads")
    temp_dir.mkdir(exist_ok=True)
    file_path = temp_dir / uploaded_file.name
    
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
        
    # 2. Run Normalizer
    output_dir = Path("temp_outputs")
    
    with st.spinner("Normalizing and rasterizing document to 300 DPI..."):
        doc_ctx = normalize_document(file_path, output_dir)
        
    # 3. Display Results
    st.success(f"✅ Document processed successfully!")
    st.info(f"**Document ID:** `{doc_ctx.doc_id}`")
    st.info(f"**Total Pages Rasterized:** {len(doc_ctx.page_image_paths)}")
    
    st.divider()
    st.subheader("📄 Rasterized Pages (300 DPI)")
    
    # Display images in a 2-column grid
    cols = st.columns(2)
    for idx, img_path in enumerate(doc_ctx.page_image_paths):
        with cols[idx % 2]:
            st.image(str(img_path), caption=f"Page {idx + 1}", use_container_width=True)
'''
    print("\n📄 Creating app.py...")
    create_file(base_dir / "src/doc_checker/ui/app.py", app_content)
    
    # Final verification
    print("\n" + "=" * 70)
    print("🔍 VERIFICATION - Checking if files were actually created:")
    print("=" * 70)
    
    key_files = [
        "src/doc_checker/__init__.py",
        "src/doc_checker/schemas.py",
        "src/doc_checker/pipeline/__init__.py",
        "src/doc_checker/pipeline/normalizer.py",
        "src/doc_checker/ui/app.py",
    ]
    
    all_good = True
    for file_rel in key_files:
        full_path = base_dir / file_rel
        if full_path.exists():
            size = full_path.stat().st_size
            print(f"  ✅ {file_rel} ({size} bytes)")
        else:
            print(f"  ❌ MISSING: {file_rel}")
            all_good = False
    
    print("=" * 70)
    if all_good:
        print("🎉 SUCCESS! All files created. Now run:")
        print(f"   cd {base_dir}")
        print("   uv init")
        print("   uv add pydantic streamlit pypdfium2 pillow pikepdf")
        print("   uv run streamlit run src/doc_checker/ui/app.py")
    else:
        print("⚠️  Some files are missing. Check the errors above.")
    print("=" * 70)

if __name__ == "__main__":
    setup_project()