# src/doc_checker/ui/app.py
import sys
import os
from pathlib import Path

# --- ROBUST PATH FIX ---
# Current file: src/doc_checker/ui/app.py
# We need to add the 'src' directory to sys.path so 'import doc_checker' works.
src_dir = Path(__file__).resolve().parent.parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))
# -------------------------

import uuid
import streamlit as st
import sqlite3
import pandas as pd

# Now these imports will work perfectly
from doc_checker.config import config
from doc_checker.pipeline.security_gate import security_gate
from doc_checker.pipeline.normalizer import normalize_document
from doc_checker.pipeline.vlm_extractor import extract_with_vlm, verify_extracted_fields, EXTRACTION_MODEL
from doc_checker.pipeline.text_extractor import extract_document_content
from doc_checker.services.embedding_service import EmbeddingService
from doc_checker.db.database import (
    init_db, save_document_metadata, save_profile_to_db,
    save_document_text, save_embeddings, save_extracted_fields, 
    save_document_images, search_similar
)
from doc_checker.schemas import DocumentContext

# Initialize
init_db()
embedding_service = EmbeddingService()

# ... [rest of your app.py code remains exactly the same] ...

st.set_page_config(page_title="AI Loan Doc Checker", layout="wide")
st.title("🏦 Module 1 — AI Document Checker")

uploaded = st.file_uploader("Upload Loan Document (PDF)", type=["pdf"])

if uploaded:
    tmp = Path("temp_uploads"); tmp.mkdir(exist_ok=True)
    target = tmp / uploaded.name
    target.write_bytes(uploaded.getbuffer())
    
    doc_id = str(uuid.uuid4())
    ctx = DocumentContext(doc_id=doc_id, original_path=target)
    
    tab1, tab2, tab3, tab4 = st.tabs(["🔒 Security", "🖼️ Render", " Extract & Embed", "📊 Database"])
    
    with tab1:
        st.subheader("Stage 0: Security Gate")
        with st.spinner("Inspecting..."):
            report = security_gate(target)
            ctx.security_report = report
        if report.verdict != "allowed":
            st.error(f"🚫 BLOCKED: {report.finding_codes}")
            st.stop()
        st.success("✅ Safe to process")

    with tab2:
        st.subheader("Stage 1: Rasterization & Storage")
        with st.spinner("Rendering pages to 300 DPI..."):
            ctx = normalize_document(ctx) # Now saves to secure_uploads/{doc_id}/
        st.success(f"Rendered {len(ctx.page_image_paths)} pages to `secure_uploads/{doc_id}/`")
        if ctx.page_image_paths:
            st.image(str(ctx.page_image_paths[0]), caption="Page 1 (High Res)", use_container_width=True)

    with tab3:
        st.subheader("Stage 2: Smart Extraction & Embedding")
        if not ctx.page_image_paths:
            st.info("Complete previous stages first.")
        else:
            # Step A: VLM Structured Extraction
            with st.spinner(f"Extracting fields with {EXTRACTION_MODEL}..."):
                try:
                    raw_data = extract_with_vlm(ctx.page_image_paths[0])
                    verified_data = verify_extracted_fields(raw_data)
                    st.success("✅ Structured extraction complete")
                except Exception as e:
                    st.error(f"VLM extraction failed: {e}")
                    st.stop()
            
            # Step B: Smart Text Extraction (Native vs Scanned Routing)
            with st.spinner("Analyzing document type and extracting text..."):
                try:
                    full_md, page_texts, extraction_method = extract_document_content(ctx.original_path, ctx.page_image_paths)
                    
                    if extraction_method == "native_pdfplumber":
                        st.success("✅ Native PDF detected. Extracted text instantly via pdfplumber.")
                    else:
                        st.warning("️ Scanned document detected. Extracting text via VLM OCR (takes ~10s/page)...")
                except Exception as e:
                    st.error(f"Text extraction failed: {e}")
                    st.stop()
            
            # Step C: Embeddings
            with st.spinner("Generating embeddings..."):
                try:
                    chunks, embeddings = embedding_service.embed_document(full_md, doc_id)
                    st.success(f"✅ Generated {len(chunks)} embeddings")
                except Exception as e:
                    st.error(f"Embedding failed: {e}")
                    st.stop()
            
            # Step D: Save to DB
            with st.spinner("Saving to knowledge base..."):
                save_document_metadata(doc_id, uploaded.name, str(ctx.original_path), report.sha256, report.size_bytes, verified_data.get("document_type", "unknown"), report.verdict, report.page_count or 0)
                save_document_images(doc_id, ctx.page_image_paths) # NEW: Save image paths
                save_profile_to_db(doc_id, verified_data, str(raw_data))
                save_document_text(doc_id, full_md, page_texts)
                save_embeddings(doc_id, chunks, embeddings, config.ollama.embedding_model)
                save_extracted_fields(doc_id, verified_data)
                st.success("✅ All data saved!")
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("### 📄 Extracted Profile")
                st.json(verified_data)
            with col2:
                st.markdown("### 📊 Stats")
                st.metric("Extraction Method", "Native PDF" if extraction_method == "native_pdfplumber" else "Scanned VLM OCR")
                st.metric("Total Chunks", len(chunks))
                st.metric("Image Pages Saved", len(ctx.page_image_paths))

    with tab4:
        st.subheader("🗄️ Knowledge Base Preview")
        import sqlite3, pandas as pd
        with sqlite3.connect(str(config.database.db_path)) as conn:
            st.dataframe(pd.read_sql_query("SELECT doc_id, original_filename, document_type, image_paths_json FROM documents", conn), use_container_width=True)