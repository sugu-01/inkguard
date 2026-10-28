import re
from collections import Counter
from datetime import date
from models import Finding

MULT = {"million": 1_000_000, "lakh": 100_000, "k": 1_000}

def sentence_of(text, pos):
    start = max(text.rfind(c, 0, pos) for c in ".!?") + 1
    ends = [i for i in (text.find(c, pos) for c in ".!?") if i != -1]
    return text[start:(min(ends) + 1 if ends else len(text))].lower()

def check_banned(text, rules):
    out = []
    for r in rules:
        if r["type"] != "ban" or not r["approved"]:
            continue
        for term, sub in r["terms"].items():
            for m in re.finditer(r"\b" + re.escape(term) + r"\b", text, re.I):
                out.append(Finding(kind="rule", ref=r["id"], start=m.start(), end=m.end(),
                    message=f"Banned term '{m.group(0)}'.", proof=f"{r['id']}, page {r['page']}: {r['quote']}", fix=sub))
    return out

def check_claims(text, facts):
    out = []
    for m in re.finditer(r"(\d[\d,]*\.?\d*)\s*(million|lakh|k)?\+?", text, re.I):
        value = float(m.group(1).replace(",", "")) * MULT.get((m.group(2) or "").lower(), 1)
        sent = sentence_of(text, m.start())
        fact = next((f for f in facts if any(k in sent for k in f["kw"])), None)
        s, e = m.start(), m.end()
        if fact is None:
            out.append(Finding(kind="unverified", ref="claim", start=s, end=e,
                message="No approved fact on file. Unverified, not false."))
            continue
        info = f"{fact['id']} · owner {fact['owner']} · expires {fact['expires']}"
        if date.fromisoformat(fact["expires"]) < date.today():
            out.append(Finding(kind="stale", ref=fact["id"], start=s, end=e,
                message=f"Fact {fact['id']} has expired. {fact['owner']} should refresh it.", proof=info))
        elif value != fact["val"]:
            out.append(Finding(kind="conflict", ref=fact["id"], start=s, end=e,
                message=f"Conflicts with {fact['id']} (value {fact['val']:,}).", proof=info, fix=f"{int(fact['val']):,}"))
        else:
            out.append(Finding(kind="verified", ref=fact["id"], start=s, end=e,
                message=f"Matches {fact['id']}.", proof=info))
    return out

def check(text, rules, facts):
    return sorted(check_banned(text, rules) + check_claims(text, facts), key=lambda f: f.start)

def _keys(findings):
    return Counter((f.kind, f.ref) for f in findings if f.kind not in ("verified", "tone"))

def verified_fix(text, finding, rules, facts):
    """Model proposes, code decides: return the fixed text only if it passes every check."""
    if finding.fix is None:
        return None
    candidate = text[:finding.start] + finding.fix + text[finding.end:]
    before, after = _keys(check(text, rules, facts)), _keys(check(candidate, rules, facts))
    if sum(after.values()) < sum(before.values()) and all(after[k] <= before[k] for k in after):
        return candidate
    return None
