# src/doc_checker/pipeline/normalizer.py
import pypdfium2 as pdfium
from pathlib import Path
from ..schemas import DocumentContext
from .limits import SafetyLimits

def normalize_document(ctx: DocumentContext, limits: SafetyLimits = SafetyLimits()) -> DocumentContext:
    """
    Stage 1: Rasterize pages to 300 DPI and save to structured folder.
    """
    # Create a dedicated folder for this document's images
    doc_image_dir = Path("secure_uploads") / ctx.doc_id
    doc_image_dir.mkdir(parents=True, exist_ok=True)
    
    pdf = pdfium.PdfDocument(str(ctx.original_path))
    n_pages = len(pdf)
    scale_factor = 300 / 72  # 300 DPI
    
    total_pixels = 0
    
    for i in range(n_pages):
        page = pdf[i]
        bitmap = page.render(scale=scale_factor)
        pil_image = bitmap.to_pil()
        
        w, h = pil_image.size
        page_pixels = w * h
        
        if page_pixels > limits.max_pixels_per_page:
            pdf.close()
            raise ValueError(f"Page {i+1} exceeds pixel budget")
            
        total_pixels += page_pixels
        if total_pixels > limits.max_total_pixels:
            pdf.close()
            raise ValueError(f"Document exceeds total pixel budget")
        
        # Save to the structured folder
        img_path = doc_image_dir / f"page_{i+1}.png"
        pil_image.save(img_path)
        ctx.page_image_paths.append(img_path)
        
    pdf.close()
    return ctx