<div align="center">

# 🖋️ InkGuard

**Nothing ships that you can't prove.**

Check ad copy against your approved brand rules and approved facts, with proof behind every flag.

[![Live Demo](https://img.shields.io/badge/demo-live-brightgreen?style=for-the-badge)](https://inkguard-hu8j.onrender.com)
![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Tests](https://img.shields.io/badge/tests-pytest-0A9EDC?style=for-the-badge&logo=pytest&logoColor=white)

[**Live demo**](https://inkguard-hu8j.onrender.com) · [Quick start](#-quick-start) · [API](#-api) · [Roadmap](#-roadmap)

</div>

> Built for a hackathon. Demo data is synthetic.

---

## 😖 The problem

Brand guidelines live in long PDFs nobody rereads, and the facts inside an ad (prices, refund windows, promo codes) go stale without anyone noticing. One banned word or one expired offer can mean a compliance headache, a refund storm, or a brand incident.

## ✨ What InkGuard does

1. **Compile** rules from a brand-guideline PDF, each linked to its source page and exact quote.
2. **Approve** rules with a human in the loop. Unapproved rules are never enforced.
3. **Check** any draft for banned terms, numbers that disagree with approved facts, expired facts, and (optionally) tone.
4. **Fix** with verified suggestions: a fix is offered only if re-running every check proves it reduces findings.

Every finding carries proof: the rule ID, page and quote, or the fact ID, owner and expiry date, plus `start` / `end` offsets so the UI can highlight the exact span.

### Design principles

| Principle | How it shows up |
|---|---|
| **Code decides, AI assists** | Deterministic checks always run. AI is optional and only adds tone findings. |
| **Every finding has proof** | Rule ID + page + quote, or fact ID + owner + expiry. |
| **"Unverified" is not "false"** | A claim with no matching fact is flagged unverified, never called wrong. |
| **Model proposes, code verifies** | `verified_fix()` accepts a fix only if the result has strictly fewer findings. |
| **No hallucinated rules** | Compiled rules are dropped unless their quote exists verbatim on the cited page. |
| **Untrusted input** | Drafts are wrapped in `<content>` tags and the LLM is told never to follow instructions inside. |
| **Graceful degradation** | If the AI provider or Supabase is down, all rule and fact findings still return. |

## 🔍 Finding types

| Kind | Meaning |
|---|---|
| `rule` | Banned term from an approved rule, with a replacement when one exists |
| `conflict` | A number disagrees with an approved fact |
| `stale` | The matching fact has expired; its owner should refresh it |
| `unverified` | A number with no approved fact on file |
| `verified` | A number that matches an approved fact |
| `tone` | AI-flagged phrase that may break a tone rule (with confidence) |
| `inject` | Prompt-injection style content (reserved in the model) |

---

## 🏗️ Architecture

```
┌──────────────┐    POST /check     ┌─────────────────────────────┐
│   Frontend   │ ─────────────────▶ │  FastAPI (api.py)           │
│ (index.html) │ ◀───────────────── │                             │
└──────────────┘     findings       │  engine.py   deterministic  │
                                    │  llm.py      Groq tone AI   │
                                    │  compiler.py PDF → rules    │
                                    │  db.py       data access    │
                                    └──────────────┬──────────────┘
                                                   │
                        ┌──────────────────────────┴───────────┐
                        ▼                                      ▼
                Supabase (primary)                    data/seed.json
                companies, rules,                     (automatic fallback)
                approved_facts
                        ▲
                        │
                MCP server (stdio) ──▶ AI agents
```

<details>
<summary><b>📁 Project structure</b></summary>

```
inkguard/
├── backend/
│   ├── api.py            # Main FastAPI app: /health and /check
│   ├── main.py           # Earlier minimal app backed by data/db.json
│   ├── engine.py         # Banned terms, claim matching, verified fixes
│   ├── db.py             # Supabase first, seed.json fallback, normalisation
│   ├── compiler.py       # PDF → candidate rules (regex + optional AI)
│   ├── llm.py            # Groq wrapper, tone findings, injection-safe prompts
│   ├── mcp_server.py     # MCP server for approved rules and facts
│   ├── models.py         # Pydantic models
│   ├── store.py          # Thread-safe JSON store (used by main.py)
│   ├── rag/rag_service.py  # Standalone RAG service
│   ├── data/             # seed.json, db.json
│   └── test_*.py         # pytest suites
├── frontend/index.html   # Landing page with live checker
├── docs/API.md           # Role-based route plan
└── requirements.txt
```

</details>

## 🧰 Tech stack

**Backend:** Python, FastAPI, Pydantic · **PDF:** pypdf · **AI (optional):** Groq (`openai/gpt-oss-20b` by default) · **Retrieval:** BM25 · **Agents:** Model Context Protocol · **Storage:** Supabase with JSON fallback · **Frontend:** HTML, CSS, vanilla JS · **Tests:** pytest, httpx

---

## 🚀 Quick start

**Prerequisites:** Python 3.10+. A Groq key and a Supabase project are both optional.

```bash
# 1. Clone
git clone https://github.com/sugu-01/inkguard.git
cd inkguard

# 2. Install
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Run the API
cd backend
uvicorn api:app --reload --port 8000
```

Open **http://localhost:8000/docs** for interactive docs, then open `frontend/index.html` in your browser (or run `python -m http.server 5173` inside `frontend/`).

With no configuration, InkGuard runs on `seed.json` with deterministic checks only.

### ⚙️ Configuration (optional)

Create `backend/.env`:

```env
# AI tone checks
GROQ_API_KEY=your_groq_key
LLM_MODEL=openai/gpt-oss-20b

# Live data and MCP server
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
INKGUARD_COMPANY_NAME=InkGuard Demo Company
```

> ⚠️ `.env` is git-ignored. Never commit keys. The Supabase service-role key bypasses row-level security, so keep it server-side and rotate it if it is ever exposed.

The frontend calls the API at the `API` constant near the bottom of `frontend/index.html` (default `http://localhost:8000`). If the API is unreachable, it falls back to built-in sample rules and says so.

### 🧪 Tests

```bash
cd backend
pytest
```

---

## 📡 API

Base URL (local): `http://localhost:8000`

### `GET /health`

```json
{ "status": "ok", "rules_loaded": 4, "facts_loaded": 4, "supabase": false }
```

### `POST /check`

```json
{ "text": "Get guaranteed results for just 499 per month!" }
```

```json
{
  "findings": [
    {
      "kind": "rule",
      "ref": "R1",
      "start": 4,
      "end": 14,
      "message": "Banned term 'guaranteed'.",
      "proof": "R1, page 3: Never use the words 'guaranteed', 'risk-free' or 'cure' in customer-facing copy.",
      "fix": null,
      "source": "code"
    }
  ],
  "ai_available": false
}
```

- Empty `text` returns `422`.
- Tone checks run only when approved `tone` rules exist and a Groq key is set. If the AI call fails, `ai_available` is `false` and no deterministic finding is lost.
- Findings are sorted by position in the text.

<details>
<summary><b>Planned routes</b> (see <a href="docs/API.md"><code>docs/API.md</code></a>)</summary>

| Route | Role | Purpose |
|---|---|---|
| `GET /rules` | Brand manager | View rules |
| `POST /rules/compile` | Brand manager | Compile rules from a PDF |
| `POST /rules/{id}/approve` | Brand manager | Approve a rule |
| `GET` / `POST /facts` | Brand manager | View and add facts |
| `POST /submissions` | Creator | Submit content for review |
| `POST /submissions/{id}/decision` | Reviewer | Approve, request changes, or escalate |
| `GET /audit` | Anyone | Audit trail |
| `GET /insights` | Anyone | Chart and insight data |

The demo identifies roles with an `X-Role` header. This is a shortcut, **not** authentication; a production build must enforce permissions on the server.

</details>

<details>
<summary><b>📦 Data formats</b></summary>

`db.py` normalises Supabase or `seed.json` data into the shape `engine.py` expects.

**Rule**

```json
{
  "id": "R1",
  "type": "banned_terms",
  "approved": true,
  "page": 3,
  "quote": "Never use the words 'guaranteed', 'risk-free' or 'cure' in customer-facing copy.",
  "terms": ["guaranteed", "risk-free", "cure"]
}
```

`terms` can be a list or a `{term: replacement}` object; a replacement becomes the suggested fix.

**Fact**

```json
{
  "id": "F-REFUND",
  "kw": ["refund", "days"],
  "val": 14,
  "owner": "Operations",
  "expires": "2027-01-15"
}
```

`kw` words are matched against the sentence containing a number, and `val` is compared numerically. Past `expires` dates produce `stale` findings.

</details>

---

## 🤖 MCP server

`backend/mcp_server.py` exposes InkGuard data to MCP-compatible agents over stdio (requires the Supabase variables).

| Tool | Description |
|---|---|
| `get_company_rules` | Approved brand guidelines for a company |
| `get_approved_facts` | Approved facts with owners and expiry dates |

```bash
cd backend && python mcp_server.py
```

Only **approved** rules are returned, so agents cannot enforce unreviewed guidance.

<details>
<summary><b>📚 RAG service</b></summary>

`backend/rag/rag_service.py` answers questions about your guidelines with numbered citations and explains violations with their source. It needs no API key (BM25 retrieval, extractive answers) and becomes LLM-powered when `GEMINI_API_KEY` or `GROQ_API_KEY` is set.

```bash
pip install fastapi uvicorn python-multipart pypdf httpx
python backend/rag/rag_service.py     # http://localhost:8001/docs
```

| Route | Purpose |
|---|---|
| `POST /api/rag/query` | Ask a question, get an answer with citations |
| `POST /api/rag/check` | Check copy and explain each violation |
| `POST /api/rag/ingest-text` | Add raw text |
| `POST /api/rag/ingest-file` | Upload `.txt`, `.md` or `.pdf` (15 MB max) |
| `GET /api/rag/documents` | List documents |
| `DELETE /api/rag/documents/{doc_id}` | Remove a document |
| `POST /api/rag/reset` | Clear the knowledge base |
| `GET /api/rag/health` | Service status |

</details>

## ☁️ Deployment

The live demo runs on [Render](https://render.com). Typical setup:

- **Backend (Web Service):** root `backend`, build `pip install -r ../requirements.txt`, start `uvicorn api:app --host 0.0.0.0 --port $PORT`
- **Frontend (Static Site):** publish `frontend/`
- Add environment variables in the Render dashboard, never in the repo.
- Set the frontend `API` constant to your backend URL and restrict CORS origins in `api.py`.

Free instances sleep when idle, so the first request can be slow.

## 🔒 Safety and trust

- Rules start as `approved: false` and are enforced only after a human approves them.
- The compiler never invents replacements; terms without one get no auto-fix.
- AI output is validated: quotes must exist in the source text, confidence is clamped to 0–1, malformed output is discarded.
- Provider errors and API keys are never returned to clients.

## ⚠️ Known limitations

- The frontend `API` URL is hardcoded; if it points at `localhost`, the hosted page uses sample rules.
- CORS allows all origins, and `X-Role` is not real authentication.
- Only `/health` and `/check` are implemented so far.
- `compiler.py` extracts `Never use:` lines by pattern; other phrasing needs the optional AI extraction.

## 🗺️ Roadmap

- [ ] Full role-based API from `docs/API.md`
- [ ] Highlighted spans and one-click verified fixes in the UI
- [ ] PDF upload and rule approval flow
- [ ] Submission and review workflow with audit trail
- [ ] Insights dashboard (common violations, stale-fact alerts)
- [ ] Real authentication in place of `X-Role`
- [ ] Tighter CORS and database-only storage

## 🤝 Contributing

Issues and PRs are welcome. Please run `pytest` before opening a PR.

## 📄 License

No license has been chosen yet. Add one (for example MIT) before sharing publicly.

---

<p align="center">Made with ☕ for the hackathon · <b>InkGuard</b>: check your copy before it ships.</p>
