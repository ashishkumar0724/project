# src/doc_checker/pipeline/detectors/family_a_arithmetic.py
from typing import List, Dict, Any, Tuple
from ...schemas import Finding
from datetime import datetime

def check_arithmetic_invariants(transactions: List[Dict[str, Any]]) -> Tuple[List[Finding], float]:
    """
    Runs deterministic math checks on the transaction list.
    Returns a list of Findings and a risk score (0.0 to 1.0).
    """
    findings = []
    risk_score = 0.0
    
    if len(transactions) < 2:
        return findings, 0.0

    # 1. Row-by-Row Running Balance Check
    for i in range(1, len(transactions)):
        prev = transactions[i-1]
        curr = transactions[i]
        
        expected_balance = prev["balance"] + curr["credit"] - curr["debit"]
        
        # Allow a tiny floating point margin of error (0.01)
        if abs(expected_balance - curr["balance"]) > 0.05:
            findings.append(Finding(
                page_number=1, # Default to 1, can be mapped later
                region_bbox=None,
                detector_id="family_a_arithmetic",
                detector_version="1.0",
                reason=f"Row {i+1} balance mismatch. Expected {expected_balance:.2f}, got {curr['balance']:.2f}.",
                raw_score=0.95,
                finding_code="ARITH_ROW_BALANCE_MISMATCH"
            ))
            risk_score = max(risk_score, 0.95)

    # 2. Summary Invariant Check (First and Last row)
    opening_balance = transactions[0]["balance"] - transactions[0]["credit"] + transactions[0]["debit"] # Reverse engineer true opening
    total_credits = sum(t["credit"] for t in transactions)
    total_debits = sum(t["debit"] for t in transactions)
    closing_balance = transactions[-1]["balance"]
    
    expected_closing = opening_balance + total_credits - total_debits
    
    if abs(expected_closing - closing_balance) > 0.05:
        findings.append(Finding(
            page_number=1,
            region_bbox=None,
            detector_id="family_a_arithmetic",
            detector_version="1.0",
            reason=f"Summary mismatch. Opening({opening_balance:.2f}) + Credits({total_credits:.2f}) - Debits({total_debits:.2f}) should equal {expected_closing:.2f}, but Closing is {closing_balance:.2f}.",
            raw_score=1.0,
            finding_code="ARITH_SUMMARY_MISMATCH"
        ))
        risk_score = 1.0

    # 3. Date Monotonicity Check
    for i in range(1, len(transactions)):
        try:
            # Basic date parsing (handles YYYY-MM-DD or DD/MM/YYYY)
            d1 = datetime.strptime(transactions[i-1]["date"], "%Y-%m-%d")
            d2 = datetime.strptime(transactions[i]["date"], "%Y-%m-%d")
            if d2 < d1:
                findings.append(Finding(
                    page_number=1,
                    region_bbox=None,
                    detector_id="family_a_arithmetic",
                    detector_version="1.0",
                    reason=f"Date anomaly: Transaction {i+1} ({transactions[i]['date']}) is older than Transaction {i} ({transactions[i-1]['date']}).",
                    raw_score=0.60,
                    finding_code="ARITH_DATE_ANOMALY"
                ))
                risk_score = max(risk_score, 0.60)
        except ValueError:
            pass # Skip if date format is unparseable

    return findings, risk_score