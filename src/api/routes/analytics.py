import csv, io, sqlite3
from datetime import date
from urllib.parse import quote
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from src.ai import anpr
from src.api.deps import page
from src.database import db_manager as db
from src.traffic import pkji_calculator as pkji_calc

router = APIRouter()
PKJI = db.PKJI

def overview_data():
    t = db.q("SELECT COUNT(*) c, COALESCE(AVG(CASE WHEN status!='macet' THEN speed END),0) a, SUM(status='speeding') v, SUM(status='watchlist') w FROM detections WHERE ts>=datetime('now','-24 hours','localtime')", one=True)
    return {"total": t["c"], "avg_speed": round(t["a"], 1), "violations": t["v"] or 0, "watchlist_hits": t["w"] or 0,
            "flow": db.q("SELECT strftime('%H:00',ts) h, COUNT(*) n, ROUND(AVG(CASE WHEN status!='macet' THEN speed END),1) s FROM detections WHERE ts>=datetime('now','-12 hours','localtime') GROUP BY h ORDER BY MIN(ts)"),
            "mix": db.q("SELECT pkji, COUNT(*) n FROM detections GROUP BY pkji"),
            "events": db.q("SELECT ts,camera,plate,pkji,speed,status FROM detections WHERE status IN ('speeding','watchlist') ORDER BY ts DESC LIMIT 8")}

def _filter(loc, job, days):
    """Potongan SQL untuk membatasi deteksi: kamera milik satu lokasi, satu job video, dan/atau N hari terakhir."""
    sql, args = "", []
    if loc:
        names = [c["name"] for c in db.q("SELECT name FROM cameras WHERE location_id=?", (loc,))]
        if not names: return " AND 0", []
        sql += " AND camera IN (" + ",".join("?" * len(names)) + ")"; args += names
    if job: sql += " AND src=?"; args.append(f"video:{job}")
    if days: sql += " AND ts>=datetime('now',?,'localtime')"; args.append(f"-{int(days)} days")
    return sql, args

def _res(counts, bydir, q15, q15dir, scale, cap_loc):
    """Analisis PKJI. Jalan terbagi + data arah ada -> tiap arah dianalisis terpisah; hasil utama = arah terburuk (D_J tertinggi)."""
    sc = lambda c: {k: v * scale for k, v in c.items()}
    if bydir and pkji_calc.is_divided(pkji_calc.settings_for(cap_loc)["road_type"]):
        per = pkji_calc.analyze_directions({d: sc(c) for d, c in bydir.items()}, q15dir, cap_loc)
        w = max(per, key=lambda d: per[d]["dj"])
        return {**per[w], "arah": w, "per_arah": {str(d): r for d, r in per.items()}}
    return pkji_calc.analyze(sc(counts), q15, cap_loc)

def corridor_data(loc=None, job=None, days=None):
    """Analitik koridor. `job` = hanya hasil satu video; `loc` = hanya kamera satu lokasi (parameter kapasitas ikut lokasi itu)."""
    cf, ca = _filter(loc, job, days); cap_loc = loc
    if job and not loc:  # job video: pakai parameter kapasitas lokasi kameranya
        r = db.q("SELECT c.location_id l FROM jobs j JOIN cameras c ON c.id=j.camera_id WHERE j.id=?", (job,), one=True); cap_loc = r["l"] if r else None
    heat = db.q("SELECT CAST(strftime('%w',ts) AS INT) d, CAST(strftime('%H',ts) AS INT) h, COUNT(*) n FROM detections WHERE 1=1" + cf + " GROUP BY d,h", ca)
    bins = [0] * 12  # histogram kecepatan tanpa status 'macet' (kecepatan < minimum valid tidak ikut statistik kecepatan)
    for r in db.q("SELECT MIN(CAST(speed/10 AS INT),11) b, COUNT(*) n FROM detections WHERE status!='macet'" + cf + " GROUP BY b", ca): bins[max(r["b"], 0)] = r["n"]
    out = {"heat": heat, "hist": {"labels": [f"{i*10}-{i*10+9}" for i in range(12)], "data": bins}, "peak": None}
    if job:  # satu video < 1 jam: arus = jumlah kendaraan / durasi video sebenarnya (bukan tebakan dari slot 15 menit)
        j = db.q("SELECT dur, started FROM jobs WHERE id=?", (job,), one=True)
        if j and j["dur"] and j["dur"] < 3600:
            counts, bydir = {}, {}
            for r in db.q("SELECT pkji, dir, COUNT(*) n FROM detections WHERE 1=1" + cf + " GROUP BY pkji, dir", ca):
                counts[r["pkji"]] = counts.get(r["pkji"], 0) + r["n"]
                if r["dir"] in (1, 2): bydir.setdefault(r["dir"], {})[r["pkji"]] = r["n"]
            if counts:
                res = _res(counts, bydir, [], {}, 3600 / j["dur"], cap_loc); res["phf"] = None  # PHF butuh >= 1 jam
                for p in res.get("per_arah", {}).values(): p["phf"] = None
                out["peak"] = {"hour": j["started"][:13].replace("T", " "), "volume": sum(counts.values()), "observed_min": round(j["dur"] / 60, 1), **res}
            return out
    # jam puncak = jam dengan ARUS (smp-setara jam) tertinggi, bukan jumlah mentah: jam yang baru terekam sebagian (klip video pendek) tidak boleh kalah/menang karena durasi
    hrs = db.q("SELECT strftime('%Y-%m-%d %H',ts) b, COUNT(*) n, COUNT(DISTINCT CAST(strftime('%M',ts) AS INT)/15) s FROM detections WHERE 1=1" + cf + " GROUP BY b", ca)
    if hrs:
        pk = max(hrs, key=lambda h: h["n"] * 4 / h["s"])
        rows = db.q("SELECT pkji, dir, CAST(strftime('%M',ts) AS INT)/15 k, COUNT(*) n FROM detections WHERE strftime('%Y-%m-%d %H',ts)=?" + cf + " GROUP BY pkji,dir,k", [pk["b"], *ca])
        counts, q15, bydir, q15dir = {}, [0] * 4, {}, {}
        for r in rows:
            counts[r["pkji"]] = counts.get(r["pkji"], 0) + r["n"]; q15[r["k"]] += r["n"]
            if r["dir"] in (1, 2):
                bydir.setdefault(r["dir"], {}); bydir[r["dir"]][r["pkji"]] = bydir[r["dir"]].get(r["pkji"], 0) + r["n"]
                q = q15dir.setdefault(r["dir"], [0] * 4); q[r["k"]] += r["n"]
        slots = pk["s"]; scale = 4 / slots  # data < 1 jam: arus diekstrapolasi ke per jam (kasar)
        res = _res(counts, bydir, q15, q15dir, scale, cap_loc)
        if slots < 4:  # PHF butuh 4 interval 15 menit penuh
            res["phf"] = None
            for p in res.get("per_arah", {}).values(): p["phf"] = None
        out["peak"] = {"hour": pk["b"], "volume": pk["n"], "observed_min": slots * 15, **res}
    return out

def query_logs(plate="", pkji="", day="", camera="", limit=None):
    sql, a = "SELECT * FROM detections WHERE 1=1", []
    for col, op, v in [("plate", "LIKE", f"%{plate}%" if plate else ""), ("pkji", "=", pkji), ("date(ts)", "=", day), ("camera", "=", camera)]:
        if v: sql += f" AND {col} {op} ?"; a.append(v)
    return db.q(sql + " ORDER BY ts DESC" + (f" LIMIT {int(limit)}" if limit else ""), a)

@router.get("/", response_class=HTMLResponse)
def overview(request: Request): return page(request, "overview.html", pkji=db.pkji_labels())

@router.get("/api/v1/overview")
def api_overview(): return overview_data()

@router.get("/logs", response_class=HTMLResponse)
def logs(request: Request, plate: str = "", pkji: str = "", date: str = ""):
    return page(request, "vehicle_logs.html", rows=query_logs(plate, pkji, date, limit=300), pkji=db.pkji_labels(), f={"plate": plate, "pkji": pkji, "date": date})

@router.get("/logs/export")
def export(plate: str = "", pkji: str = "", date: str = "", camera: str = ""):
    buf = io.StringIO(); w = csv.writer(buf); keys = ("id", "ts", "camera", "plate", "pkji", "speed", "status", "dir")
    w.writerow(keys)
    for r in query_logs(plate, pkji, date, camera): w.writerow([r[k] for k in keys])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=vehiscan_logs.csv"})

@router.get("/watchlist", response_class=HTMLResponse)
def watchlist(request: Request): return page(request, "watchlist.html", rows=db.q("SELECT * FROM watchlist ORDER BY id DESC"))

@router.post("/watchlist")
def wl_add(plate: str = Form(...), reason: str = Form(...)):
    p = anpr.normalize(plate) or " ".join(plate.upper().split())  # 'ab1234xy' -> 'AB 1234 XY'
    if not p: return RedirectResponse("/watchlist?bad=" + quote("Plat tidak boleh kosong"), 303)
    if db.q("SELECT 1 FROM watchlist WHERE plate=?", (p,), one=True): return RedirectResponse("/watchlist?bad=" + quote("Plat itu sudah ada di watchlist"), 303)
    db.q("INSERT INTO watchlist(plate,reason,added) VALUES(?,?,?)", (p, reason.strip(), str(date.today())), commit=True)
    return RedirectResponse("/watchlist?ok=" + quote("Plat ditambahkan"), 303)

@router.post("/watchlist/{i}/delete")
def wl_del(i: int):
    db.q("DELETE FROM watchlist WHERE id=?", (i,), commit=True); return RedirectResponse("/watchlist", 303)

@router.post("/watchlist/{i}/edit")
def wl_edit(i: int, plate: str = Form(...), reason: str = Form(...)):
    p = anpr.normalize(plate) or " ".join(plate.upper().split())
    if not p: return RedirectResponse("/watchlist?bad=" + quote("Plat tidak boleh kosong"), 303)
    try: db.q("UPDATE watchlist SET plate=?, reason=? WHERE id=?", (p, reason.strip(), i), commit=True)
    except sqlite3.IntegrityError: return RedirectResponse("/watchlist?bad=" + quote("Plat itu sudah ada di watchlist"), 303)
    return RedirectResponse("/watchlist?ok=" + quote("Perubahan disimpan"), 303)

@router.get("/corridor", response_class=HTMLResponse)
def corridor(request: Request):
    return page(request, "corridor.html", locs=db.q("SELECT id,name FROM locations ORDER BY name"),
                jobs=db.q("SELECT id,filename,started FROM jobs WHERE status='done' ORDER BY id DESC LIMIT 50"))

@router.get("/api/v1/corridor")
def api_corridor(location_id: int = 0, job_id: int = 0): return corridor_data(location_id or None, job_id or None)

@router.get("/reports", response_class=HTMLResponse)
def reports(request: Request): return page(request, "reports.html")

@router.get("/reports/generate")
def report(fmt: str = "xlsx", days: int = 7):
    rows = db.q("SELECT id,ts,camera,plate,pkji,speed,status FROM detections WHERE ts>=datetime('now',?,'localtime') ORDER BY ts DESC", (f"-{days} days",))
    mix = {}
    for r in rows: mix[r["pkji"]] = mix.get(r["pkji"], 0) + 1
    pk = corridor_data(days=days)["peak"] or {}
    summ = [("Periode (hari)", days), ("Total kendaraan", len(rows)), ("Pelanggaran kecepatan", sum(r["status"] == "speeding" for r in rows)),
            ("Hit watchlist", sum(r["status"] == "watchlist" for r in rows)), ("Jam puncak", pk.get("hour", "-")), ("D_J (derajat kejenuhan)", pk.get("dj", "-")), ("LOS", pk.get("los", "-")), ("PHF", pk.get("phf", "-"))] + [(f"Kelas {k}", v) for k, v in mix.items()]
    if fmt == "xlsx":
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active; ws.title = "Ringkasan"
        for s in summ: ws.append(list(s))
        w2 = wb.create_sheet("Deteksi"); w2.append(["id", "waktu", "kamera", "plat", "kelas", "km/jam", "status"])
        for r in rows: w2.append(list(r.values()))
        b = io.BytesIO(); wb.save(b)
        return Response(b.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=laporan.xlsx"})
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    b = io.BytesIO(); c = canvas.Canvas(b, pagesize=A4); y = 800
    c.setFont("Helvetica-Bold", 14); c.drawString(50, y, "Laporan VehiScan ITS"); c.setFont("Helvetica", 11)
    for k, v in summ: y -= 20; c.drawString(50, y, f"{k}: {v}")
    c.save()
    return Response(b.getvalue(), media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=laporan.pdf"})
