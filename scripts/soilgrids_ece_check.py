"""Standalone check: does a candidate GEE soil-salinity asset exist, and what does it contain?

Run manually with GEE credentials already configured (same auth gee_client.py uses).
This does NOT go through the VIA extraction registry — it queries the asset directly.

History: "projects/soilgrids-isric/ece" was assumed during design and does NOT exist
(confirmed via this script: "Image asset ... not found"). SoilGrids 2.0's 10 standard
properties (bdod, cec, cfvo, clay, nitrogen, ocd, ocs, phh2o, sand, silt, soc) do not
include electrical conductivity at all.

Current candidate: "projects/sat-io/open-datasets/global_soil_salinity" — a community
(not official ISRIC) ImageCollection from the awesome-gee-community-catalog, covering
7 static years (1986-2016, no more recent data), built via random forest with reported
validation accuracy 67-70%. This is materially lower confidence than the OpenLandMap
soil layers already used for pH/clay/sand/OC. Confirm band names/units/scale below
before deciding whether to use it.

Usage:
    python scripts/soilgrids_ece_check.py
"""

from __future__ import annotations

import ee

from via.config import load_settings

ASSET_ID = "projects/sat-io/open-datasets/global_soil_salinity"


def main() -> int:
    settings = load_settings()
    if settings.gee_private_key_json:
        credentials = ee.ServiceAccountCredentials(
            settings.gee_service_account, key_data=settings.gee_private_key_json
        )
    else:
        credentials = ee.ServiceAccountCredentials(
            settings.gee_service_account, settings.gee_private_key_file
        )
    ee.Initialize(credentials, project=settings.gee_project)

    print(f"Checking: {ASSET_ID}")
    try:
        collection = ee.ImageCollection(ASSET_ID)
        size = collection.size().getInfo()
        print(f"EXISTS as ImageCollection. Image count: {size}")

        first = collection.first()
        bands = first.bandNames().getInfo()
        print(f"First image band names: {bands}")

        info = first.getInfo()
        props = info.get("properties", {})
        print(f"First image properties: {props}")

        projection = first.select(0).projection().getInfo()
        print(f"Projection: {projection}")

        scale = first.select(0).projection().nominalScale().getInfo()
        print(f"Nominal scale (m): {scale}")

        dates = collection.aggregate_array("system:time_start").getInfo()
        print(f"system:time_start values (ms epoch, one per image): {dates}")

        return 0
    except Exception as exc:
        print(f"NOT FOUND or error: {exc}")
        print(
            "\nThis asset id was found via web search of the GEE community catalog, not "
            "verified before this run. If it fails, search "
            "https://gee-community-catalog.org/ and https://developers.google.com/earth-engine/datasets "
            "directly for 'salinity' / 'electrical conductivity' before registering anything "
            "in gee_variable_registry.py."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
