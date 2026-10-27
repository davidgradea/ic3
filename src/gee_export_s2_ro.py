"""Exportă seria Sentinel-2 pe zona din România în același format ca PASTIS-R.

- colecția COPERNICUS/S2_SR_HARMONIZED, aceleași 10 benzi și aceeași ordine ca PASTIS
  (B2, B3, B4, B5, B6, B7, B8, B8A, B11, B12), grilă de 10 m;
- scorul de nori Cloud Score+ (GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED, banda cs_cdf) exportat separat;
- sezonul agricol 1 sep. (an−1) – 31 oct. (an), ca fereastra PASTIS (sep. 2018 – oct. 2019);
- pe lângă GeoTIFF-uri, salvează un CSV cu NDVI-ul mediu pe zonă pe fiecare dată (figura FR vs. RO).

Necesită cont Google Earth Engine:
    pip install earthengine-api geemap geopandas
    earthengine authenticate

Utilizare:
    python src/gee_export_s2_ro.py --aoi zona_ro.geojson --year 2024 --out RO_2024 --project <proiect-gcp>
"""
import argparse
import os

import ee

BANDS = ["B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aoi", default="zona_ro.geojson")
    ap.add_argument("--year", type=int, default=2024, help="anul recoltei (sezon sep. an−1 → oct. an)")
    ap.add_argument("--out", default="RO_2024")
    ap.add_argument("--project", default=None)
    ap.add_argument("--max-cloud", type=float, default=0.6, help="cs_cdf minim mediu pe zonă (0..1) pentru o dată utilă")
    ap.add_argument("--no-tif", action="store_true", help="doar inventarul și CSV-ul NDVI")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    ee.Initialize(project=a.project)

    import geopandas as gpd
    import geemap
    aoi = geemap.geopandas_to_ee(gpd.read_file(a.aoi).to_crs(4326)).geometry()

    start, end = f"{a.year - 1}-09-01", f"{a.year}-10-31"
    s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
          .filterBounds(aoi).filterDate(start, end)
          .linkCollection(ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"), ["cs_cdf"]))

    def add_props(img):
        clear = img.select("cs_cdf").reduceRegion(ee.Reducer.mean(), aoi, 20, maxPixels=1e9).get("cs_cdf")
        nd = img.normalizedDifference(["B8", "B4"]).updateMask(img.select("cs_cdf").gte(a.max_cloud))
        nd_mean = nd.reduceRegion(ee.Reducer.mean(), aoi, 20, maxPixels=1e9).get("nd")
        return img.set({"date": img.date().format("YYYY-MM-dd"), "clear_frac": clear, "ndvi_mean": nd_mean})

    s2 = s2.map(add_props)
    inv = s2.reduceColumns(ee.Reducer.toList(4), ["date", "clear_frac", "ndvi_mean", "system:index"]).get("list").getInfo()
    with open(os.path.join(a.out, "s2_inventory.csv"), "w") as f:
        f.write("date,clear_frac,ndvi_mean,system_index\n")
        for d, c, n, idx in inv:
            f.write(f"{d},{c},{'' if n is None else n},{idx}\n")
    usable = [r for r in inv if r[1] is not None and r[1] >= a.max_cloud]
    print(f"Scene S2 în sezon: {len(inv)} · utile (cs_cdf ≥ {a.max_cloud}): {len(usable)}")

    if a.no_tif:
        return
    for d, c, n, idx in usable:
        img = s2.filter(ee.Filter.eq("system:index", idx)).first()
        geemap.ee_export_image(img.select(BANDS).toInt16().clip(aoi), os.path.join(a.out, f"S2_{d}.tif"),
                               scale=10, region=aoi, crs="EPSG:32635")
        geemap.ee_export_image(img.select("cs_cdf").clip(aoi), os.path.join(a.out, f"CS_{d}.tif"),
                               scale=10, region=aoi, crs="EPSG:32635")
    print("Export terminat în", a.out)


if __name__ == "__main__":
    main()
