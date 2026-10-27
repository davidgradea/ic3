# IC3 · A7 · AgriTwin — PASTIS-R → România

Segmentarea culturilor pe parcele românești cu un model antrenat pe Franța (PASTIS-R) și puține etichete locale.
Client: APIA → selecția parcelelor pentru control pe teren.

## Date

| Set | Unde | Folder local  |
|---|---|---|
| PASTIS-R (S1 + S2, Franța) | https://zenodo.org/record/5735646 (CC BY 4.0, 54 GB) | `PASTIS-R/` |
| Sentinel-2 pe zona RO | Google Earth Engine, `zona_ro.geojson` | `RO_2024/` |

## Instalare

```bash
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

## Rulare

```bash
# 1. Verificare PASTIS-R: integritate, statistici pentru data card, curbe NDVI pe clasă
python src/verify_pastis.py --root PASTIS-R --out outputs

# 2. Seria Sentinel-2 pe zona din România (necesită: earthengine authenticate)
python src/gee_export_s2_ro.py --aoi zona_ro.geojson --year 2024 --out RO_2024 --project <proiect-gcp> --no-tif   
python src/gee_export_s2_ro.py --aoi zona_ro.geojson --year 2024 --out RO_2024 --project <proiect-gcp>            
```

Ieșiri: `outputs/pastis_stats.json`, `outputs/ndvi_curves_fr.json`, `outputs/ndvi_per_clasa_fr.png`.

Split: cele 5 fold-uri spațiale oficiale PASTIS (configurația I: train 1–3, val 4, test 5). România e doar domeniu de test, plus fine-tuning pe k parcele.

Data card: `datacard_A7.md`.
