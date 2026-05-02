# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AI-powered evaluation system for judging open-ended coding/project submissions. Judges submit a project name, participant, objective, GitHub repo link, and UI/deployment link. Independent agents evaluate the submission across three dimensions (objective alignment, code quality, UI/UX), and an aggregator produces a final report.

**Status:** Active development. `readme.md` is the authoritative design document.

## Planned Tech Stack

- **Backend:** FastAPI + Uvicorn, Python 3.10+, Pydantic
- **Frontend:** Streamlit
- **LLM layer:** Pluggable `LLMClient` interface — OpenAI (default) or local models (Ollama / vLLM / HuggingFace)
- **Storage:** SQLite for dev (`data/evals.db`), Postgres for production — toggled via `config.yaml`
- **Observability:** `structlog` for structured JSON logging
- **Code analysis:** GitPython, optional pylint / flake8
- **UI testing:** `requests` + HTML parsing (Playwright deferred to later)

## Development Commands

```bash
pip install -r requirements.txt

# Generate a judge password hash (add to config.yaml judges list)
python -c "from passlib.hash import bcrypt; print(bcrypt.hash('yourpassword'))"

uvicorn api.main:app --reload       # API server (dev, http://localhost:8000)
streamlit run frontend/app.py       # Streamlit UI (http://localhost:8501)

pytest                              # Run tests
```

## Architecture

```
Streamlit UI → FastAPI Gateway → [Objective Agent | Code Agent | UI Agent] → Aggregator → Report
```

All three evaluation agents run **in parallel**. The aggregator merges their outputs using configurable weights (default: objective 0.4, code 0.3, ui 0.3).

### Planned folder structure

```
project/
├── api/            # FastAPI app, routes/, middleware/ (auth, rate limiting)
├── agents/
│   ├── objective_agent/
│   │   └── prompts/        # objective_v1.0.txt, objective_v1.2.txt, ...
│   ├── code_agent/
│   │   └── prompts/
│   ├── ui_agent/
│   │   └── prompts/
│   └── aggregator/
├── core/
│   ├── config.py           # loads config.yaml
│   ├── llm/                # LLMClient base + OpenAIClient, LocalModelClient
│   ├── security/           # JWT auth
│   ├── audit/              # evaluation record schema, immutable record writer
│   └── observability/      # structlog setup, JSON log formatter
├── services/       # repo_service.py (GitPython, pins commit SHA), evaluation_service.py
├── frontend/       # streamlit_app.py
├── tests/
└── config.yaml     # All externalized config (model, security, weights, repo limits)
```

### API endpoints

```
POST /evaluate                          # Submit evaluation request; returns report + agents (reasoning, sub-scores)
GET  /report/{id}                       # Final report + agents (reasoning, sub-scores); raw_llm_response excluded
GET  /report/{id}/provenance            # Full provenance: input snapshot, config snapshot, per-agent LLM metadata
GET  /report/{id}/raw                   # Raw per-agent LLM responses
GET  /evaluations?judge=X&date=Y        # Filterable evaluation history
POST /report/{id}/override              # Submit a judge score override (append-only)
GET  /metrics/summary                   # Aggregate stats: score distributions, override rate, token costs
GET  /metrics/evaluation/{id}           # Per-evaluation token/latency breakdown
```

Both `POST /evaluate` and `GET /report/{id}` include an `agents` field with per-agent `score`, `reasoning`, `confidence`, `sub_scores` (code agent only), `llm`, `prompt_version`, `tokens`, and `latency_ms`. `raw_llm_response` is intentionally excluded — fetch it separately via `/raw`.

### UI agent evaluation modes

`ui_url` is optional. The UI agent combines live deployment data with frontend source files from the cloned repo:

| Scenario | Data used | Confidence cap |
|---|---|---|
| URL provided + reachable | Live HTML (headings, links, forms, title) + source files | none |
| URL provided + unreachable | Source files only | `medium` |
| No URL (local/undeployed) | Source files only | `medium` |

The same `file_contents` list already selected by the repo service for the code agent is reused — no second clone or fetch. The prompt instructs the LLM to infer layout, flows, and completeness from frontend files when no live URL is available.

### Agent output contract

Objective and UI agents return a flat score. The Code agent returns sub-dimension scores.

**Objective / UI agent (success):**
```json
{
  "status": "ok",
  "score": 8,
  "reasoning": "...",
  "confidence": "low|medium|high",
  "llm": { "provider": "openai", "model": "gpt-4o-mini", "model_version": "2024-07-18" },
  "prompt_version": "objective_v1.2",
  "tokens": { "input": 1200, "output": 310 },
  "latency_ms": 1540,
  "raw_llm_response": "..."
}
```

**Code agent (success):**
```json
{
  "status": "ok",
  "score": 7.2,
  "sub_scores": {
    "cleanliness":    { "score": 8, "reasoning": "..." },
    "modularity":     { "score": 7, "reasoning": "..." },
    "security":       { "score": 6, "reasoning": "Hardcoded API key in config.py" },
    "robustness":     { "score": 7, "reasoning": "..." },
    "best_practices": { "score": 8, "reasoning": "..." }
  },
  "reasoning": "...",
  "confidence": "high",
  "llm": { "provider": "openai", "model": "gpt-4o-mini", "model_version": "2024-07-18" },
  "prompt_version": "code_v1.0",
  "tokens": { "input": 3200, "output": 580 },
  "latency_ms": 2100,
  "raw_llm_response": "..."
}
```

`score` is the weighted average of `sub_scores` using `config.evaluation.code_sub_weights` (defaults: security 0.30, modularity 0.25, robustness 0.20, cleanliness 0.15, best_practices 0.10).

**Any agent (failure):**
```json
{ "status": "failed", "error": "timeout after 30s" }
```

The aggregator reweights remaining successful agents proportionally and appends a flag for each failure. Known flags: `code_agent_failed`, `objective_agent_failed`, `ui_agent_failed`, `low_confidence`, `high_agent_disagreement` (spread > 4 pts), `repo_not_accessible`, `ui_url_unreachable`, `security_issue_detected`.

```json
{
  "overall_score": 7.5,
  "objective_score": 8,
  "code_score": null,
  "ui_score": 7,
  "weights_used": { "objective": 0.4, "code": 0.3, "ui": 0.3 },
  "summary": "...",
  "flags": ["code_agent_failed"],
  "judge_overrides": []
}
```

## Governance Invariants

These must hold in every implementation decision:

1. **Pinned commit SHA** — `repo_service.py` must resolve the repo to a specific commit SHA at evaluation time. Never store or re-use `HEAD`.
2. **Config snapshot** — a copy of `config.yaml` (not a reference) is embedded in every evaluation record by `core/audit/`.
3. **Judge overrides are append-only** — `POST /report/{id}/override` appends to `judge_overrides[]`; the original agent scores are never modified.
4. **Prompt versions are files** — prompts live under `agents/<name>/prompts/` as versioned `.txt` files. Agents load by name and record the version string in their output. No inline prompt strings.
5. **Structured logging everywhere** — every log line emits `evaluation_id` and `agent` fields so parallel agent logs are always correlatable.
6. **Storage is insert-only** — `core/audit/` only inserts evaluation records, never updates or deletes. Overrides and re-evaluations create new records.

## Key Design Decisions

**LLM abstraction:** All LLM calls return `LLMResponse(text, model_version, tokens_input, tokens_output, latency_ms)`. Never call provider SDKs directly from agents — always go through `core/llm/`. `model_version` is populated from the API response, not from config, so it reflects the actual model snapshot used.

**Storage:** SQLite for dev (`data/evals.db`), Postgres for production. Backend is toggled via `config.yaml database.backend`. `core/audit/` writes evaluation records; it must never overwrite an existing record — only insert.

**Agent failure:** Partial results are valid. Failed agents emit `{ "status": "failed", "error": "..." }`. The aggregator reweights surviving agents proportionally and appends a flag. Never zero-score a failed agent — `null` score + flag is the correct representation.

**Code agent sub-dimension scoring:** A single LLM call requests scores across five dimensions: `cleanliness`, `modularity`, `security`, `robustness`, `best_practices`. The `security` dimension has the highest weight (0.30) and instructs the LLM to explicitly flag hardcoded secrets, injection vectors, missing auth, and OWASP Top 10 patterns. Any flagged security issue also sets `security_issue_detected` in the top-level `flags[]`. Sub-weights are configurable in `config.evaluation.code_sub_weights`.

**Code agent file selection:** Entry points first (`main.py`, `app.py`, `server.*`, `index.*`), then files in last `config.repo.recent_commits` (default 10) commits, then smallest files to fill up to `config.repo.max_files` (default 50).

**Config externalization:** All tunable parameters live in `config.yaml`, loaded via `core/config.py`. `agent_timeout_seconds` and `recent_commits` are both configurable.

**Security guardrails:** Reject oversized repos and invalid URLs at the API gateway. Truncate large files before sending to LLM. Sanitize all inputs. Enforce per-agent execution timeouts.

**UI agent data strategy:** The UI agent receives `file_contents` (the same list the code agent uses) alongside the live URL fetch result. When `ui_url` is empty or unreachable, the prompt switches to source-only mode and caps confidence at `medium`. Never score 0 solely because the URL is absent — use `null` + flag only if both URL and source are unavailable.

**Reasoning depth:** Prompts are calibrated to produce actionable, specific reasoning — not one-liners. Code sub-scores: 2-3 sentences citing specific files or patterns. Code overall reasoning: 4-6 sentences covering strengths, weaknesses, and critical findings. Objective and UI agents: 4-6 sentences with specific references to implemented/missing functionality or structural observations.

**Report response includes per-agent detail:** `POST /evaluate` and `GET /report/{id}` both include an `agents` object with reasoning, sub-scores, confidence, and LLM metadata. `raw_llm_response` is excluded from these responses (available via `/raw`) to keep payload size reasonable.

**What NOT to build in v1:** LangGraph or other multi-agent orchestration frameworks, ML-based scoring models, real-time streaming, deep UI automation (Playwright), vector databases.
