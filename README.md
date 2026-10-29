# 🖋️ InkGuard

**Write boldly. Ship safely.**

InkGuard checks ad copy against your brand rules and approved facts *before* it goes live. Brand guidelines are compiled from your PDF, every claim is checked against a fact on file, and every finding comes with proof: the exact rule quote, page number, fact owner and expiry date.

> Built for a hackathon. Synthetic demo data only.

---

## ✨ The Problem

Marketing copy ships fast. Brand guidelines live in 40-page PDFs nobody rereads, and the "facts" in an ad (prices, refund windows, promo codes) go stale without anyone noticing. One banned word or one expired offer can mean a compliance headache, a refund storm, or a brand incident.

## 💡 The Solution

InkGuard turns the brand book into an enforceable checker:

1. **Compile** rules from a brand-guideline PDF, with each rule linked to its source page and exact quote.
2. **Approve** rules (human in the loop) so nothing unreviewed is ever enforced.
3. **Check** any draft: banned terms, number claims vs. approved facts, expired facts, and (optionally) tone.
4. **Fix** with verified suggestions: a fix is offered only if re-running the checks proves it reduces findings.

### Design principles

| Principle | How it shows up |
|---|---|
| **Code decides, AI assists** | Deterministic checks always run. AI is optional and only adds tone findings. |
| **Every finding has proof** | Rule ID + page + quote, or fact ID + owner + expiry. |
| **"Unverified" is not "false"** | A claim with no matching fact is flagged as unverified, never called wrong. |
| **Model proposes, code verifies** | `verified_fix()` accepts a fix only if the fixed text passes every check with strictly fewer findings. |
| **No hallucinated rules** | Compiled rules are dropped unless their quote exists verbatim on the cited page. |
| **Untrusted input** | Draft text is wrapped in `<content>` tags and the LLM is told never to follow instructions inside it (prompt-injection defense). |
| **Graceful degradation** | If the AI provider is down or no key is set, the API still returns all rule and fact findings. |

---

## 🔍 Finding Types

| Kind | Meaning |
|---|---|
| `rule` | A banned term from an approved rule, with a suggested replacement when one exists |
| `conflict` | A number in the draft disagrees with an approved fact |
| `stale` | The matching fact has expired and its owner should refresh it |
| `unverified` | A number with no approved fact on file |
| `verified` | A number that matches an approved fact |
| `tone` | AI-flagged phrase that may break an approved tone rule (with confidence score) |
| `inject` | Prompt-injection style content (reserved in the model) |

Each finding includes `start`/`end` character offsets so the UI can highlight the exact span.

---

## 🏗️ Architecture

```
┌──────────────┐     POST /check      ┌──────────────────────────┐
│   Frontend   │ ───────────────────▶ │  FastAPI backend         │
│ (index.html) │ ◀─────────────────── │                          │
└──────────────┘      findings        │  engine.py  deterministic│
                                      │  llm.py     Groq tone AI │
                                      │  compiler.py PDF → rules │
                                      │  store.py   JSON storage │
                                      └────────────┬─────────────┘
                                                   │
                         ┌─────────────────────────┴───────────┐
                         ▼                                     ▼
                  data/db.json                       MCP server (stdio)
                  (rules, facts, audit)           exposes rules & facts to
                                                  AI agents via Supabase
```

### Project structure

```
inkguard/
├── backend/
│   ├── main.py          # FastAPI app: /health and /check backed by data/db.json
│   ├── api.py           # Alternate FastAPI app with optional AI tone checks (Groq)
│   ├── engine.py        # Core checks: banned terms, claim matching, verified fixes
│   ├── compiler.py      # PDF → candidate rules (regex, plus optional AI extraction)
│   ├── llm.py           # Groq client wrapper, tone findings, injection-safe prompts
│   ├── mcp_server.py    # MCP server exposing approved rules and facts
│   ├── models.py        # Pydantic models: Finding, CheckRequest, CheckResponse, Decision
│   ├── store.py         # Thread-safe JSON store and audit log helper
│   ├── data/
│   │   ├── seed.json    # Sample brand rules and facts
│   │   └── db.json      # Working database
│   └── test_*.py        # pytest suites for the engine, compiler and API
├── frontend/
│   └── index.html       # Landing page
└── docs/
    └── API.md           # Full API route plan
```

---

## 🧰 Tech Stack

- **Backend:** Python, FastAPI, Pydantic
- **PDF parsing:** pypdf
- **AI (optional):** Groq API (default model `openai/gpt-oss-20b`, configurable)
- **Agent integration:** Model Context Protocol (MCP) server backed by Supabase
- **Storage:** JSON file for the demo, Supabase for the MCP server
- **Frontend:** HTML and CSS (DM Sans and Outfit fonts)
- **Testing:** pytest

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- (Optional) A [Groq](https://console.groq.com) API key for AI tone checks
- (Optional) A Supabase project for the MCP server

### 1. Clone

```bash
git clone https://github.com/sugu-01/inkguard.git
cd inkguard/backend
```

### 2. Install dependencies

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install fastapi uvicorn pydantic pypdf groq python-dotenv mcp supabase pytest httpx
```

### 3. Configure environment (optional)

Create `backend/.env`:

```env
# AI tone checks (optional; the app works without it)
GROQ_API_KEY=your_groq_key
LLM_MODEL=openai/gpt-oss-20b

# MCP server (only needed to run mcp_server.py)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
```

> `.env` is git-ignored. Never commit keys.

### 4. Run the API

```bash
uvicorn main:app --reload --port 8000
```

Open the interactive docs at **http://localhost:8000/docs**.

### 5. Open the frontend

Open `frontend/index.html` in your browser, or serve it:

```bash
cd ../frontend && python -m http.server 5173
```

### 6. Run the tests

```bash
cd backend
pytest
```

---

## 📡 API

Base URL: `http://localhost:8000`

### `GET /health`

```json
{ "ok": true, "message": "InkGuard API is running" }
```

### `POST /check`

Request:

```json
{ "text": "Get guaranteed results for just 499 per month!" }
```

Response:

```json
{
  "findings": [
    {
      "kind": "rule",
      "ref": "R-01",
      "start": 4,
      "end": 14,
      "message": "Banned term 'guaranteed'.",
      "proof": "R-01, page 3: Never use: guaranteed, risk-free",
      "fix": "proven",
      "source": "code"
    }
  ],
  "ai_available": false
}
```

### Planned routes

See [`docs/API.md`](docs/API.md) for the full role-based route design:

| Route | Role | Purpose |
|---|---|---|
| `GET /rules` | Brand manager | View rules |
| `POST /rules/compile` | Brand manager | Compile rules from a PDF |
| `POST /rules/{id}/approve` | Brand manager | Approve a rule |
| `GET/POST /facts` | Brand manager | View and add facts |
| `POST /submissions` | Creator | Submit content for review |
| `POST /submissions/{id}/decision` | Reviewer | Approve, request changes, or escalate |
| `GET /audit` | Anyone | Audit trail |
| `GET /insights` | Anyone | Chart and insight data |

> **Role header:** the demo identifies users with an `X-Role` header (e.g. `X-Role: Brand manager`). This is a demo shortcut, **not** real authentication. A production build must enforce permissions on the server.

---

## 🤖 MCP Server

`backend/mcp_server.py` exposes InkGuard data to MCP-compatible AI agents over stdio:

| Tool | Description |
|---|---|
| `get_company_rules` | Approved brand guidelines for a company |
| `get_approved_facts` | Approved facts with owners and expiry dates |

```bash
python mcp_server.py
```

Only **approved** rules are ever returned, so agents cannot enforce unreviewed guidance.

---

## 🔒 Safety & Trust

- Rules start as `approved: false` and are enforced only after a human approves them.
- The compiler never invents replacements. Terms without an explicit replacement get no auto-fix.
- AI output is validated: quotes must exist in the source text, confidence is clamped to 0–1, and malformed output is discarded.
- Provider errors and API keys are never exposed to clients.
- Fixes are applied only when `verified_fix()` proves the result is strictly cleaner.

---

## 🗺️ Roadmap

- [ ] Wire up the full role-based API from `docs/API.md`
- [ ] Interactive checker UI with highlighted spans and one-click verified fixes
- [ ] PDF upload and rule approval flow in the frontend
- [ ] Submission and review workflow with audit trail
- [ ] Insights dashboard (most common violations, stale-fact alerts)
- [ ] Real authentication in place of the `X-Role` demo header
- [ ] Tighten CORS and move storage fully to a database

---

## 🤝 Contributing

Issues and PRs are welcome. Please run `pytest` before opening a PR.

## 📄 License

No license has been chosen yet. Add one (for example MIT) before sharing publicly.

---

<p align="center">Made with ☕ for the hackathon. <b>InkGuard</b>: check your copy before it ships.</p>
