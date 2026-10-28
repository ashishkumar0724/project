# src/doc_checker/pipeline/parser.py
import pdfplumber
from ..schemas import DocumentContext

def classify_and_extract(ctx: DocumentContext) -> DocumentContext:
    """
    Stage 2 & 3: Determine render class, doc type, and extract text/tables.
    """
    if ctx.security_report.verdict != "allowed":
        raise PermissionError("Cannot parse a document that failed the security gate.")

    full_text = ""
    all_tables = []
    text_lengths = []

    # Extract text and tables page by page
    with pdfplumber.open(ctx.original_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            full_text += text + "\n"
            text_lengths.append(len(text))
            
            tables = page.extract_tables() or []
            # Flatten tables into a simple list of rows for the schema
            all_tables.append(tables) 

    ctx.extracted_text = full_text.split("\n") # Store as list of lines
    ctx.extracted_tables = all_tables

    # --- STAGE 2: CLASSIFICATION ---
    
    # Axis A: Render Class (Native vs Scanned)
    # If the first page has > 50 chars of text, it's native.
    if text_lengths and text_lengths[0] > 50:
        ctx.render_class = "native_text"
    else:
        ctx.render_class = "scanned"

    # Axis B: Semantic Type (Keyword Anchors)
    lower_text = full_text.lower()
    
    if any(k in lower_text for k in ["permanent account number", "pan card", "income tax department"]):
        ctx.doc_type = "pan_card"
    elif any(k in lower_text for k in ["gross pay", "net pay", "salary slip", "earnings", "deductions"]):
        ctx.doc_type = "salary_slip"
    elif any(k in lower_text for k in ["balance", "debit", "credit", "transaction", "statement"]):
        ctx.doc_type = "bank_statement"
    else:
        ctx.doc_type = "unknown"

    return ctx