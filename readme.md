# AI Project Evaluator

An open-source, multi-agent system for evaluating hackathon and coding submissions. Judges submit a project's GitHub repo and (optionally) a live deployment URL; independent AI agents score it across objective alignment, code quality, and UI/UX — then an aggregator produces a final report with full reasoning.

---

## Features

- **Three independent evaluation agents** run in parallel — objective alignment, code quality (5 sub-dimensions), and UI/UX
- **Works without a live deployment** — if no URL is provided, the UI agent evaluates directly from frontend source files
- **Pluggable LLM backend** — OpenAI by default; swap to any local model (Ollama, vLLM, HuggingFace) via `config.yaml`
- **Full audit trail** — every evaluation pins the commit SHA, records the prompt version and model version used, and stores raw LLM responses
- **Judge overrides** — scores can be overridden with a reason; original agent scores are never mutated
- **Streamlit UI** for judges and a FastAPI backend with JWT auth and rate limiting

---

## Quick start

### Option A — Docker Compose

**Prerequisites:** Docker Desktop (or Docker Engine + Compose plugin)

```bash
# 1. Clone the repo
git clone https://github.com/your-org/code-reviewer.git
cd code-reviewer

# 2. Create your config
cp config.example.yaml config.yaml
# Edit config.yaml:
#   - Set security.jwt_secret to a random string  (openssl rand -hex 32)
#   - Add your judges (see "Adding judges" below)

# 3. Create your .env file with your OpenAI key
echo "OPENAI_API_KEY=sk-..." > .env

# 4. Start everything
docker compose up -d
```

- **Frontend (judge UI):** http://localhost:8501
- **Backend API:** http://localhost:8000
- **API docs:** http://localhost:8000/docs

To stop: `docker compose down`  
Evaluation records are persisted in `./data/evals.db` across restarts.

---

### Option B — Manual setup

**Prerequisites:** Python 3.10+, `git` on your PATH

```bash
# 1. Clone and install dependencies
git clone https://github.com/your-org/code-reviewer.git
cd code-reviewer
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Create your config
cp config.example.yaml config.yaml
# Edit config.yaml — set jwt_secret and add judges

# 3. Set your OpenAI key
export OPENAI_API_KEY=sk-...          # Windows: set OPENAI_API_KEY=sk-...

# 4. Start the backend (terminal 1)
uvicorn api.main:app --reload

# 5. Start the frontend (terminal 2)
streamlit run frontend/app.py
```

- **Frontend:** http://localhost:8501
- **Backend:** http://localhost:8000 / docs at http://localhost:8000/docs

---

## Configuration

All settings live in `config.yaml` (copied from `config.example.yaml`). The file is git-ignored — never commit it with real secrets.

### Adding judges

Generate a bcrypt password hash for each judge:

```bash
python -c "from passlib.hash import bcrypt; print(bcrypt.hash('yourpassword'))"
```

Then add to `config.yaml`:

```yaml
judges:
  - username: alice
    password_hash: "$2b$12$..."
  - username: bob
    password_hash: "$2b$12$..."
```

### Switching LLM provider

**OpenAI (default):**
```yaml
model:
  provider: openai
  name: gpt-4o-mini   # or gpt-4o, gpt-4-turbo, etc.
```
Set `OPENAI_API_KEY` in your environment or `.env` file.

**Local model (Ollama / vLLM / HuggingFace):**
```yaml
model:
  provider: local
  name: llama3       # model name as your local server expects it
```
Point the local client at your server endpoint — see `core/llm/local_client.py`.

### Switching to Postgres (production)

```yaml
database:
  backend: postgres
  url: postgresql://user:password@host:5432/evals
```

For Docker Compose, add a `db` service and set `url` to the internal hostname.

### Key tuning options

| Setting | Default | Effect |
|---|---|---|
| `evaluation.agent_timeout_seconds` | `30` | Per-agent LLM call timeout |
| `evaluation.weights` | obj 0.4 / code 0.3 / ui 0.3 | Final score weighting |
| `evaluation.code_sub_weights` | security 0.30 highest | Code dimension weighting |
| `repo.max_files` | `50` | Max files sent to code agent |
| `repo.recent_commits` | `10` | Recent commits used for file prioritisation |

---

## How it works

```
Streamlit UI → FastAPI Gateway → [Objective Agent | Code Agent | UI Agent] → Aggregator → Report
```

All three agents run **in parallel**. Each is an independent LLM call with a versioned prompt file.

### Objective agent
Reads the stated objective and key source files, scores 0–10 on how well the implementation delivers on the stated goal.

### Code agent
Scores five sub-dimensions in a single LLM call:

| Dimension | Weight | What is checked |
|---|---|---|
| `security` | 0.30 | Hardcoded secrets, injection vectors, missing auth, OWASP Top 10 |
| `modularity` | 0.25 | Separation of concerns, DRY, function/class size |
| `robustness` | 0.20 | Error handling, boundary conditions, exception propagation |
| `cleanliness` | 0.15 | Naming, formatting, no dead code |
| `best_practices` | 0.10 | Language idioms, consistent patterns |

Files are selected by priority: entry points first → files changed in recent commits → smallest remaining files up to `max_files`.

### UI agent

Combines **live deployment data** (HTML structure, headings, form counts) with **frontend source files** from the repo. Works in three modes:

| Scenario | Data used | Confidence cap |
|---|---|---|
| URL provided and reachable | Live HTML + source files | none |
| URL provided but unreachable | Source files only | `medium` |
| No URL (local/undeployed project) | Source files only | `medium` |

### Aggregator
Merges agent scores using configurable weights. Failed agents are reweighted proportionally (never zeroed). Flags are appended for low confidence, high inter-agent disagreement, security issues, and agent failures.

### Report response
Both `POST /evaluate` and `GET /report/{id}` return per-agent reasoning, sub-scores, and confidence alongside the aggregate — so judges see the full analysis immediately without a second call.

---

## API reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/auth/token` | Get a JWT (username + password) |
| `POST` | `/evaluate` | Submit a project for evaluation |
| `GET` | `/report/{id}` | Full report with per-agent reasoning |
| `GET` | `/report/{id}/provenance` | Model version, tokens, latency, prompt version |
| `GET` | `/report/{id}/raw` | Raw LLM response text per agent |
| `POST` | `/report/{id}/override` | Submit a judge score override (append-only) |
| `GET` | `/evaluations` | Evaluation history (filter by judge, date) |
| `GET` | `/metrics/summary` | Score distributions, override rate, token costs |
| `GET` | `/metrics/evaluation/{id}` | Per-evaluation token/latency breakdown |

Interactive docs available at `http://localhost:8000/docs` when the backend is running.

---

## Prompt versioning

Prompts live as versioned `.txt` files under `agents/<name>/prompts/`. Each agent records the prompt version in its output, so a scoring change between two evaluations can always be attributed to a model change or a prompt change — never ambiguously both.

To ship a new prompt version, add a new file (e.g. `code_v1.1.txt`) and update the `PROMPT_VERSION` constant in the agent. Old records retain their original version string.

---

## Contributing

Pull requests are welcome. A few conventions to keep in mind:

- All LLM calls go through `core/llm/` — never call provider SDKs directly from agents
- Prompts are files, not inline strings
- Evaluation records are insert-only — never update or delete
- Every log line must include `evaluation_id` and `agent` fields
- `config.yaml` is git-ignored — use `config.example.yaml` for any config-related changes

To run the test suite:
```bash
pytest
```

---

## License

MIT — see [LICENSE](LICENSE).
