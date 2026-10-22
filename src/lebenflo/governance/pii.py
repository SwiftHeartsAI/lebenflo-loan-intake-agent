"""PII masking. Runs on every piece of text before it is sent to the LLM.

Document Intelligence is allowed to see raw documents (it has to read them); the LLM is not
allowed to see SSNs, account numbers or dates of birth. Simple regexes are enough for our
known document formats and are easy to explain and test. In production I'd add Presidio or
Azure AI Language PII detection for free-text documents.
"""

import re

SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b")
ACCOUNT = re.compile(r"\b\d{8,17}\b")
DOB = re.compile(
    r"\b(DOB|Date of Birth|Birth Date)(\s*[:\-]?\s*)\d{1,4}[/\-]\d{1,2}[/\-]\d{2,4}", re.I
)


def mask_account(number: str) -> str:
    """Keep the last 4 digits so a reviewer can still tell accounts apart."""
    return f"[ACCOUNT ****{number[-4:]}]"


def mask_pii(text: str) -> str:
    text = SSN.sub("[SSN]", text)
    text = ACCOUNT.sub(lambda m: mask_account(m.group()), text)
    text = DOB.sub(lambda m: f"{m.group(1)}{m.group(2)}[DOB]", text)
    return text
