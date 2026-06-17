# GEE Smoke Test Manual

This smoke test runs one real Google Earth Engine extraction through VIA's `GeeExtractionClient`.
It is manual only and is not part of `pytest`.

## Required Environment

Set these variables locally. Do not commit credential files or private key contents.

```powershell
$env:GEE_ENABLED="True"
$env:GEE_PROJECT="your-gcp-project"
$env:GEE_SERVICE_ACCOUNT="service-account@project.iam.gserviceaccount.com"
$env:GEE_PRIVATE_KEY_FILE="C:\path\to\gee-service-account-key.json"
```

Optional:

```powershell
$env:GEE_TIMEOUT_SECONDS="60"
$env:GEE_MAX_RETRIES="3"
```

## Example Command

Use a small dataset/period/parcel to keep the request cheap and fast. Dataset and band are script inputs, not hardcoded in the client.

```powershell
python scripts/gee_smoke_test.py `
  --dataset-key "COPERNICUS/S2_SR_HARMONIZED" `
  --band "B8" `
  --start "2024-06-01" `
  --end "2024-06-10" `
  --reducer "mean" `
  --scale 30
```

The default geometry is a tiny GeoJSON polygon near Lima. To provide your own small parcel:

```powershell
python scripts/gee_smoke_test.py `
  --dataset-key "COPERNICUS/S2_SR_HARMONIZED" `
  --band "B8" `
  --start "2024-06-01" `
  --end "2024-06-10" `
  --geometry-json '{"type":"Polygon","coordinates":[[[-76.01,-12.01],[-76.01,-12.011],[-76.009,-12.011],[-76.009,-12.01],[-76.01,-12.01]]]}' `
  --fallback-allowed
```

## Expected Output

On success, the script prints JSON with `value`, `source`, `dataset_key`, `band`, `reducer`, and `extraction_date`.

If credentials or project configuration are missing, it prints a controlled configuration error and exits without printing secrets.
