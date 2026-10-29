"""
InkGuard RAG Service  (single file, drop-in)
=============================================
Explainable retrieval-augmented generation for brand governance.

WHAT IT DOES
  * Ingest brand guidelines / policy docs (.txt .md .pdf or raw text)
  * Hybrid-free, zero-key retrieval: BM25 over overlapping chunks
  * Answers questions WITH numbered citations  (POST /api/rag/query)
  * Checks marketing copy against the guidelines and EXPLAINS every
    violation with the rule + source it came from (POST /api/rag/check)
  * Works with NO API key (extractive answers + rule-based checker).
    Add a free-tier key and the same endpoints become LLM-powered.

RUN
  pip install fastapi uvicorn python-multipart pypdf httpx
  python rag_service.py                 # http://localhost:8001/docs

OPTIONAL ENV (or a .env file next to this script)
  GEMINI_API_KEY=...      # free tier  -> https://aistudio.google.com/apikey
  GROQ_API_KEY=...        # free tier  -> https://console.groq.com/keys
  GEMINI_MODEL=gemini-2.5-flash       # change if Google renames it
  GROQ_MODEL=llama-3.3-70b-versatile  # change if Groq renames it
  RAG_PORT=8001
  RAG_ORIGINS=*           # comma separated CORS origins

FRONTEND USAGE (fetch)
  const r = await fetch("http://localhost:8001/api/rag/query", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ question: "Can we say our product is cheap?" })
  });
  const { answer, citations, mode } = await r.json();

  // brand check
  await fetch("http://localhost:8001/api/rag/check", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ content: "Our guaranteed, cheap solution!" })
  });

  // upload guideline files (multipart, field name "files")
  const fd = new FormData(); fd.append("files", fileInput.files[0]);
  await fetch("http://localhost:8001/api/rag/ingest-file", { method: "POST", body: fd });

Drop files into  rag_data/knowledge/  and restart to auto-ingest them too.
"""

import hashlib
import io
import json
import logging
import math
import os
import re
import threading
import time
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

log = logging.getLogger("inkguard.rag")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

DATA_DIR = BASE_DIR / "rag_data"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
STORE_FILE = DATA_DIR / "store.json"
DATA_DIR.mkdir(exist_ok=True)
KNOWLEDGE_DIR.mkdir(exist_ok=True)

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GROQ_KEY = os.getenv("GROQ_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
PORT = int(os.getenv("RAG_PORT", "8001"))
ORIGINS = [o.strip() for o in os.getenv("RAG_ORIGINS", "*").split(",") if o.strip()]

CHUNK_SIZE = 900
CHUNK_OVERLAP = 150
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

# --------------------------------------------------------------------------- #
# Built-in sample knowledge (used only when nothing else has been ingested)
# --------------------------------------------------------------------------- #
SEED_DOCS = [
    (
        "Sample Brand Guidelines",
        """# Brand Voice and Tone

Our voice is confident, warm and plain-spoken. We write the way a knowledgeable friend talks: short sentences, active verbs, no jargon. We never shout; avoid ALL CAPS and more than one exclamation mark per piece of copy.

Tone shifts with context. In product UI we are concise and helpful. In marketing we are optimistic but honest. In support replies we are empathetic and solution-first.

# Words We Avoid

Do not use the words "cheap", "guaranteed", "revolutionary", "best-in-class" or "world-class" in any customer-facing copy. Say "affordable" instead of "cheap". Never promise outcomes; say "designed to" or "helps you" instead of "guaranteed".

Avoid the phrases "game-changer", "synergy" and "cutting-edge" because they are vague and overused.

# Claims and Legal

Every performance claim must be backed by a source that is linked or footnoted. Never make medical, financial or legal claims. Do not use competitor names in comparative copy without approval from the legal team.

Superlatives such as "the best" or "number one" require written proof and legal sign-off before publishing.

# Logo Usage

Keep clear space around the logo equal to the height of the letter I. Never stretch, rotate, recolor or add shadows to the logo. The minimum logo width is 24 px on screens and 20 mm in print. Use the white logo on dark backgrounds and the ink logo on light backgrounds.

# Color Palette

The primary color is Ink Navy (#0B1F3A). The accent color is Signal Amber (#F5A623). Body text must be Ink Navy on white or white on Ink Navy to meet WCAG AA contrast. Do not use Signal Amber for body text.

# Typography

Headlines use the Inter Bold typeface. Body copy uses Inter Regular at 16 px minimum on screens. Never mix more than two typefaces in a single layout.

# Inclusive Language

Use gender-neutral language by default. Do not use ableist idioms. Write alt text for every image and keep it under 125 characters.

# Social Media

Hashtags: use at most three per post and capitalise each word (#BrandVoice). Always disclose paid partnerships with #Ad at the start of the post. Respond to customer mentions within 24 hours.
""",
    )
]

# --------------------------------------------------------------------------- #
# Text utils
# --------------------------------------------------------------------------- #
STOP = set(
    "a an the and or of to in on for with is are was were be been it this that these those as at by "
    "from your our you we can do does how what when where which who why i me my us they them their "
    "if then than so but also any all use used using".split()
)


def _stem(w: str) -> str:
    for suf in ("ingly", "edly", "ing", "ed", "es", "ly", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokenize(text: str) -> List[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP and len(t) > 1]


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


def _split_long(block: str, size: int) -> List[str]:
    if len(block) <= size:
        return [block]
    out, cur = [], ""
    for s in split_sentences(block):
        if len(cur) + len(s) + 1 > size and cur:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[dict]:
    """Paragraph-aware chunker that remembers the nearest markdown heading."""
    text = re.sub(r"\r\n?", "\n", text).strip()
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    chunks: List[dict] = []
    heading, cur, cur_heading = "", "", ""

    def flush():
        nonlocal cur
        if cur.strip():
            chunks.append({"heading": cur_heading, "text": cur.strip()})
        cur = ""

    for block in blocks:
        if block.startswith("#"):
            flush()
            heading = block.lstrip("#").strip().split("\n")[0]
            rest = "\n".join(block.split("\n")[1:]).strip()
            if not rest:
                continue
            block = rest
        for piece in _split_long(block, size):
            if cur and len(cur) + len(piece) + 2 > size:
                tail = cur[-overlap:]
                tail = tail[tail.find(" ") + 1:] if " " in tail else tail
                flush()
                cur = tail + " "
            if not cur.strip():
                cur_heading = heading
            cur = f"{cur}\n\n{piece}" if cur.strip() else f"{cur}{piece}"
    flush()
    return chunks


def extract_text(filename: str, raw: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        return "\n\n".join((p.extract_text() or "") for p in reader.pages)
    if ext in (".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ""):
        text = raw.decode("utf-8", errors="ignore")
        if ext in (".html", ".htm"):
            text = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", text)
            text = re.sub(r"<[^>]+>", " ", text)
        return text
    raise HTTPException(415, f"Unsupported file type '{ext}'. Use .txt .md .pdf")


# --------------------------------------------------------------------------- #
# BM25 index
# --------------------------------------------------------------------------- #
class BM25:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf: List[Counter] = []
        self.dl: List[int] = []
        self.df: Counter = Counter()
        self.avgdl = 0.0

    def build(self, texts: List[str]) -> None:
        self.tf = [Counter(tokenize(t)) for t in texts]
        self.dl = [sum(c.values()) for c in self.tf]
        self.df = Counter()
        for c in self.tf:
            self.df.update(c.keys())
        self.avgdl = (sum(self.dl) / len(self.dl)) if self.dl else 0.0

    def score(self, query: str) -> List[float]:
        n = len(self.tf)
        q = tokenize(query)
        scores = [0.0] * n
        for term in set(q):
            df = self.df.get(term, 0)
            if not df:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for i, c in enumerate(self.tf):
                f = c.get(term, 0)
                if f:
                    denom = f + self.k1 * (1 - self.b + self.b * self.dl[i] / (self.avgdl or 1))
                    scores[i] += idf * f * (self.k1 + 1) / denom
        return scores


# --------------------------------------------------------------------------- #
# Store (documents + chunks + index), persisted as JSON
# --------------------------------------------------------------------------- #
class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.docs: dict = {}
        self.chunks: List[dict] = []
        self.index = BM25()
        self._load()

    def _load(self):
        if STORE_FILE.exists():
            try:
                data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
                self.docs, self.chunks = data.get("docs", {}), data.get("chunks", [])
            except Exception as e:  # corrupted file -> start clean
                log.warning("Could not read store (%s); starting empty", e)
        self._reindex()

    def _save(self):
        tmp = STORE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"docs": self.docs, "chunks": self.chunks}), encoding="utf-8")
        tmp.replace(STORE_FILE)

    def _reindex(self):
        self.index.build([f"{c['title']} {c['heading']} {c['text']}" for c in self.chunks])

    def add_document(self, title: str, text: str, source: str = "upload") -> dict:
        text = text.strip()
        if len(text) < 20:
            raise HTTPException(400, "Document is empty or too short to index.")
        digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()
        with self.lock:
            for d in self.docs.values():
                if d["hash"] == digest:
                    return {**d, "duplicate": True}
            doc_id = uuid.uuid4().hex[:10]
            pieces = chunk_text(text)
            for i, p in enumerate(pieces):
                self.chunks.append(
                    {
                        "id": f"{doc_id}-{i}",
                        "doc_id": doc_id,
                        "title": title,
                        "heading": p["heading"],
                        "text": p["text"],
                        "position": i,
                    }
                )
            doc = {
                "doc_id": doc_id,
                "title": title,
                "source": source,
                "chars": len(text),
                "chunks": len(pieces),
                "hash": digest,
                "added": int(time.time()),
            }
            self.docs[doc_id] = doc
            self._reindex()
            self._save()
            return {**doc, "duplicate": False}

    def delete_document(self, doc_id: str) -> bool:
        with self.lock:
            if doc_id not in self.docs:
                return False
            del self.docs[doc_id]
            self.chunks = [c for c in self.chunks if c["doc_id"] != doc_id]
            self._reindex()
            self._save()
            return True

    def reset(self):
        with self.lock:
            self.docs, self.chunks = {}, []
            self._reindex()
            self._save()

    def search(self, query: str, k: int = 4) -> List[dict]:
        with self.lock:
            if not self.chunks:
                return []
            scores = self.index.score(query)
            ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
            return [{**self.chunks[i], "score": round(scores[i], 4)} for i in ranked if scores[i] > 0]


store = Store()


def ingest_knowledge_folder() -> None:
    for f in sorted(KNOWLEDGE_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in (".txt", ".md", ".markdown", ".pdf"):
            try:
                store.add_document(f.stem, extract_text(f.name, f.read_bytes()), source=f"file:{f.name}")
            except Exception as e:
                log.warning("Skipping %s: %s", f.name, e)
    if not store.docs:
        for title, text in SEED_DOCS:
            store.add_document(title, text, source="sample")
        log.info("Loaded built-in sample brand guidelines")


# --------------------------------------------------------------------------- #
# LLM layer (optional) -- Gemini or Groq free tiers
# --------------------------------------------------------------------------- #
def llm_provider() -> Optional[str]:
    if GEMINI_KEY:
        return "gemini"
    if GROQ_KEY:
        return "groq"
    return None


def call_llm(system: str, prompt: str, json_mode: bool = False) -> str:
    provider = llm_provider()
    if provider == "gemini":
        gen_cfg = {"temperature": 0.2}
        if json_mode:
            gen_cfg["responseMimeType"] = "application/json"
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": GEMINI_KEY, "Content-Type": "application/json"},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": gen_cfg,
            },
            timeout=60,
        )
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    if provider == "groq":
        body = {
            "model": GROQ_MODEL,
            "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json=body,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    raise RuntimeError("No LLM configured")


def parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group(0))
        raise


def context_block(hits: List[dict]) -> str:
    return "\n\n".join(
        f"[{i}] ({h['title']} > {h['heading'] or 'General'})\n{h['text']}" for i, h in enumerate(hits, 1)
    )


def citations_of(hits: List[dict]) -> List[dict]:
    return [
        {
            "n": i,
            "doc_id": h["doc_id"],
            "title": h["title"],
            "heading": h["heading"],
            "score": h["score"],
            "snippet": h["text"][:320] + ("..." if len(h["text"]) > 320 else ""),
        }
        for i, h in enumerate(hits, 1)
    ]


# --------------------------------------------------------------------------- #
# RAG: answer
# --------------------------------------------------------------------------- #
ANSWER_SYSTEM = (
    "You are InkGuard, an explainable brand-governance assistant. Answer ONLY from the numbered "
    "context passages. Cite every claim with its passage number like [1] or [2][3]. If the context "
    "does not contain the answer, say you could not find it in the guidelines. Be concise and "
    "explain WHY the rule applies."
)


def extractive_answer(question: str, hits: List[dict]) -> str:
    q = set(tokenize(question))
    scored = []
    for n, h in enumerate(hits, 1):
        for s in split_sentences(h["text"]):
            overlap = len(q & set(tokenize(s)))
            if overlap:
                scored.append((overlap, -n, s, n))
    scored.sort(reverse=True)
    top = scored[:3] or [(0, 0, split_sentences(hits[0]["text"])[0], 1)]
    return "\n".join(f"- {s} [{n}]" for _, _, s, n in top)


def answer_question(question: str, top_k: int = 4) -> dict:
    t0 = time.time()
    hits = store.search(question, top_k)
    if not hits:
        return {
            "answer": "I could not find anything relevant in the ingested guidelines.",
            "grounded": False,
            "mode": "none",
            "citations": [],
            "latency_ms": int((time.time() - t0) * 1000),
        }
    mode, err = "extractive", None
    if llm_provider():
        try:
            answer = call_llm(ANSWER_SYSTEM, f"Context:\n{context_block(hits)}\n\nQuestion: {question}")
            mode = f"llm:{llm_provider()}"
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            log.warning("LLM failed, falling back to extractive: %s", err)
            answer = extractive_answer(question, hits)
    else:
        answer = extractive_answer(question, hits)
    out = {
        "answer": answer,
        "grounded": True,
        "mode": mode,
        "citations": citations_of(hits),
        "latency_ms": int((time.time() - t0) * 1000),
    }
    if err:
        out["llm_error"] = err
    return out


# --------------------------------------------------------------------------- #
# RAG: explainable brand check
# --------------------------------------------------------------------------- #
CHECK_SYSTEM = (
    "You are InkGuard, an explainable brand-compliance auditor. Judge the CONTENT strictly against "
    "the numbered brand-guideline passages. Return ONLY JSON: "
    '{"verdict":"pass|needs_review|fail","score":0-100,"summary":"...",'
    '"violations":[{"rule":"quoted/paraphrased rule","evidence":"exact text from content",'
    '"source":1,"why":"explanation","suggested_fix":"rewrite"}]}. '
    "Only flag violations supported by a passage; use the passage number for source. "
    "If compliant, return an empty violations list."
)

RULE_WORDS = re.compile(r"\b(avoid|never|do not|don't|must not|banned|prohibited|not use)\b", re.I)
QUOTED = re.compile(r"[\"\u201c]([^\"\u201d]{2,40})[\"\u201d]")


def rule_based_check(content: str) -> List[dict]:
    """Zero-key checker: finds quoted banned terms inside 'avoid/never/do not' rules."""
    found, seen = [], set()
    lower = content.lower()
    with store.lock:
        chunks = list(store.chunks)
    for ci, c in enumerate(chunks):
        for sent in split_sentences(c["text"]):
            if not RULE_WORDS.search(sent):
                continue
            for m in QUOTED.finditer(sent):
                term = m.group(1)
                # skip quoted terms that are *recommended* alternatives ("say "designed to"")
                if re.search(r"\b(say|use|try|write|prefer|with)\s*$", sent[: m.start()], re.I):
                    continue
                key = term.lower()
                if key in seen:
                    continue
                if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", lower):
                    seen.add(key)
                    found.append(
                        {
                            "rule": sent,
                            "evidence": term,
                            "source_title": c["title"],
                            "source_heading": c["heading"],
                            "why": f'The guidelines prohibit "{term}" in customer-facing copy.',
                            "suggested_fix": f'Remove or rephrase "{term}".',
                        }
                    )
    return found


def check_content(content: str, top_k: int = 5) -> dict:
    t0 = time.time()
    hits = store.search(content[:2000], top_k)
    mode, err, result = "rule-based", None, None
    if llm_provider() and hits:
        try:
            raw = call_llm(
                CHECK_SYSTEM,
                f"Guideline passages:\n{context_block(hits)}\n\nCONTENT TO AUDIT:\n{content}",
                json_mode=True,
            )
            result = parse_json(raw)
            mode = f"llm:{llm_provider()}"
            for v in result.get("violations", []):
                try:
                    h = hits[int(v.get("source", 0)) - 1]
                    v["source_title"], v["source_heading"] = h["title"], h["heading"]
                except Exception:
                    pass
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            log.warning("LLM check failed, using rule-based: %s", err)
    if result is None:
        violations = rule_based_check(content)
        n = len(violations)
        result = {
            "verdict": "pass" if n == 0 else ("needs_review" if n == 1 else "fail"),
            "score": max(0, 100 - 25 * n),
            "summary": "No banned terms or prohibited phrases detected."
            if n == 0
            else f"{n} guideline violation(s) detected.",
            "violations": violations,
        }
    result.update(
        {"mode": mode, "citations": citations_of(hits), "latency_ms": int((time.time() - t0) * 1000)}
    )
    if err:
        result["llm_error"] = err
    return result


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(_: FastAPI):
    ingest_knowledge_folder()
    log.info(
        "InkGuard RAG ready | docs=%d chunks=%d | llm=%s",
        len(store.docs), len(store.chunks), llm_provider() or "none (extractive mode)",
    )
    yield


app = FastAPI(title="InkGuard RAG Service", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=False if ORIGINS == ["*"] else True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryIn(BaseModel):
    question: str = Field(..., min_length=2, max_length=2000)
    top_k: int = Field(4, ge=1, le=10)


class CheckIn(BaseModel):
    content: str = Field(..., min_length=2, max_length=20000)
    top_k: int = Field(5, ge=1, le=10)


class TextIn(BaseModel):
    title: str = Field("Untitled", max_length=200)
    text: str = Field(..., min_length=20)


@app.get("/")
def root():
    return {"service": "InkGuard RAG", "docs": "/docs", "health": "/api/rag/health"}


@app.get("/api/rag/health")
def health():
    return {
        "status": "ok",
        "documents": len(store.docs),
        "chunks": len(store.chunks),
        "llm": llm_provider() or "none",
        "mode": f"llm:{llm_provider()}" if llm_provider() else "extractive",
    }


@app.post("/api/rag/query")
def query(body: QueryIn):
    return answer_question(body.question.strip(), body.top_k)


@app.post("/api/rag/check")
def check(body: CheckIn):
    return check_content(body.content.strip(), body.top_k)


@app.post("/api/rag/ingest-text")
def ingest_text(body: TextIn):
    return store.add_document(body.title.strip() or "Untitled", body.text, source="text")


@app.post("/api/rag/ingest-file")
async def ingest_file(files: List[UploadFile] = File(...)):
    results = []
    for f in files:
        raw = await f.read()
        if len(raw) > MAX_UPLOAD_BYTES:
            results.append({"file": f.filename, "error": "File larger than 15 MB"})
            continue
        try:
            text = extract_text(f.filename or "upload.txt", raw)
            doc = store.add_document(Path(f.filename or "upload").stem, text, source=f"file:{f.filename}")
            results.append({"file": f.filename, **doc})
        except HTTPException as e:
            results.append({"file": f.filename, "error": e.detail})
        except Exception as e:
            results.append({"file": f.filename, "error": f"{type(e).__name__}: {e}"})
    return {"results": results}


@app.get("/api/rag/documents")
def documents():
    return {"documents": sorted(store.docs.values(), key=lambda d: d["added"], reverse=True)}


@app.delete("/api/rag/documents/{doc_id}")
def delete_document(doc_id: str):
    if not store.delete_document(doc_id):
        raise HTTPException(404, "Document not found")
    return {"deleted": doc_id}


@app.post("/api/rag/reset")
def reset():
    store.reset()
    return {"status": "cleared"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)