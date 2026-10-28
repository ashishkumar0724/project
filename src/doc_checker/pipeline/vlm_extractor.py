# src/doc_checker/pipeline/vlm_extractor.py
import base64
import json
import re
import requests
from pathlib import Path
from typing import Dict, Any
from PIL import Image

OLLAMA_URL = "http://localhost:11434/api/generate"
EXTRACTION_MODEL = "qwen3-vl:2b"

EXTRACTION_PROMPT = """
You are an expert financial document parser. Analyze the provided image.
Extract these fields accurately. If missing, return null.
Return ONLY valid JSON. No markdown.

Fields:
- applicant_name
- account_number
- ifsc_code
- bank_name
- pan_number
- document_type (bank_statement, salary_slip, pan_card, unknown)
- statement_period
- opening_balance
- closing_balance
"""

def prepare_image_for_vlm(image_path: Path, max_width: int = 1024) -> str:
    """
    Resizes image to reduce token count for VLM while keeping text readable.
    Returns base64 string.
    """
    with Image.open(image_path) as img:
        # Convert to RGB if necessary (removes alpha channel issues)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
            
        # Resize if too wide
        if img.width > max_width:
            ratio = max_width / float(img.width)
            new_height = int(float(img.height) * ratio)
            img = img.resize((max_width, new_height), Image.LANCZOS)
            
        # Save to bytes
        import io
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85) # JPEG is smaller than PNG for VLM
        return base64.b64encode(buffer.getvalue()).decode('utf-8')

def extract_with_vlm(image_path: Path) -> Dict[str, Any]:
    """Calls the VLM to extract structured financial data."""
    
    # 1. Prepare smaller image for VLM
    image_b64 = prepare_image_for_vlm(image_path)
    
    payload = {
        "model": EXTRACTION_MODEL,
        "prompt": EXTRACTION_PROMPT,
        "images": [image_b64],
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 2048,
            "num_ctx": 8192  # CRITICAL FIX: Increase context window to fit the image
        }
    }
    
    try:
        # Check Ollama status
        requests.get("http://localhost:11434/api/tags", timeout=5).raise_for_status()
        
        # Make request
        response = requests.post(OLLAMA_URL, json=payload, timeout=180) # Increased timeout
        
        if response.status_code == 400:
            # Parse the specific error
            err_data = response.json()
            raise ValueError(f"Bad Request: {err_data.get('error', 'Unknown error')}")
            
        response.raise_for_status()
        result = response.json()
        
        raw_text = result.get("response", "{}")
        if not raw_text:
            raise ValueError("Ollama returned empty response")
            
        # Clean JSON
        raw_text = raw_text.replace("```json", "").replace("```", "").strip()
        return json.loads(raw_text)
        
    except requests.exceptions.ConnectionError:
        raise ConnectionError("Cannot connect to Ollama. Is 'ollama serve' running?")
    except requests.exceptions.Timeout:
        raise TimeoutError("Ollama timed out. The model might be loading.")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from VLM: {e}\nRaw: {raw_text[:200]}")

def verify_extracted_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    verified_data = data.copy()
    warnings = []

    ifsc = verified_data.get("ifsc_code")
    if ifsc and not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", str(ifsc).upper()):
        warnings.append(f"IFSC invalid: {ifsc}")
        verified_data["ifsc_code"] = None

    pan = verified_data.get("pan_number")
    if pan and not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$", str(pan).upper()):
        warnings.append(f"PAN invalid: {pan}")
        verified_data["pan_number"] = None

    verified_data["verification_warnings"] = warnings
    return verified_data