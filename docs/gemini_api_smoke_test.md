# Gemini API Smoke Test Manual

This smoke test runs one manual recommendation draft through VIA's
`GeminiApiDraftingProvider`. It is manual only and is not part of `pytest`.

The LLM only drafts prose from precomputed data. It must not calculate scores,
weights, memberships, gaps, ranking, categories, or agronomic decisions.

## Required Environment

Do not print, commit, or paste API keys into the repository.

```powershell
$env:LLM_DRAFTING_PROVIDER="gemini_api"
$env:GEMINI_API_KEY="TU_API_KEY"
$env:GEMINI_API_MODEL="gemma-3-27b-it"
```

Optional:

```powershell
$env:GEMINI_API_BASE_URL="https://generativelanguage.googleapis.com/v1beta"
$env:GEMINI_API_TIMEOUT_SECONDS="30"
$env:GEMINI_API_MAX_OUTPUT_TOKENS="2048"
$env:LLM_MAX_PROMPT_CHARS="12000"
```

## Gemini API Contract Expected by VIA

The adapter builds the endpoint:

```text
{GEMINI_API_BASE_URL}/models/{GEMINI_API_MODEL}:generateContent
```

The API key is sent in the `x-goog-api-key` header, not in the URL.

It sends a REST `generateContent` payload:

```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        {
          "text": "Redacta una recomendacion agricola..."
        }
      ]
    }
  ],
  "generationConfig": {
    "temperature": 0.2,
    "maxOutputTokens": 2048
  }
}
```

VIA expects text at:

```json
{
  "candidates": [
    {
      "content": {
        "parts": [
          {
            "text": "texto redactado"
          }
        ]
      }
    }
  ]
}
```

If Gemini returns a different response shape, update the parser with a fake
transport unit test before relying on the smoke test.

## Output Contract

The adapter accepts only the final recommendation text. It must be in Spanish
and include these sections:

1. Resumen ejecutivo
2. Justificacion de viabilidad
3. Brechas y factores limitantes
4. Acciones recomendadas
5. Advertencias o limites de evidencia

The response is rejected if it is empty, too short, missing the expected
sections, omits score or brecha, repeats prompt instructions, includes internal
metacommentary such as `I should`, `the prompt says`, `ensure`, or `do not
calculate`, or otherwise exposes the drafting instructions instead of the final
recommendation.

Gemini HTTP errors are reported with sanitized diagnostics such as:

```text
Gemini API request failed: HTTP 503 - UNAVAILABLE - This model is currently experiencing high demand.
```

API keys and sensitive headers are not included in error messages.

## Example Command

```powershell
python scripts/gemini_api_smoke_test.py
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
- includes two evidence fragments so the prompt asks for a structured recommendation with summary, justification,
  gaps, actions, and evidence;
- calls only `GeminiApiDraftingProvider`;
- does not persist to the database;
- does not start the saga;
- does not require GEE, Evaluation, Recommendation endpoints, or RAG.
