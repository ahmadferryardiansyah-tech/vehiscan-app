"""Perhitungan manual PKJI 2023 langkah demi langkah dari keluaran deteksi aplikasi.

Tanpa argumen          : contoh jalan 2/2-TT (log 10 menit, 187 kendaraan), sama dengan PERHITUNGAN_MANUAL.md.
--contoh terbagi       : contoh jalan 4/2-T dianalisis per arah.
Dengan data Anda       : Vehicle Logs -> Export CSV, lalu
    python scripts/contoh_perhitungan_manual.py data.csv --durasi 600 --lokasi 2
    --durasi  lama rekaman (detik); bawaan: selisih waktu deteksi pertama dan terakhir
    --lokasi  id lokasi untuk parameter kapasitas; bawaan: default halaman Parameter
"""
import argparse, csv, sys
from collections import Counter
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.database import db_manager as db
from src.traffic import pkji_calculator as calc

LOS = [.2, .44, .74, .85, 1.0]
S_TT = {"road_type": "2/2-TT", "lanes": 2, "lane_width": 3.5, "split": "50-50", "city_pop": 0.85, "f_chs": 0, "khs": "LO", "lbe": "2.0", "los": LOS}
S_T = {**S_TT, "road_type": "4/2-T", "lanes": 4}
CONTOH_TT = {None: {"SM": 103, "MP": 68, "KS": 9, "LB": 2, "LT": 5}}
CONTOH_T = {1: {"SM": 60, "MP": 40, "KS": 5, "LB": 1, "LT": 3}, 2: {"SM": 100, "MP": 85, "KS": 8, "LB": 2, "LT": 5}}

def kecepatan(jarak_m, dt_s):
    return jarak_m / dt_s * 3.6  # km/jam

def baca_csv(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    g = {}
    for r in rows:
        d = int(r["dir"]) if r.get("dir") else None
        g.setdefault(d, Counter())[db.LEGACY.get(r["pkji"], r["pkji"])] += 1
    ts = sorted(datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S") for r in rows)
    return {d: dict(c) for d, c in g.items()}, (ts[-1] - ts[0]).total_seconds() if len(ts) > 1 else 0

def tampil(judul, counts, dur, s, lanes=None):
    f = 3600 / dur; n = sum(counts.values()); q = {k: v * f for k, v in counts.items()}
    r = calc.compute(q, [], s, lanes); d = r["detail"]; fk = d["faktor"]
    print(f"\n=== {judul} ===")
    print(f"1. Hitung per kelas: {n} kendaraan dalam {dur:g} detik   2. Faktor ke per jam = 3600 / {dur:g} = {f:g}")
    for k, v in counts.items(): print(f"     {k}: {v} x {f:g} = {q[k]:g} kend/jam")
    print(f"     Q total = {d['q_total']:g} kend/jam")
    print(f"3. Baris emp: {d['baris_emp']}  (lebar jalur {s['lane_width']:g} x {s['lanes']} = {d['lebar_jalur']:g} m)")
    print("4. Q_smp = sum(emp x Q)")
    for k, x in q.items(): print(f"     {k}: {d['emp'][k]} x {x:g} = {d['smp_per_kelas'][k]:g}")
    print(f"     Q_smp = {r['smp_jam']} smp/jam")
    nl = f" x {fk['n_lajur']} lajur" if fk["n_lajur"] > 1 else ""
    print(f"5. C = C0{nl} x F_CLJ x F_CPA x F_CHS x F_CUK = {fk['C0']}{nl} x {fk['F_CLJ']} x {fk['F_CPA']} x {fk['F_CHS']} x {fk['F_CUK']} = {r['capacity']} smp/jam")
    print(f"     (F_CHS: {fk['catatan_F_CHS']})")
    print(f"6. D_J = {r['smp_jam']} / {r['capacity']} = {r['dj']}   7. LOS {r['los']}  ({'LAIK' if r['laik'] else 'JENUH / TIDAK LAIK'}, batas {calc.DJ_LIMIT})")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("csv", nargs="?"); ap.add_argument("--durasi", type=float); ap.add_argument("--lokasi", type=int); ap.add_argument("--contoh", choices=["tt", "terbagi"], default="tt")
    a = ap.parse_args()
    if a.csv: groups, dur = baca_csv(a.csv); dur = a.durasi or dur; s = calc.settings_for(a.lokasi)
    else: groups, dur, s = (CONTOH_T, 600, S_T) if a.contoh == "terbagi" else (CONTOH_TT, 600, S_TT); dur = a.durasi or dur
    if not dur: sys.exit("Durasi rekaman tidak diketahui: beri --durasi (detik).")
    if calc.is_divided(s["road_type"]) and any(d in (1, 2) for d in groups):
        for d in (1, 2):
            if d in groups: tampil(f"Arah {d} ({s['road_type']}, {s['lanes'] // 2} lajur satu arah)", groups[d], dur, s, max(1, s["lanes"] // 2))
    else:
        tampil(f"Dua arah ({s['road_type']})", {k: sum(g.get(k, 0) for g in groups.values()) for k in db.PKJI if any(k in g for g in groups.values())}, dur, s)
    print("\nPHF: tidak dihitung (butuh rekaman >= 1 jam dengan 4 interval 15 menit)")
    lim = db.param if a.csv else db.default
    print(f"Kecepatan contoh: 15 m / 1,08 s x 3,6 = {kecepatan(15, 1.08):.1f} km/jam. Di bawah {lim('speed_min'):g} km/jam = status 'macet' (tetap dihitung volume, keluar dari statistik kecepatan); di atas {lim('speed_max'):g} = dibuang.")

if __name__ == "__main__":
    main()
