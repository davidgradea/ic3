"""Încărcare PASTIS-R pentru proiectul IC3 · A7 (PASTIS-R → România).

Structura așteptată (arhiva PASTIS-R.zip de pe Zenodo, dezarhivată):
    PASTIS_ROOT/metadata.geojson
    PASTIS_ROOT/DATA_S2/S2_<id>.npy        (T, 10, 128, 128) int16, reflectanță ×10⁴
    PASTIS_ROOT/DATA_S1A/S1A_<id>.npy      (T, 3, 128, 128) float16, [VV, VH, VV/VH] în dB (orbită ascendentă)
    PASTIS_ROOT/DATA_S1D/S1D_<id>.npy      idem, orbită descendentă
    PASTIS_ROOT/ANNOTATIONS/TARGET_<id>.npy (3, 128, 128) uint8; canalul 0 = clasa semantică
    PASTIS_ROOT/NORM_S2_patch.json          media / deviația standard pe fold

Lista de patch-uri se ia din metadata.geojson (2.433), NU din folder: în DATA_S2 există
fișiere suplimentare fără adnotări.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date

import numpy as np

# Ordinea benzilor S2 în PASTIS
S2_BANDS = ["B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12"]
S1_BANDS = ["VV", "VH", "VV/VH"]

# Nomenclatura PASTIS (Sainte Fare Garnot & Landrieu, 2021)
CLASSES = {
    0: "Fundal", 1: "Pajiște", 2: "Grâu moale de toamnă", 3: "Porumb", 4: "Orz de toamnă",
    5: "Rapiță de toamnă", 6: "Orz de primăvară", 7: "Floarea-soarelui", 8: "Viță-de-vie",
    9: "Sfeclă", 10: "Triticale de toamnă", 11: "Grâu dur de toamnă", 12: "Legume, fructe, flori",
    13: "Cartofi", 14: "Leguminoase furajere", 15: "Soia", 16: "Livadă", 17: "Cereale amestec",
    18: "Sorg", 19: "Void (ignorat)",
}
VOID = 19

# Taxonomie comună FR ↔ RO (propunere pentru transfer; se rafinează la CP2)
COMMON = {
    "Cereale de toamnă": [2, 4, 10, 11, 17],
    "Cereale de primăvară": [6],
    "Porumb": [3],
    "Floarea-soarelui": [7],
    "Rapiță": [5],
    "Soia": [15],
    "Pajiști / furaje": [1, 14],
    "Plante prășitoare": [9, 13, 18],
    "Permanente (vie, livadă)": [8, 16],
    "Legume": [12],
}


@dataclass
class Patch:
    pid: str
    fold: int
    tile: str
    s2: np.ndarray              # (T, 10, H, W) float32, reflectanță [0, 1]
    s2_dates: list[date]
    label: np.ndarray           # (H, W) uint8, 0..19
    s1a: np.ndarray | None = None
    s1d: np.ndarray | None = None
    s1a_dates: list[date] | None = None
    s1d_dates: list[date] | None = None


def _dates(d) -> list[date]:
    if isinstance(d, str):
        d = json.loads(d.replace("'", '"'))
    vals = [d[k] for k in sorted(d, key=int)]
    return [date(int(str(v)[:4]), int(str(v)[4:6]), int(str(v)[6:8])) for v in vals]


def read_metadata(root: str) -> list[dict]:
    with open(os.path.join(root, "metadata.geojson")) as f:
        feats = json.load(f)["features"]
    return [f["properties"] for f in feats]


def load_patch(root: str, meta: dict, with_s1: bool = False) -> Patch:
    pid = str(meta["ID_PATCH"])
    s2 = np.load(os.path.join(root, "DATA_S2", f"S2_{pid}.npy")).astype(np.float32) / 1e4
    label = np.load(os.path.join(root, "ANNOTATIONS", f"TARGET_{pid}.npy"))[0]
    p = Patch(pid, int(meta["Fold"]), meta["TILE"], s2, _dates(meta["dates-S2"]), label)
    if with_s1:
        p.s1a = np.load(os.path.join(root, "DATA_S1A", f"S1A_{pid}.npy")).astype(np.float32)
        p.s1d = np.load(os.path.join(root, "DATA_S1D", f"S1D_{pid}.npy")).astype(np.float32)
        p.s1a_dates, p.s1d_dates = _dates(meta["dates-S1A"]), _dates(meta["dates-S1D"])
    return p


def fold_split(metas: list[dict], test_fold: int = 1) -> dict[str, list[dict]]:
    """Split-ul oficial PASTIS: fold-urile sunt grupate spațial (patch-urile vecine în același fold).
    Configurația I din Garnot & Landrieu (2021): train = 1,2,3 · val = 4 · test = 5; rotim cu test_fold."""
    order = [(test_fold + k - 1) % 5 + 1 for k in range(5)]  # test_fold = 5 -> [5,1,2,3,4]
    test, val, train = order[0], order[4], order[1:4]
    return {
        "train": [m for m in metas if int(m["Fold"]) in train],
        "val": [m for m in metas if int(m["Fold"]) == val],
        "test": [m for m in metas if int(m["Fold"]) == test],
    }


def ndvi(s2: np.ndarray) -> np.ndarray:
    """NDVI = (B8 − B4) / (B8 + B4) pe fiecare dată: (T, H, W)."""
    b4, b8 = s2[:, 2], s2[:, 6]
    return (b8 - b4) / np.clip(b8 + b4, 1e-6, None)


def to_common(label: np.ndarray) -> np.ndarray:
    """Etichete PASTIS → indice în taxonomia comună (−1 = fundal / void)."""
    out = np.full(label.shape, -1, dtype=np.int16)
    for i, ids in enumerate(COMMON.values()):
        out[np.isin(label, ids)] = i
    return out
