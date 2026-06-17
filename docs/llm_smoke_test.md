# LLM Local Smoke Test Manual

This smoke test runs one manual recommendation draft through VIA's
`LocalHttpLlmDraftingProvider`. It is manual only and is not part of `pytest`.

The LLM only drafts prose from precomputed data. It must not calculate scores,
weights, memberships, gaps, ranking, categories, or agronomic decisions.

## Required Environment

Set these variables locally:

```powershell
$env:LLM_DRAFTING_PROVIDER="local_http"
$env:LLM_LOCAL_HTTP_ENDPOINT="http://localhost:11434/api/generate"
$env:LLM_MODEL="gemma:2b"
```

Optional:

```powershell
$env:LLM_TIMEOUT_SECONDS="30"
$env:LLM_MAX_PROMPT_CHARS="12000"
```

## HTTP Contract

The adapter sends a `POST` request with JSON:

```json
{
  "model": "gemma:2b",
  "prompt": "Redacta una recomendacion agricola...",
  "stream": false
}
```

This matches Ollama-style `/api/generate` when `stream=false`. The response must
be a JSON object with one of these text fields:

```json
{ "response": "texto redactado" }
```

Also accepted for compatibility:

```json
{ "text": "texto redactado" }
{ "content": "texto redactado" }
{ "choices": [{ "text": "texto redactado" }] }
{ "choices": [{ "message": { "content": "texto redactado" } }] }
```

Empty text, missing text fields, non-JSON responses, HTTP failures, and timeouts
are treated as technical errors.

## Example Command

Start your local LLM server first, then run:

```powershell
python scripts/llm_smoke_test.py
```

Expected output:

```json
{
  "status": "ok",
  "text": "..."
}
```

The script:

- builds an in-memory example `RecommendationDraftContext`;
- calls only `LocalHttpLlmDraftingProvider`;
- does not persist to the database;
- does not start the saga;
- does not require GEE, Evaluation, Recommendation endpoints, or RAG.
