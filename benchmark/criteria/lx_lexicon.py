import re
from typing import Dict, List, Any

# [LEXICON STANDARDS]
# 1. NO APOLOGIES
# 2. NO PERSONA-DRIFT ("As an AI...")
# 3. NO CONVERSATIONAL PADDING
# 4. DRY TECHNICAL TONE ONLY

FAIL_PATTERNS = [
    r"As an AI",
    r"I apologize",
    r"I'm sorry",
    r"As a large language model",
    r"How can I help you today",
    r"Is there anything else",
    r"As your assistant",
    r"Happy to help",
    r"Sure thing",
]

def audit_text(text: str) -> Dict[str, Any]:
    """
    Verifies that the provided text adheres to the Servo Lexicon standards.
    Returns a diagnostic dictionary.
    """
    if not text:
        return {"pass": True, "score": 1.0, "reason": "Empty text"}

    failures = []
    for pattern in FAIL_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            failures.append(f"Detected prose noise: '{match.group(0)}'")

    # Simple noise ratio calculation (failed pattern counts)
    is_pass = len(failures) == 0
    score = 1.0 if is_pass else max(0.0, 1.0 - (len(failures) * 0.1))

    return {
        "metric": "lx_lexicon",
        "pass": is_pass,
        "score": round(score, 2),
        "failures": failures,
        "raw_text_preview": text[:100] + ("..." if len(text) > 100 else "")
    }

if __name__ == "__main__":
    # Self-test
    test_cases = [
        "The project mapping is complete. 10 files indexed.",
        "I'm sorry, I cannot perform that action as an AI assistant.",
        "The state delta lx_StateDelta has been committed to the ledger."
    ]
    
    for tc in test_cases:
        result = audit_text(tc)
        print(f"Text: {tc[:30]}... | Pass: {result['pass']} | Score: {result['score']}")
