from typing import List, Literal, Optional
from pydantic import BaseModel

Kind = Literal["rule", "conflict", "stale", "unverified", "verified", "tone", "inject"]

class Finding(BaseModel):
    kind: Kind
    ref: str                    # rule or fact ID, e.g. "R-01" or "F-012"
    start: int                  # span in the draft text
    end: int
    message: str
    proof: Optional[str] = None # rule quote, or fact details
    fix: Optional[str] = None   # replacement text for text[start:end]
    source: Literal["code", "ai"] = "code"

class CheckRequest(BaseModel):
    text: str

class CheckResponse(BaseModel):
    findings: List[Finding]
    ai_available: bool

class Decision(BaseModel):
    decision: Literal["Approved", "Changes requested", "Escalated"]
    note: str = ""