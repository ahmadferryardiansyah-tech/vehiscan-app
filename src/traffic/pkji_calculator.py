"""Kapasitas, emp dinamis, dan Derajat Kejenuhan (D_J) menurut PKJI 2023 (Jalan Perkotaan).

    C   = C0 x F_CLJ x F_CPA x F_CHS x F_CUK      [smp/jam]
    D_J = Q_smp / C

- Jalan tak terbagi (2/2-TT): dianalisis dua arah sekaligus.
- Jalan terbagi (4/2-T, 6/2-T): dianalisis PER ARAH; C0 per lajur x jumlah lajur satu arah.
Tabel acuan: configs/pkji_2023.json. Parameter lokasi: tabel locations; bila kosong dipakai default halaman Parameter.
"""
import json
from pathlib import Path
from src.database import db_manager as db

CFG = Path(__file__).resolve().parents[2] / "configs" / "pkji_2023.json"
DJ_LIMIT = 0.85  # D_J di atas ini = jenuh / tidak laik (ditandai merah di UI)

def cfg():
    return json.loads(CFG.read_text(encoding="utf-8"))["pkji_2023_config"]

# ---------------------------------------------------------------- tipe jalan
def norm_type(t):
    return str(t or "2/2-TT").upper().replace(" ", "-")

def is_divided(t):
    return not norm_type(t).endswith("-TT")

def lanes_of(t):
    return int(norm_type(t).split("/")[0])

def _interp(points, x):
    """Interpolasi linear antar titik tabel {x: y}; di luar rentang dibatasi ke ujung tabel."""
    pts = sorted((float(k), v) for k, v in points.items())
    if x <= pts[0][0]: return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1: return round(y0 + (y1 - y0) * (x - x0) / (x1 - x0), 4)
    return pts[-1][1]

# ---------------------------------------------------------------- emp dinamis
def emp_for(road_type, q_total, width_m, lanes=1):
    """emp per kelas. Tak terbagi: Q = total dua arah (kend/jam), lebar jalur (m).
    Terbagi: Q dibagi jumlah lajur satu arah (kend/jam/lajur). -> (dict emp, keterangan baris tabel)."""
    r = cfg()["dynamic_emp_rules"]
    if is_divided(road_type):
        t = r["road_type_divided"]; ql = q_total / max(lanes, 1); low = ql < t["threshold_q_per_lane"]
        e = dict(t["emp_table"]["Q_below_1050" if low else "Q_above_1050"])
        return e, f"terbagi, Q/lajur = {ql:.0f} {'<' if low else '>='} {t['threshold_q_per_lane']} kend/jam"
    t = r["road_type_2_2_TT"]; low = q_total < t["low_volume_threshold_q"]
    tbl = t["emp_table"]["Q_below_1800" if low else "Q_above_1800"]
    narrow = width_m <= t["narrow_lane_max_width_m"]
    e = {k: v for k, v in tbl.items() if not k.startswith("SM_")}
    e["SM"] = tbl["SM_narrow_lane" if narrow else "SM_wide_lane"]
    return e, f"2/2-TT, Q {'<' if low else '>='} {t['low_volume_threshold_q']} kend/jam, lebar jalur {'<=' if narrow else '>'} {t['narrow_lane_max_width_m']:g} m"

# ---------------------------------------------------------------- faktor kapasitas
def f_clj(road_type, lane_width, lanes):
    """Tak terbagi: tabel menurut LEBAR JALUR dua arah (lebar lajur x jumlah lajur). Terbagi: menurut lebar lajur."""
    t = cfg()["capacity_factors_lookup"]
    if is_divided(road_type): return _interp(t["F_CLJ_per_lajur_terbagi"], lane_width)
    return _interp(t["F_CLJ_lebar_jalur_2_2_TT"], lane_width * lanes)

def f_cpa(split, divided):
    """Pemisahan arah hanya berlaku untuk jalan tak terbagi (terbagi = 1,00)."""
    return 1.0 if divided else cfg()["capacity_factors_lookup"]["F_CPA"][split]

def f_cuk(pop):
    t = cfg()["capacity_factors_lookup"]["F_CUK"]
    if pop < 0.1: return t["lt_0.1M"]
    if pop < 0.5: return t["0.1M_0.5M"]
    if pop < 1.0: return t["0.5M_1.0M"]
    if pop <= 3.0: return t["1.0M_3.0M"]
    return t["gt_3.0M"]

def f_chs(s):
    """F_CHS: nilai manual bila diisi (> 0); selain itu otomatis dari KHS + lebar bahu (hanya 2/2-TT berbahu).
    -> (nilai, catatan)."""
    if s.get("f_chs"): return s["f_chs"], "manual"
    if is_divided(s["road_type"]): return 1.0, "jalan terbagi: tabel belum ada, dipakai 1,00 (isi F_CHS manual)"
    t = cfg()["capacity_factors_lookup"]["F_CHS_2_2_TT_bahu"]
    return t[s["khs"]][str(s["lbe"])], f"tabel 2/2-TT berbahu: KHS {s['khs']}, bahu {s['lbe']} m"

# ---------------------------------------------------------------- parameter efektif
def settings_for(loc_id=None):
    """Parameter efektif: nilai khusus lokasi bila diisi, selain itu default halaman Parameter."""
    row = db.q("SELECT road_type,lanes,lane_w,split,pop,f_chs,khs,lbe FROM locations WHERE id=?", (loc_id,), one=True) if loc_id else None
    g = lambda col, key: row[col] if row and row[col] is not None else db.param(key)
    rt = norm_type(row["road_type"] if row and row["road_type"] else db.param("road_type"))
    lanes = int(row["lanes"]) if row and row["lanes"] else lanes_of(rt)
    return {"road_type": rt, "lanes": lanes, "lane_width": g("lane_w", "lane_width"), "split": g("split", "split"),
            "city_pop": g("pop", "city_pop"), "f_chs": g("f_chs", "f_chs"), "khs": g("khs", "khs"), "lbe": g("lbe", "lbe"),
            "los": [db.param(f"los_{x}") for x in "abcde"]}

# ---------------------------------------------------------------- perhitungan murni (tanpa database)
def capacity(s, lanes=None):
    """C [smp/jam]. Terbagi: C0 per lajur x jumlah lajur ANALISIS (satu arah bila per arah). 2/2-TT: total dua arah."""
    c0 = cfg()["capacity_factors_lookup"]["base_capacity_C0"][s["road_type"]]
    div = is_divided(s["road_type"]); n = (lanes or s["lanes"]) if div else 1
    chs, chs_note = f_chs(s)
    fs = {"F_CLJ": f_clj(s["road_type"], s["lane_width"], s["lanes"]), "F_CPA": f_cpa(s["split"], div), "F_CHS": chs, "F_CUK": f_cuk(s["city_pop"])}
    c = c0 * n
    for v in fs.values(): c *= v
    return c, {"C0": c0, "n_lajur": n, **fs, "catatan_F_CHS": chs_note}

def los(dj, limits):
    for lim, l in zip(limits, "ABCDE"):
        if dj <= lim: return l
    return "F"

def phf(q15):
    """Peak Hour Factor = V_jam / (4 x V_15menit_puncak)."""
    return round(sum(q15) / (4 * max(q15)), 2) if q15 and max(q15) else 0

def compute(counts, q15, s, lanes=None):
    """counts = {kelas: kend/jam}. lanes = jumlah lajur yang dianalisis (jalan terbagi per arah: lajur satu arah).
    -> hasil + rincian langkah (dipakai halaman Corridor & contoh perhitungan manual)."""
    div = is_divided(s["road_type"]); n = (lanes or s["lanes"]) if div else s["lanes"]
    q_total = sum(counts.values()); width = s["lane_width"] * s["lanes"]
    emp, band = emp_for(s["road_type"], q_total, width, n)
    smp = {k: emp.get(k, 1.0) * v for k, v in counts.items()}; v = sum(smp.values())
    c, f = capacity(s, n); dj = v / c if c else 0
    return {"smp_jam": round(v, 1), "capacity": round(c), "dj": round(dj, 3), "los": los(dj, s["los"]), "phf": phf(q15), "laik": dj <= DJ_LIMIT,
            "detail": {"q_total": round(q_total, 1), "lebar_jalur": round(width, 2), "baris_emp": band, "emp": emp,
                       "smp_per_kelas": {k: round(x, 2) for k, x in smp.items()}, "faktor": f, "road_type": s["road_type"]}}

def analyze(counts, q15, loc_id=None):
    return compute(counts, q15, settings_for(loc_id))

def analyze_directions(by_dir, q15_by_dir, loc_id=None):
    """Jalan terbagi: analisis terpisah tiap arah. by_dir = {arah: {kelas: kend/jam}}. -> {arah: hasil}."""
    s = settings_for(loc_id); n = max(1, s["lanes"] // 2)
    return {d: compute(c, q15_by_dir.get(d, []), s, lanes=n) for d, c in sorted(by_dir.items())}
