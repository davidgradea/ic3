"""Verificare pipeline PASTIS-R: integritate, statistici pentru data card, figura NDVI pe clasă.

Utilizare (din rădăcina repo-ului):
    python src/verify_pastis.py --root PASTIS-R --out outputs
    python src/verify_pastis.py --root PASTIS-R --out outputs --ndvi-patches 400
"""
import argparse
import collections
import json
import os
import sys
from datetime import date

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from pastis_data import COMMON, CLASSES, VOID, fold_split, load_patch, ndvi, read_metadata  # noqa: E402


def doy(d: date, season_start: date) -> int:
    """Zi din sezonul agricol (1 = 1 septembrie al primului an), ca să aliniem FR 2018–19 cu sezonul RO.
    Sezonul PASTIS ține 14 luni (sep. 2018 – oct. 2019), deci nu resetăm la 1 sep. 2019."""
    return (d - season_start).days + 1


CLOUD_B2 = 0.2      # reflectanță în albastru peste care pixelul e considerat nor (ca în Bonafilia et al., 2020)
MIN_CLEAR = 0.5     # o dată se folosește pentru o clasă doar dacă ≥ 50% din pixelii clasei sunt fără nori


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--ndvi-patches", type=int, default=300, help="câte patch-uri pentru curba NDVI")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    metas = read_metadata(a.root)
    ids = [str(m["ID_PATCH"]) for m in metas]

    # 1. Integritate: fiecare patch din metadate are S2, S1A, S1D, TARGET
    missing = collections.Counter()
    for pid in ids:
        for sub, pre in [("DATA_S2", "S2"), ("DATA_S1A", "S1A"), ("DATA_S1D", "S1D"), ("ANNOTATIONS", "TARGET")]:
            if not os.path.exists(os.path.join(a.root, sub, f"{pre}_{pid}.npy")):
                missing[sub] += 1
    extra = sorted({f[3:-4] for f in os.listdir(os.path.join(a.root, "DATA_S2"))} - set(ids))

    # 2. Statistici din metadate
    def n_dates(m, k):
        d = m[k]
        return len(d if isinstance(d, dict) else json.loads(d.replace("'", '"')))
    all_s2 = [v for m in metas for v in (m["dates-S2"] if isinstance(m["dates-S2"], dict) else json.loads(m["dates-S2"].replace("'", '"'))).values()]
    split = fold_split(metas, test_fold=5)  # configurația I: train 1-3, val 4, test 5
    stats = {
        "patches": len(metas),
        "patches_per_fold": dict(sorted(collections.Counter(int(m["Fold"]) for m in metas).items())),
        "patches_per_tile": dict(collections.Counter(m["TILE"] for m in metas)),
        "parcels_total": int(sum(int(m["N_Parcel"]) for m in metas)),
        "s2_period": [min(all_s2), max(all_s2)],
        "s2_dates_per_patch": [min(n_dates(m, "dates-S2") for m in metas), max(n_dates(m, "dates-S2") for m in metas)],
        "s1a_dates_per_patch": [min(n_dates(m, "dates-S1A") for m in metas), max(n_dates(m, "dates-S1A") for m in metas)],
        "s1d_dates_per_patch": [min(n_dates(m, "dates-S1D") for m in metas), max(n_dates(m, "dates-S1D") for m in metas)],
        "split_config_I": {k: len(v) for k, v in split.items()},
        "missing_files": dict(missing),
        "s2_without_annotation": len(extra),
    }

    # 3. Distribuția claselor pe pixeli (toate patch-urile) + goluri
    counts = np.zeros(20, dtype=np.int64)
    for pid in ids:
        lab = np.load(os.path.join(a.root, "ANNOTATIONS", f"TARGET_{pid}.npy"), mmap_mode="r")[0]
        counts += np.bincount(lab.ravel(), minlength=20)[:20]
    tot = counts.sum()
    stats["pixel_share_pct"] = {CLASSES[i]: round(100 * counts[i] / tot, 2) for i in range(20)}
    stats["void_pct"] = round(100 * counts[VOID] / tot, 2)
    stats["background_pct"] = round(100 * counts[0] / tot, 2)

    # 4. Curba NDVI pe clasă comună (subset aleator de patch-uri, NDVI mediu pe pixel per dată)
    rng = np.random.default_rng(a.seed)
    sub = rng.choice(len(metas), size=min(a.ndvi_patches, len(metas)), replace=False)
    groups = list(COMMON.items())
    acc = {g: collections.defaultdict(list) for g, _ in groups}
    s2_nan = 0
    n_obs = n_clear = 0
    for i in sub:
        p = load_patch(a.root, metas[i])
        nd = ndvi(p.s2)
        clear = p.s2[:, 0] < CLOUD_B2                     # (T, H, W)
        s2_nan += int(np.isnan(p.s2).sum())
        n_obs += clear.size; n_clear += int(clear.sum())
        start = date(p.s2_dates[0].year if p.s2_dates[0].month >= 9 else p.s2_dates[0].year - 1, 9, 1)
        for g, cls in groups:
            mask = np.isin(p.label, cls)
            if mask.sum() < 50:
                continue
            for t, d in enumerate(p.s2_dates):
                ok = clear[t][mask]
                if ok.mean() < MIN_CLEAR:
                    continue
                acc[g][doy(d, start) // 10].append(float(nd[t][mask][ok].mean()))   # agregare pe decade
    stats["ndvi_patches_used"] = int(len(sub))
    stats["s2_nan_values_in_subset"] = s2_nan
    stats["s2_cloudy_pixel_pct_in_subset"] = round(100 * (1 - n_clear / max(n_obs, 1)), 1)

    curves = {g: {int(k): (float(np.median(v)), len(v)) for k, v in sorted(acc[g].items()) if len(v) >= 5}
              for g, _ in groups}
    with open(os.path.join(a.out, "pastis_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    with open(os.path.join(a.out, "ndvi_curves_fr.json"), "w", encoding="utf-8") as f:
        json.dump(curves, f, indent=2, ensure_ascii=False)
    print(json.dumps(stats, indent=2, ensure_ascii=False))

    # 5. Figura
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    show = ["Cereale de toamnă", "Porumb", "Floarea-soarelui", "Rapiță", "Pajiști / furaje", "Soia"]
    colors = ["#C8702A", "#1B6F5A", "#D9A600", "#6B4FA0", "#7A8B99", "#B03A48"]
    fig, ax = plt.subplots(figsize=(10, 4))
    for g, c in zip(show, colors):
        cv = curves.get(g, {})
        if not cv:
            continue
        x = [k * 10 + 5 for k in cv]
        y = [v[0] for v in cv.values()]
        ax.plot(x, y, color=c, lw=2, label=g)
    months = ["sep", "oct", "nov", "dec", "ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct"]
    starts = [1, 31, 62, 92, 123, 154, 182, 213, 243, 274, 304, 335, 366, 396]
    ax.set_xticks(starts); ax.set_xticklabels(months)
    ax.set_xlim(1, 430); ax.set_ylim(0, 0.95)
    ax.set_ylabel("NDVI median (fără nori)"); ax.set_xlabel("sezonul agricol 2018–2019 (Franța, PASTIS-R)")
    ax.grid(alpha=.25); ax.legend(frameon=False, ncol=3, fontsize=9, loc="upper left")
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(a.out, "ndvi_per_clasa_fr.png"), dpi=150)
    print("Figura și statisticile salvate în", a.out)


if __name__ == "__main__":
    main()
