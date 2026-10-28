# src/doc_checker/pipeline/text_extractor.py
import pdfplumber
import base64
import requests
from pathlib import Path
from typing import List, Tuple
from PIL import Image
import io

from ..config import config

OLLAMA_URL = f"{config.ollama.base_url}/api/generate"
VISION_MODEL = config.ollama.extraction_model  # qwen3-vl:2b

# Prompt for full page OCR via VLM (used only for scanned docs)
FULL_TEXT_PROMPT = """
You are an expert document digitization AI. Your task is to transcribe the provided document image exactly as it appears.
Rules:
1. Preserve the exact structure. If there is a table, output it as a clean Markdown table.
2. Do not summarize, skip, or alter any text, numbers, or dates.
3. Output ONLY the transcribed text in Markdown format. No conversational filler.
"""

def encode_image_to_base64(image_path: Path) -> str:
    """Resize and encode image for VLM."""
    with Image.open(image_path) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        if img.width > 1200:
            ratio = 1200 / float(img.width)
            new_height = int(float(img.height) * ratio)
            img = img.resize((1200, new_height), Image.LANCZOS)
            
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')

def extract_full_text_with_vlm(image_path: Path) -> str:
    """Extract full page text using the Vision Model (OCR fallback)."""
    image_b64 = encode_image_to_base64(image_path)
    
    payload = {
        "model": VISION_MODEL,
        "prompt": FULL_TEXT_PROMPT,
        "images": [image_b64],
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 4096,
            "num_ctx": 8192
        }
    }
    
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=180)
        response.raise_for_status()
        result = response.json()
        return result.get("response", "").strip()
    except Exception as e:
        raise ConnectionError(f"VLM Text Extraction failed: {e}")

def extract_native_pdf_text(pdf_path: Path) -> Tuple[str, List[str]]:
    """Extract text using pdfplumber for native PDFs (100% accurate)."""
    pages_text = []
    full_md = ""
    
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            pages_text.append(text)
            
            page_md = f"## Page {page_num}\n\n"
            tables = page.extract_tables()
            if tables:
                page_md += "### Tables\n\n"
                for table_idx, table in enumerate(tables, 1):
                    if table:
                        page_md += f"**Table {table_idx}**\n"
                        headers = table[0] if table[0] else []
                        page_md += "| " + " | ".join(str(h) if h else "" for h in headers) + " |\n"
                        page_md += "|" + "|".join(["---"] * len(headers)) + "|\n"
                        for row in table[1:]:
                            page_md += "| " + " | ".join(str(cell) if cell else "" for cell in row) + " |\n"
                        page_md += "\n"
            
            if text.strip():
                page_md += "### Content\n\n" + text + "\n\n"
            full_md += page_md
            
    return full_md, pages_text

def extract_document_content(pdf_path: Path, page_image_paths: List[Path]) -> Tuple[str, List[str], str]:
    """
    Smart Routing:
    1. Try pdfplumber. If it gets >100 chars, it's Native (Fast & 100% Accurate).
    2. If <100 chars, it's Scanned. Fallback to VLM for full OCR.
    
    Returns: (full_markdown, page_texts, extraction_method)
    """
    full_md, pages_text = extract_native_pdf_text(pdf_path)
    total_chars = sum(len(t) for t in pages_text)
    
    if total_chars > 100:
        return full_md, pages_text, "native_pdfplumber"
    else:
        print("⚠️ Native text too low. Switching to VLM for full OCR...")
        vlm_pages_text = []
        vlm_full_md = ""
        
        for page_num, img_path in enumerate(page_image_paths, 1):
            page_text = extract_full_text_with_vlm(img_path)
            vlm_pages_text.append(page_text)
            vlm_full_md += f"## Page {page_num} (VLM OCR)\n\n{page_text}\n\n---\n\n"
            
        return vlm_full_md, vlm_pages_text, "scanned_vlm_ocr"