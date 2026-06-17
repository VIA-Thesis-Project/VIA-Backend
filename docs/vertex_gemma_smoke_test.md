# Vertex AI Gemma Smoke Test Manual

This smoke test runs one manual recommendation draft through VIA's
`VertexGemmaDraftingProvider`. It is manual only and is not part of `pytest`.

The LLM only drafts prose from precomputed data. It must not calculate scores,
weights, memberships, gaps, ranking, categories, or agronomic decisions.

## Required Environment

Authenticate locally with Google Cloud Application Default Credentials or run
with an IAM identity allowed to invoke the Vertex AI endpoint. Do not print,
commit, or paste service account JSON into the repository.

```powershell
$env:LLM_DRAFTING_PROVIDER="vertex_gemma"
$env:VERTEX_AI_PROJECT_ID="your-gcp-project"
$env:VERTEX_AI_LOCATION="us-central1"
$env:VERTEX_AI_ENDPOINT_ID="123456789"
$env:LLM_MODEL="gemma-2-9b-it"
```

Optional:

```powershell
$env:VERTEX_AI_TIMEOUT_SECONDS="30"
$env:LLM_MAX_PROMPT_CHARS="12000"
```

## Vertex Contract Expected by VIA

The adapter builds the endpoint path:

```text
projects/{VERTEX_AI_PROJECT_ID}/locations/{VERTEX_AI_LOCATION}/endpoints/{VERTEX_AI_ENDPOINT_ID}
```

It calls `PredictionServiceClient.predict(...)` with:

```json
{
  "instances": [
    {
      "prompt": "Redacta una recomendacion agricola...",
      "model": "gemma-2-9b-it"
    }
  ],
  "parameters": {
    "temperature": 0.2,
    "maxOutputTokens": 1024
  }
}
```

The deployed endpoint response is parsed defensively. VIA accepts a prediction
object containing one of these fields:

```json
{ "response": "texto redactado" }
{ "text": "texto redactado" }
{ "content": "texto redactado" }
{ "choices": [{ "text": "texto redactado" }] }
{ "choices": [{ "message": { "content": "texto redactado" } }] }
```

If your deployed Gemma endpoint returns a different prediction shape, update the
parser with a fake-client unit test before relying on the smoke test.

## Example Command

```powershell
python scripts/vertex_gemma_smoke_test.py
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
- calls only `VertexGemmaDraftingProvider`;
- does not persist to the database;
- does not start the saga;
- does not require GEE, Evaluation, Recommendation endpoints, or RAG.
