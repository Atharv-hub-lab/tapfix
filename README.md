# TapFix â€” Smart Guided Troubleshooting Engine

TapFix is a REST API built for the **Samsung PRISM GenAI Hackathon 2026–27 â€” Theme 02: Smart Guided Troubleshooting Engine**.

It converts a user's device complaint into a structured troubleshooting plan while grounding troubleshooting guidance in Samsung SIIS evidence and mapping supported actions to trusted Samsung Settings deeplinks.

---

## Problem

Users often describe device problems in vague language such as:

> My phone display is completely black.

A troubleshooting system must understand the complaint, identify relevant troubleshooting evidence, select appropriate actions, and guide the user toward the required Settings screen when a valid Settings deeplink exists.

TapFix addresses this using query understanding, retrieval, SIIS-grounded reasoning, trusted catalog mapping, validation, and fast-path caching.

---

## What TapFix Does

A typical request follows this pipeline:

```text
User Complaint
      â†“
Query Understanding
      â†“
Query Normalization
      â†“
BM25 Retrieval
      â†“
SIIS Evidence Retrieval
      â†“
Two-Stage Solution Reasoning
      â†“
Trusted Catalog Mapping
      â†“
Schema Validation
      â†“
Fast-Path Cache
      â†“
Structured JSON Response
```

---

## Architecture

### 1. Query Understanding

The incoming complaint is normalized into a technical retrieval query.

The system identifies useful signals such as:

- device symptoms
- ON/OFF direction
- technical keywords
- relevant troubleshooting intent

A deterministic provider provides a reliable fallback when the LLM provider is unavailable.

### 2. Retrieval

TapFix uses a lightweight BM25 retrieval implementation to search the available troubleshooting catalog.

The retrieval layer is designed to work with the supplied Samsung catalog without requiring a large external retrieval dependency.

### 3. SIIS Evidence Retrieval

When a request does not provide a SIIS response directly, TapFix can retrieve a relevant SIIS article from the locally available SIIS records.

Retrieval is intentionally symptom-aware:

- strongly vague complaints should not select arbitrary troubleshooting articles
- concrete symptoms such as black screens, freezing, charging, Wi-Fi, Bluetooth, and battery problems can trigger relevant SIIS retrieval

This prevents weak symptom matches from producing unrelated troubleshooting actions.

### 4. Two-Stage Solution Reasoning

The solution pipeline separates understanding from solution generation.

#### Stage 1 â€” Query Understanding

Converts the raw complaint into a normalized technical intent.

#### Stage 2 â€” Solution Generation

Uses SIIS troubleshooting evidence and catalog candidates to construct a structured solution.

When SIIS evidence is available, troubleshooting steps are grounded in that evidence rather than being freely invented.

### 5. Trusted Catalog Mapping

Catalog deeplinks are treated as trusted data.

TapFix does not invent Samsung deeplink URIs.

When a supported catalog entry is selected, the deeplink is copied from the trusted catalog.

If a supported Settings mapping is not available, the system can return a manual troubleshooting action instead of fabricating a deeplink.

### 6. Validation

Before a response is returned, the generated plan is validated against the API contract.

Validation checks include:

- required fields
- action structure
- category values
- step presence
- deeplink validity
- trusted catalog membership
- URL-leak prevention

### 7. Fast-Path Cache

Validated responses are cached so repeated requests can be served without rebuilding the entire troubleshooting plan.

The cache also supports normalized/paraphrased queries.

This allows repeated requests to stay within the required low-latency target.

---

## Vague Query Handling

TapFix distinguishes between strongly vague complaints and complaints containing useful technical symptoms.

For example:

> My phone isn't working properly

does not contain enough reliable information to select an arbitrary Samsung troubleshooting article.

Instead of guessing, TapFix returns a safe manual troubleshooting response.

For a concrete complaint such as:

> My screen is completely black and I can't see anything

TapFix can retrieve the corresponding SIIS troubleshooting article and return the grounded troubleshooting steps.

This approach prioritizes correctness over unsupported catalog matches.

---

## API

### Health Check

```http
GET /health
```

Example response:

```json
{
  "status": "ok"
}
```

### Troubleshooting

```http
POST /v1/troubleshoot
```

Example request:

```json
{
  "query": "My phone is not charging",
  "siis_response": ""
}
```

The `siis_response` field can also contain a supplied SIIS article.

Example structure:

```json
{
  "query": "My phone is not charging",
  "siis_response": {
    "title": "Charging issues",
    "content": "Troubleshooting guidance..."
  }
}
```

The API returns a structured troubleshooting response containing:

- goal
- title
- score
- action name
- action description
- category
- troubleshooting steps
- actionable deeplink when supported
- validation deeplink when applicable

---

## Project Structure

```text
tapfix/
â”‚
â”œâ”€â”€ app/
â”‚   â”œâ”€â”€ api_models.py
â”‚   â”œâ”€â”€ articles.py
â”‚   â”œâ”€â”€ catalog.py
â”‚   â”œâ”€â”€ config.py
â”‚   â”œâ”€â”€ direction.py
â”‚   â”œâ”€â”€ main.py
â”‚   â”œâ”€â”€ matching.py
â”‚   â”œâ”€â”€ pipeline.py
â”‚   â”œâ”€â”€ plan.py
â”‚   â”œâ”€â”€ relevance.py
â”‚   â”œâ”€â”€ retrieval.py
â”‚   â”œâ”€â”€ sequencing.py
â”‚   â”œâ”€â”€ validation.py
â”‚   â”‚
â”‚   â””â”€â”€ llm/
â”‚       â”œâ”€â”€ gemini.py
â”‚       â”œâ”€â”€ mock.py
â”‚       â”œâ”€â”€ parsing.py
â”‚       â”œâ”€â”€ provider.py
â”‚       â”œâ”€â”€ solution.py
â”‚       â”œâ”€â”€ solution_gemini.py
â”‚       â”œâ”€â”€ solution_parsing.py
â”‚       â”œâ”€â”€ solution_provider.py
â”‚       â””â”€â”€ trusted_solution.py
â”‚
â”œâ”€â”€ data/
â”‚   â”œâ”€â”€ deeplinks.json
â”‚   â”œâ”€â”€ siis_responses.json
â”‚   â””â”€â”€ ...
â”‚
â”œâ”€â”€ scripts/
â”‚   â”œâ”€â”€ hackathon_validation.py
â”‚   â””â”€â”€ official_20_validation.py
â”‚
â”œâ”€â”€ tests/
â”‚
â”œâ”€â”€ Dockerfile
â”œâ”€â”€ requirements.txt
â”œâ”€â”€ .env.example
â””â”€â”€ README.md
```

---

## Tech Stack

- Python 3.12
- FastAPI
- Pydantic
- BM25 retrieval
- Gemini API integration
- Custom deterministic fallback providers
- Docker
- Pytest

---

## Local Setup

### 1. Clone the repository

```powershell
git clone https://github.com/Atharv-hub-lab/tapfix.git
cd tapfix
```

### 2. Create a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the example environment file:

```powershell
Copy-Item .env.example .env
```

Configure the required values in `.env`.

**Do not commit `.env` or API keys to Git.**

### 5. Start the API

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The API will be available at:

```text
http://localhost:8000
```

Health check:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

---

## Docker

### Build

```powershell
docker build -t tapfix:final .
```

### Run

```powershell
docker run -d --name tapfix-final -p 8000:8000 tapfix:final
```

### Health Check

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Expected:

```json
{
  "status": "ok"
}
```

---

## Testing

Run the complete automated test suite:

```powershell
pytest -q
```

The final verified run produced:

```text
427 passed
```

---

## Hackathon Validation

Run the project validation scripts:

```powershell
$env:PYTHONPATH = "."

python scripts/hackathon_validation.py
python scripts/official_20_validation.py
```

### Final Measured Validation Results

| Metric | Result |
|---|---:|
| Automated tests | 427 passed |
| Core scenarios | 6/6 |
| Official Samsung scenarios | 20/20 |
| Schema validity | 20/20 |
| URL leaks | 0 |
| Invalid deeplinks | 0 |
| Unseen scenario | Passed |
| Repeat-query cache p95 | 48.9 ms |
| Paraphrase cache coverage | 9/9 |
| Cold-start p95 | 50.5 ms |
| Query variations | 10/10 |
| Official 20-query p95 | 34.2 ms |

These are measured results from the local validation environment and are not intended as production infrastructure benchmarks.

---

## Security

TapFix follows several safety constraints:

- API credentials are supplied through environment variables.
- `.env` is excluded from Git.
- Samsung catalog deeplinks are copied from trusted catalog data.
- The system does not fabricate catalog deeplink URIs.
- URL-leak validation is included in the test suite.
- SIIS content is treated as troubleshooting evidence rather than as permission to invent unsupported actions.

---

## Limitations

- Troubleshooting coverage depends on the supplied Samsung SIIS and deeplink datasets.
- A manual fallback is used when a reliable catalog mapping cannot be established.
- LLM-based processing depends on the configured provider and its availability/quota.
- Validation measurements are environment-dependent.
- The current implementation is designed around the supplied Samsung hackathon data and API contract.

---

## Final Release

The final evaluated Git commit is tagged:

```text
PRISM_GENAI_HACKATHON_Y2026
```

The tagged commit contains the final verified implementation.

---

## License

This project was developed as a submission for the Samsung PRISM GenAI Hackathon 2026–27.
