# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml   # then set jwt_secret and add judges

# Run (two terminals)
uvicorn api.main:app --reload         # backend  → http://localhost:8000
streamlit run frontend/app.py         # frontend → http://localhost:8501

# Tests
pytest
pytest tests/path/to/test_file.py::test_name   # single test

# Generate a judge password hash
python -c "from passlib.hash import bcrypt; print(bcrypt.hash('yourpassword'))"

# Docker (alternative)
docker compose up -d
```

`config.yaml` is git-ignored. All config changes for local dev go there; `config.example.yaml` is the committed template.

## Architecture

```
Streamlit (frontend/app.py)  →  FastAPI (api/)  →  EvaluationService  →  [3 agents in parallel]  →  AggregatorAgent  →  AuditWriter
```

**Request flow for `POST /evaluate`:**
1. `api/routes/evaluate.py` receives the request, authenticates via JWT (`api/middleware/auth.py`), calls `EvaluationService.evaluate()`
2. `services/evaluation_service.py` clones the repo via `RepoService`, then fires all three agents concurrently with `asyncio.gather`. Each agent is wrapped in `run_with_timeout` which retries once on failure before returning `AgentResultFailed`.
3. `AggregatorAgent` merges the three results: failed agents are reweighted proportionally (not zeroed); flags are appended for low confidence, security issues, high inter-agent score spread, and agent failures.
4. `AuditWriter` persists the `EvaluationRecord` to SQLite/Postgres. Records are insert-only — never mutated.
5. The full record (including per-agent reasoning) is returned directly in the response, so no second API call is needed.

## Key conventions

**LLM calls** must go through `core/llm/` (`LLMClient` base class). Never call provider SDKs directly from agents.

**Prompts** live as versioned `.txt` files: `agents/<name>/prompts/<name>_v<N>.<M>.txt`. Each agent hardcodes its `PROMPT_VERSION` constant. To change a prompt, add a new file and bump the constant — old records retain their original version string for audit purposes.

**Agent result types** (`core/audit/models.py`): agents return either `AgentResultOk` / `CodeAgentResultOk` (discriminator `status="ok"`) or `AgentResultFailed` (`status="failed"`). Always check `result.status` before accessing score fields.

**Database**: `AuditWriter` (`core/audit/writer.py`) stores the full `EvaluationRecord` as a JSON blob in `record_json` alongside denormalized query columns. Overrides live in a separate `overrides` table and are never written back into the evaluation blob.

**Config loading** uses `@lru_cache` — the server must restart to pick up `config.yaml` changes.

**File selection** (`services/repo_service.py`): entry points → recently-changed files → smallest remaining files, up to `repo.max_files` (default 50), truncated at 50 KB each.

## Ownership agent

The ownership agent (`agents/ownership_agent/`) scores how much evidence there is that the participant genuinely understands and owns their code — specifically because LLM-generated code is typically clean and well-structured, making traditional quality metrics unreliable signals of actual comprehension.

It detects passive signals from the code itself:
- WHY comments (not just what the code does)
- Custom implementations where a library alternative existed (deliberate choice)
- Architecture shaped to the problem domain vs. generic scaffolding
- Consistent vocabulary and naming reflecting domain knowledge
- Tradeoff acknowledgments, edge cases relevant only to this domain

Output includes `key_decisions` — each with the decision identified, the ownership signal observed, and a **targeted interview question** for the judge to ask the participant. These questions appear in the "Interview Guide" section of both the Streamlit UI and the PDF.

Weight: 0.20 (others are 0.30/0.25/0.25). `ownership_score` is `None` for old records that predate this agent.

## Adding a new agent

1. Create `agents/<name>/agent.py` with a class whose `async def run(...)` returns `AgentResultOk | AgentResultFailed`.
2. Add a versioned prompt under `agents/<name>/prompts/`.
3. Wire it into `EvaluationService` alongside the existing three agents.
4. Add a result field to `AgentResults` in `core/audit/models.py`.
5. Update `AggregatorAgent` to incorporate the new score.

## Switching LLM provider

Set `model.provider: local` in `config.yaml` and point `core/llm/local_client.py` at your local server endpoint (Ollama, vLLM, etc.).
