# src/doc_checker/ui/app.py
import sys
import os
from pathlib import Path

# --- ROBUST PATH FIX ---
src_dir = Path(__file__).resolve().parent.parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import uuid
import streamlit as st
import sqlite3
import pandas as pd
import pdfplumber

# --- IMPORTS ---
from doc_checker.config import config
from doc_checker.pipeline.security_gate import security_gate
from doc_checker.pipeline.normalizer import normalize_document
from doc_checker.pipeline.vlm_extractor import extract_financial_profile, verify_extracted_fields
from doc_checker.pipeline.text_extractor import extract_document_content
from doc_checker.pipeline.detectors.transaction_parser import parse_transactions_to_json
from doc_checker.pipeline.detectors.family_a_arithmetic import check_arithmetic_invariants
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

st.set_page_config(page_title="AI Loan Doc Checker", layout="wide")
st.title("🏦 Module 1 — AI Document Checker")

uploaded = st.file_uploader("Upload Loan Document (PDF)", type=["pdf"])

if uploaded:
    tmp = Path("temp_uploads"); tmp.mkdir(exist_ok=True)
    target = tmp / uploaded.name
    target.write_bytes(uploaded.getbuffer())
    
    doc_id = str(uuid.uuid4())
    ctx = DocumentContext(doc_id=doc_id, original_path=target)
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🔒 Security", "🖼️ Render", "📝 Extract & Embed", "🔍 Fraud Detection", "📊 Database"
    ])
    
    # ==========================================
    # TAB 1: SECURITY GATE
    # ==========================================
    with tab1:
        st.subheader("Stage 0: Security Gate")
        with st.spinner("Inspecting untrusted bytes..."):
            report = security_gate(target)
            ctx.security_report = report
        
        if report.verdict != "allowed":
            st.error(f"🚫 BLOCKED: {report.finding_codes}")
            st.stop()
        
        st.success("✅ Document passed security checks")
        st.json({
            "SHA-256": report.sha256,
            "Size (KB)": round(report.size_bytes / 1024, 1),
            "Pages": report.page_count
        })

    # ==========================================
    # TAB 2: RASTERIZATION
    # ==========================================
    with tab2:
        st.subheader("Stage 1: Rasterization & Storage")
        with st.spinner("Rendering pages to 300 DPI..."):
            ctx = normalize_document(ctx)
        st.success(f"Rendered {len(ctx.page_image_paths)} pages to `secure_uploads/{doc_id}/`")
        if ctx.page_image_paths:
            st.image(str(ctx.page_image_paths[0]), caption="Page 1 (High Res)", use_container_width=True)

    # ==========================================
    # ==========================================
    # TAB 3: SMART EXTRACTION & EMBEDDING
    # ==========================================
    with tab3:
        st.subheader("Stage 2: Smart Extraction & Embedding")
        if not ctx.page_image_paths:
            st.info("Complete previous stages first.")
        else:
            # Step A: Smart Routing & Profile Extraction
            extraction_result = None
            extraction_error = None
            is_scanned = False
            raw_pdf_text = ""
            
            with st.spinner("Analyzing document type and extracting profile..."):
                try:
                    with pdfplumber.open(ctx.original_path) as pdf:
                        total_chars = 0
                        pages_to_check = min(3, len(pdf.pages))
                        for i in range(pages_to_check):
                            text = pdf.pages[i].extract_text() or ""
                            total_chars += len(text)
                        
                        if total_chars < 100:
                            is_scanned = True
                        else:
                            raw_pdf_text = pdf.pages[0].extract_text() or ""
                    
                    raw_data = extract_financial_profile(
                        pdf_path=ctx.original_path, 
                        page_image_paths=ctx.page_image_paths, 
                        is_scanned=is_scanned,
                        raw_text=raw_pdf_text
                    )
                    
                    if raw_data:
                        extraction_result = raw_data
                    else:
                        extraction_error = "Both models failed to extract structured data"
                except Exception as e:
                    extraction_error = str(e)
            
            verified_data = {}
            if extraction_error:
                st.warning(f"⚠️ {extraction_error}")
            else:
                st.success("✅ Structured extraction complete")
                verified_data = verify_extracted_fields(extraction_result)
                save_profile_to_db(doc_id, verified_data, str(extraction_result))
            
            ctx.vlm_extracted_data = verified_data
            
            # Step B: Extract full text AND tables (ONCE)
            with st.spinner("Extracting full document text and tables..."):
                try:
                    # 1. Extract Text & Markdown
                    full_md, page_texts, is_scanned_text = extract_document_content(ctx.original_path, ctx.page_image_paths)
                    
                    # 2. Extract Raw Tables for Tab 4 (The Fix!)
                    raw_tables_for_math = []
                    with pdfplumber.open(ctx.original_path) as pdf:
                        for page in pdf.pages:
                            tables = page.extract_tables()
                            if tables:
                                # Keep the largest table from each page
                                largest = max(tables, key=lambda t: len(t) if t else 0)
                                if largest and len(largest) > 2:
                                    raw_tables_for_math.append(largest)
                    
                    # Save tables to Context so Tab 4 can use them without re-reading the PDF
                    ctx.extracted_tables = raw_tables_for_math
                    
                    if is_scanned_text:
                        st.warning("⚠️ Scanned document detected. Used VLM for full OCR.")
                    else:
                        st.success(f"✅ Native text extraction complete. Found {len(raw_tables_for_math)} table(s).")
                except Exception as e:
                    st.error(f"Text extraction failed: {e}")
                    st.stop()
            
            # Step C: Generate embeddings
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
                save_document_images(doc_id, ctx.page_image_paths)
                save_document_text(doc_id, full_md, page_texts, ctx.extracted_tables)
                save_embeddings(doc_id, chunks, embeddings, config.ollama.embedding_model)
                if verified_data:
                    save_extracted_fields(doc_id, verified_data)
                st.success("✅ All available data saved to database!")
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("### 📄 Extracted Profile")
                if verified_data: st.json(verified_data)
                else: st.info("No structured profile extracted")
            with col2:
                st.markdown("### 📊 Stats")
                st.metric("Extraction Method", "VLM" if is_scanned else "Text LLM")
                st.metric("Total Chunks", len(chunks))
                st.metric("Tables Found", len(ctx.extracted_tables))

    # ==========================================
    # ==========================================
    # TAB 4: FRAUD DETECTION (FAMILY A - MULTI-PAGE)
    # ==========================================
    with tab4:
        st.subheader("Stage 3: Detector Family A (Arithmetic & Logic)")
        
        if not ctx.page_image_paths:
            st.info("Complete previous stages first.")
        else:
            profile_data = getattr(ctx, 'vlm_extracted_data', {})
            doc_type = profile_data.get("document_type", "unknown")
            
            if doc_type == "pan_card":
                st.info("ℹ️ Arithmetic checks not applicable for PAN Cards.")
            elif doc_type == "salary_slip":
                st.info("ℹ️ Salary slips require different logic.")
            elif doc_type != "bank_statement":
                st.warning(f"⚠️ Document type is '{doc_type}'. Arithmetic checks are optimized for Bank Statements.")

            # --- USE TABLES ALREADY EXTRACTED IN TAB 3 ---
            if not ctx.extracted_tables:
                st.warning("⚠️ No valid transaction tables were found during Stage 2. Arithmetic checks are N/A.")
            else:
                st.success(f"✅ Using {len(ctx.extracted_tables)} table(s) extracted in Stage 2.")
                
                # Convert the raw tables (list of lists) into the text format the LLM expects
                all_raw_tables_text = []
                for table in ctx.extracted_tables:
                    table_text = "\n".join([" | ".join([str(cell) for cell in row]) for row in table])
                    all_raw_tables_text.append(table_text)
                
                combined_table_text = "\n\n--- NEXT PAGE ---\n\n".join(all_raw_tables_text)
                
                transactions = []
                parse_failed = False
                
                with st.spinner(f"Parsing {len(ctx.extracted_tables)} table(s) into structured JSON..."):
                    try:
                        transactions = parse_transactions_to_json(combined_table_text)
                    except Exception as e:
                        parse_failed = True
                
                if parse_failed or not transactions:
                    st.warning("⚠️ AI model could not parse the table structure. Skipping arithmetic checks.")
                else:
                    st.success(f"✅ Successfully parsed {len(transactions)} total transactions.")

                    with st.spinner("Running deterministic arithmetic checks..."):
                        findings, risk_score = check_arithmetic_invariants(transactions)
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Calculated Risk Score", f"{risk_score * 100:.0f}%")
                        if risk_score == 0.0: st.success("✅ No arithmetic anomalies detected.")
                        elif risk_score < 0.8: st.warning("⚠️ Minor anomalies detected. Needs Review.")
                        else: st.error("🚨 High risk! Major arithmetic mismatches found.")

                    with col2:
                        st.markdown("### 📄 Parsed Transactions (First 5)")
                        st.dataframe([t.model_dump() for t in transactions[:5]], use_container_width=True)

                    if findings:
                        st.divider()
                        st.markdown("### 🚩 Findings")
                        for f in findings:
                            st.error(f"**[{f.finding_code}]** {f.reason}")
                    else:
                        st.info("No findings generated. Document math is consistent.")
    # ==========================================
    # TAB 5: DATABASE PREVIEW (SIMPLIFIED)
    # ==========================================
    with tab5:
        st.subheader("🗄️ Knowledge Base Preview")
        
        db_path = Path(config.database.db_path)
        
        if not db_path.exists():
            st.error("❌ Database file not found. Please upload a document in Tab 3 first.")
        else:
            st.success(f"✅ Database found: `{db_path.name}`")
            
            try:
                with sqlite3.connect(str(db_path)) as conn:
                    st.markdown("### 📄 Saved Documents")
                    try:
                        df_docs = pd.read_sql_query("SELECT doc_id, original_filename, document_type FROM documents", conn)
                        if df_docs.empty:
                            st.info("No documents saved yet.")
                        else:
                            st.dataframe(df_docs, use_container_width=True)
                    except Exception as e:
                        st.error(f"Error reading documents: {e}")
                    
                    st.divider()
                    
                    st.markdown("### 👤 Applicant Profiles")
                    try:
                        df_profiles = pd.read_sql_query("SELECT doc_id, applicant_name, account_number, ifsc_code FROM applicant_profiles", conn)
                        if df_profiles.empty:
                            st.info("No profiles saved yet.")
                        else:
                            st.dataframe(df_profiles, use_container_width=True)
                    except Exception as e:
                        st.error(f"Error reading profiles: {e}")

            except Exception as e:
                st.error(f"Database connection failed: {e}")