# TapFix: Smart Guided Troubleshooting Engine

Samsung PRISM GenAI Hackathon 2026-27, Theme 02. Turns a vague device complaint into an
ordered troubleshooting plan where each actionable step carries a real Settings deeplink
from Samsung's catalog.

**Status: Step 3 (validation, direction, no-match, sequencing).** `GET /health` works; `POST /v1/troubleshoot` validates the
request and returns 501 until the pipeline is built in later steps. The deterministic safety layer is built and tested (`retrieval`, `direction`, `relevance`, `matching`, `sequencing`, `validation`, `plan`); there is no LLM yet.

## Quick start (Windows, PowerShell, from the project folder)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copy Samsung's four data files into the `data\` folder:
`deeplinks.json`, `siis_responses.json`, `input.txt`, `sample_output.json`
(they are inside `Theme02_Input_Kit.zip`, in `student_kit\`).

```powershell
python -m pytest            # run the tests
uvicorn app.main:app --reload   # start the API
```

Then open http://127.0.0.1:8000/health (expect `{"status":"ok"}`) or
http://127.0.0.1:8000/docs to try the endpoints.

If PowerShell blocks `activate`, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Configuration
Copy `.env.example` to `.env`. Never commit `.env` (it is git-ignored).

## Open decisions (to settle before the final release tag)
1. Samsung's data files are git-ignored for now; confirm with the organisers whether they may go in a public repo.
2. Where the `"fallback": "no_match"` metadata sits in the response (the guide does not say).
3. Description length: the guide says 5-7 words, but Samsung's own sample uses 9 and 12.
4. Behaviour when the SIIS article only weakly matches the complaint.
5. The `bixby://dummy_positive` placeholder: Samsung's guide allows it for a valid screen missing from the catalog, but our validator rejects it everywhere (stricter than the guide).
6. Toggles with no stated direction return AMBIGUOUS_DIRECTION (never a guess); the LLM stage must state ON/OFF. Samsung's own sample step text has no direction word.
7. Samsung's data contradicts itself in places (sample descriptions of 9 and 12 words vs the 5-7 rule; catalog entry DL-0497 says "Enable" but is typed offURL).
