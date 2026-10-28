import re
from pypdf import PdfReader


def _open_pdf(source):
    """Accept a file path or an uploaded file object."""
    if hasattr(source, "file"):
        source = source.file

    return PdfReader(source)


def compile_rules(source, use_ai=False):
    reader = _open_pdf(source)
    rules = []

    for page_number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""

        for line_number, line in enumerate(page_text.splitlines(), start=1):
            match = re.match(
                r"^\s*Never use:\s*(.+?)\s*$",
                line,
                re.IGNORECASE
            )

            if not match:
                continue

            terms = [
                term.strip()
                for term in match.group(1).split(",")
                if term.strip()
            ]

            if not terms:
                continue

            # Preserve the actual source line as the evidence quote.
            quote = line

            # Reject any quote that cannot be found on its source page.
            if quote not in page_text:
                continue

            rules.append({
                "id": f"R-PDF-{page_number}-{line_number}",
                "type": "ban",
                "approved": False,
                "page": page_number,
                "quote": quote,
                # No replacement is invented by the compiler.
                "terms": {term: None for term in terms}
            })

        if use_ai:
            rules.extend(_extract_ai_rules(page_text, page_number))

    # Remove duplicates while preserving order.
    unique_rules = []
    seen = set()

    for rule in rules:
        key = (
            rule["type"],
            rule["page"],
            rule["quote"],
            tuple(sorted(rule["terms"].items()))
        )

        if key not in seen:
            seen.add(key)
            unique_rules.append(rule)

    return unique_rules


def _extract_ai_rules(page_text, page_number):
    """Version 2: optional AI-assisted rule extraction."""
    import llm

    task = """
Extract brand guideline rules from the supplied page.
Return a JSON list. Each item must contain:
- type: "ban"
- quote: the exact source line copied from the page
- terms: an object mapping each prohibited term to a replacement,
  or null if no replacement is explicitly provided.
Do not invent rules or quotations. Return [] if none are found.
"""

    try:
        items = llm.ask_json(task, page_text)
    except Exception:
        # Preserve the deterministic PDF rules if AI is unavailable.
        return []

    if not isinstance(items, list):
        return []

    extracted = []

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue

        quote = item.get("quote")
        terms = item.get("terms")

        if not isinstance(quote, str) or not quote:
            continue

        # The evidence must exist exactly on this source page.
        if quote not in page_text:
            continue

        if not isinstance(terms, dict) or not terms:
            continue

        clean_terms = {}

        for term, replacement in terms.items():
            if not isinstance(term, str) or not term.strip():
                continue

            if replacement is not None and not isinstance(replacement, str):
                continue

            clean_terms[term.strip()] = replacement

        if not clean_terms:
            continue

        extracted.append({
            "id": f"R-AI-{page_number}-{index}",
            "type": "ban",
            "approved": False,
            "page": page_number,
            "quote": quote,
            "terms": clean_terms
        })

    return extracted
