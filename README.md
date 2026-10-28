#  AI Loan Intelligence Platform (Module 1: Document Checker)

An AI-powered, local-first document ingestion and verification pipeline for banks and NBFCs. This module securely processes loan documents (Bank Statements, Salary Slips, PAN Cards), extracts structured financial data, and builds a vector-ready Knowledge Base for downstream AI agents.

## 🎯 Problem Statement
Loan operations staff face two major challenges:
1. **Document Fraud:** Tampered PDFs and scanned images are hard to verify manually.
2. **Fragmented Information:** Applicant data is scattered across documents, making it difficult for AI agents to retrieve accurate, grounded answers.

This project solves the ingestion and knowledge-building phase, ensuring 100% secure, highly accurate, and locally processed document parsing.

---

## 🏗️ Architecture & Pipeline

The system uses a strict, fail-closed, 4-stage pipeline. No untrusted bytes ever reach the AI models or main application memory.

```text
[Upload] 
   │
   ▼
[Stage 0: Security Gate] ─(Fail-Closed)──> [Quarantine]
   │ (Isolated subprocess, magic bytes, PDF object walk, zip-bomb check)
   ▼ (ALLOWED)
[Stage 1: Normalization]
   │ (300 DPI rasterization, strict pixel/memory budgets)
   ▼
[Stage 2: Smart Extraction & Knowledge Base]
   ├── Native PDF? ──> pdfplumber (100% deterministic text)
   ├── Scanned PDF? ─> VLM OCR Fallback (qwen3-vl:2b)
   └── Structured Data -> VLM Field Extraction (Name, IFSC, PAN, etc.)
   │
   ▼
[Stage 3: Embeddings & Storage]
   (Text chunking -> embeddinggemma-2:440m -> SQLite Knowledge Base)

git clone https://github.com/<your-username>/loan-doc-checker.git
cd loan-doc-checker

uv sync

ollama pull qwen3-vl:2b
ollama pull embeddinggemma-2:440m
ollama pull qwen3.5:0.8b

uv run streamlit run src/doc_checker/ui/app.py

loan-doc-checker/
├── src/
│   └── doc_checker/
│       ├── config.py              # Unified configuration (Models, DB, Limits)
│       ├── schemas.py             # Pydantic data contracts
│       ├── db/
│       │   └── database.py        # SQLite schema and query logic
│       ├── pipeline/
│       │   ├── security_gate.py   # Stage 0: Isolated file inspection
│       │   ├── normalizer.py      # Stage 1: 300 DPI rasterization
│       │   ├── vlm_extractor.py   # Stage 2: Structured VLM extraction
│       │   └── text_extractor.py  # Stage 2: Smart Native/OCR routing
│       ├── services/
│       │   └── embedding_service.py # Text chunking and Ollama embeddings
│       ── ui/
│           └── app.py             # Streamlit dashboard
├── pyproject.toml                 # uv project configuration
└── README.md