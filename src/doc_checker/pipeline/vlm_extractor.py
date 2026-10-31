# src/doc_checker/pipeline/vlm_extractor.py
import base64
import json
import re
import requests
import instructor
from openai import OpenAI
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image
import io
from pydantic import BaseModel, Field

from ..config import config

VISION_MODEL = config.ollama.extraction_model  # qwen3-vl:2b
TEXT_MODEL = config.ollama.chat_model          # qwen3.5:0.8b

# Setup Instructor Client for Text Model
text_client = instructor.from_openai(
    OpenAI(base_url=f"{config.ollama.base_url}/v1", api_key="ollama", timeout=60.0)
)

# Pydantic Schema for Structured Data
class FinancialProfile(BaseModel):
    applicant_name: Optional[str] = Field(None, description="Full name")
    account_number: Optional[str] = Field(None, description="Account number")
    ifsc_code: Optional[str] = Field(None, description="IFSC code")
    bank_name: Optional[str] = Field(None, description="Bank name")
    pan_number: Optional[str] = Field(None, description="PAN number")
    document_type: str = Field("unknown", description="Type of document")

# --- VISION EXTRACTION (For Scanned PDFs) ---
EXTRACTION_PROMPT = """
Analyze this financial document image. Extract fields as JSON.
Fields: applicant_name, account_number, ifsc_code, bank_name, pan_number, document_type (bank_statement, salary_slip, pan_card, unknown)
If field not found, return null. Output ONLY JSON, no markdown.
"""

def prepare_image_for_vlm(image_path: Path, max_width: int = 1024) -> str:
    with Image.open(image_path) as img:
        if img.mode in ("RGBA", "P"): img = img.convert("RGB")
        if img.width > max_width:
            ratio = max_width / float(img.width)
            img = img.resize((max_width, int(float(img.height) * ratio)), Image.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')

def extract_with_vlm(image_path: Path) -> Optional[Dict[str, Any]]:
    try:
        image_b64 = prepare_image_for_vlm(image_path)
        payload = {
            "model": VISION_MODEL, "prompt": EXTRACTION_PROMPT, "images": [image_b64],
            "stream": False, "options": {"temperature": 0.0, "num_predict": 2048, "num_ctx": 8192}
        }
        response = requests.post(f"{config.ollama.base_url}/api/generate", json=payload, timeout=180)
        response.raise_for_status()
        raw_text = response.json().get("response", "").strip()
        if not raw_text: return None
        return json.loads(raw_text.replace("```json", "").replace("```", "").strip())
    except Exception as e:
        print(f"VLM extraction failed: {e}")
        return None

# --- TEXT EXTRACTION (For Native PDFs) ---
def extract_with_text_model(raw_text: str) -> Optional[Dict[str, Any]]:
    try:
        if len(raw_text.strip()) < 50: return None
        system_prompt = "Extract financial fields from text. Return JSON with: applicant_name, account_number, ifsc_code, bank_name, pan_number, document_type. Use null if not found."
        profile = text_client.chat.completions.create(
            model=TEXT_MODEL, response_model=FinancialProfile,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Document Text:\n{raw_text[:4000]}"}],
            max_retries=2
        )
        return profile.model_dump()
    except Exception as e:
        print(f"Text model extraction failed: {e}")
        return None

# --- THE SMART ROUTER ---
def extract_financial_profile(pdf_path: Path, page_image_paths: list, is_scanned: bool, raw_text: str = "") -> Optional[Dict[str, Any]]:
    """
    Routes extraction based on document type.
    Native PDF -> Text Model (Fast, accurate, skips VLM).
    Scanned PDF -> Vision Model (Required for images).
    """
    if not is_scanned:
        print("✅ Native PDF detected. Extracting profile via Text LLM (Skipping VLM)...")
        return extract_with_text_model(raw_text)
    else:
        print("⚠️ Scanned PDF detected. Extracting profile via Vision LLM...")
        if not page_image_paths: return None
        
        # Try VLM first
        vlm_result = extract_with_vlm(page_image_paths[0])
        if vlm_result: return vlm_result
        
        # Fallback to text model just in case (e.g., hybrid PDF)
        print("VLM failed. Trying text model fallback...")
        return extract_with_text_model(raw_text)

def verify_extracted_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    if not data: return {"verification_warnings": ["No data to verify"]}
    verified_data = data.copy()
    warnings = []
    ifsc = verified_data.get("ifsc_code")
    if ifsc and not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", str(ifsc).upper()):
        warnings.append(f"IFSC invalid: {ifsc}"); verified_data["ifsc_code"] = None
    pan = verified_data.get("pan_number")
    if pan and not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$", str(pan).upper()):
        warnings.append(f"PAN invalid: {pan}"); verified_data["pan_number"] = None
    verified_data["verification_warnings"] = warnings
    return verified_data