# src/doc_checker/pipeline/detectors/transaction_parser.py
import instructor
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import List
import logging
from ...config import config

# Setup logging to track failures without crashing the UI
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 1. Setup Client with a STRICT TIMEOUT (Prevents network/model hangs)
client = instructor.from_openai(
    OpenAI(
        base_url=f"{config.ollama.base_url}/v1", 
        api_key="ollama",
        timeout=60.0  # CRITICAL: Hard kill switch if Ollama hangs for > 60 seconds
    )
)

class Transaction(BaseModel):
    date: str = Field(description="Transaction date strictly in YYYY-MM-DD format")
    narration: str = Field(description="Description or narration of the transaction")
    debit: float = Field(default=0.0, description="Amount withdrawn. 0.0 if empty")
    credit: float = Field(default=0.0, description="Amount deposited. 0.0 if empty")
    balance: float = Field(description="Running balance after this transaction")

def parse_transactions_to_json(table_text: str) -> List[Transaction]:
    """
    Extracts bank transactions. 
    Implements a Circuit Breaker: Fails gracefully instead of crashing the app.
    """
    if not table_text.strip():
        return []

    system_prompt = """
    You are a strict data extraction engine. Extract bank transaction rows from the provided text.
    Rules:
    1. If the text is NOT a bank transaction table, return an empty list.
    2. Format dates strictly as YYYY-MM-DD.
    3. Do not use commas in numbers.
    """

    try:
        # Circuit Breaker: max_retries=3 means it tries 3 times, then gives up.
        transactions = client.chat.completions.create(
            model=config.ollama.chat_model, 
            response_model=List[Transaction],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Raw Table Text:\n{table_text}"}
            ],
            max_retries=3 
        )
        return transactions
        
    except Exception as e:
        # GRACEFUL DEGRADATION: Log the error, but DO NOT crash the app.
        logger.error(f"LLM Transaction Parsing Failed: {e}")
        
        # Return an empty list so the pipeline can continue safely
        return []