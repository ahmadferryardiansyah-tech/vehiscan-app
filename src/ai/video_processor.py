"""Analisis file video (MP4 rekaman/takeout) dengan pipeline yang sama dengan stream live."""
import json, os, shutil, subprocess, threading, time, traceback
from datetime import datetime, timedelta
from pathlib import Path
import cv2
import numpy as np
from src.ai import anpr
from src.ai.detector import cam_cal
from src.ai.speed_estimator import SpeedEstimator
from src.database import db_manager as db

ROOT = Path(__file__).resolve().parents[2]
BITRATE = [(2.5, 2.48), (4.5, 4.4), (6.5, 6.33), (999, 8.8)]  # megapiksel -> Mbps CBR (ARSA-CVS-001)

def inspect(path):
    """-> (info, errors, warnings). errors non-kosong = ditolak."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None, ["File tidak bisa dibuka (codec tidak didukung). Gunakan MP4 H.264."], []
    w, h, fps, n = int(cap.get(3)), int(cap.get(4)), cap.get(5) or 0, int(cap.get(7)); cap.release()
    if w <= 0 or h <= 0 or n <= 0 or fps <= 0:
        return None, ["Video kosong atau metadata rusak."], []
    dur = n / fps; mbps = os.path.getsize(path) * 8 / dur / 1e6; mp = w * h / 1e6; warn = []
    if w < 1280 or h < 720: warn.append(f"Resolusi {w}x{h} di bawah 1280x720 (disarankan ≥1920x1080): kelas kendaraan & plat sulit terbaca.")
    if fps < 15: warn.append(f"FPS {fps:.0f} terlalu rendah untuk estimasi kecepatan (disarankan ≥25).")
    elif fps < 25: warn.append(f"FPS {fps:.0f} di bawah 25: akurasi kecepatan menurun.")
    need = next(b for m, b in BITRATE if mp <= m)
    if mbps < need * .6: warn.append(f"Bitrate {mbps:.1f} Mbps jauh di bawah acuan {need} Mbps untuk resolusi ini: kompresi berat dapat merusak detail objek.")
    return {"w": w, "h": h, "fps": round(fps, 1), "frames": n, "dur": round(dur, 1), "mbps": round(mbps, 2)}, [], warn

def _set(job_id, **kw):
    db.q(f"UPDATE jobs SET {', '.join(k + '=?' for k in kw)} WHERE id=?", (*kw.values(), job_id), commit=True)

PREVIEW = {}  # job_id -> JPEG terakhir (pratinjau deteksi); hilang saat server restart

def _overlay(frame, tracks, plates, flash, est, cfg, i, total, ev):
    """Gambar garis A/B, area kalibrasi, kotak kendaraan (ID, kelas, plat, kecepatan) -> JPEG."""
    v = frame.copy(); h, w = v.shape[:2]; lw = max(2, w // 500); fs = w / 1600 + .4
    cv2.polylines(v, [np.int32(cfg["src"])], True, (211, 211, 34), lw)
    Hi = np.linalg.inv(est.H); W = cfg["dst"][1][0]
    for y, col in zip(est.lines, ((0, 165, 255), (60, 60, 240))):
        p = cv2.perspectiveTransform(np.float32([[[0, y], [W, y]]]), Hi)[0]
        cv2.line(v, tuple(map(int, p[0])), tuple(map(int, p[1])), col, lw * 2)
    for t in tracks:
        x1, y1, x2, y2 = t["bbox"]; f = flash.get(t["id"]); hot = bool(f and f[1] >= i)
        col = (0, 200, 0) if hot else (211, 211, 34)
        txt = f"{t['cls']} #{t['id']} {plates.label(t['id']) or (f[2] if hot and f[2] else '')}".strip() + (f" {f[0]:.0f} km/j" if hot else "")
        cv2.rectangle(v, (x1, y1), (x2, y2), col, lw)
        cv2.putText(v, txt, (x1, max(y1 - 8, 22)), cv2.FONT_HERSHEY_SIMPLEX, fs, col, lw)
    cv2.putText(v, f"frame {i}/{total}  event {ev}", (12, 30), cv2.FONT_HERSHEY_SIMPLEX, fs + .1, (255, 255, 255), lw)
    tw = min(w, 960); tw -= tw % 2; th = int(h * tw / w); th -= th % 2  # ukuran genap (syarat H.264 yuv420p)
    return cv2.resize(v, (tw, th)) if (tw, th) != (w, h) else v

REPLAYS = ROOT / "data" / "replays"

class Replay:
    """Tulis video hasil beranotasi (H.264/MP4, bisa diputar di browser) lewat ffmpeg dari paket imageio-ffmpeg.
    Kegagalan tidak menghentikan analisis, tetapi alasannya disimpan di `error` dan ditampilkan di catatan job.
    Pesan ffmpeg ditulis ke data/replays/job_N.ffmpeg.log (dihapus bila sukses). File final baru ada setelah valid."""
    def __init__(self, job_id, fps):
        self.fps, self.p, self.failed, self.error, self._logf = fps, None, False, None, None
        self.final, self.part = REPLAYS / f"job_{job_id}.mp4", REPLAYS / f"job_{job_id}.part.mp4"
        self.log = REPLAYS / f"job_{job_id}.ffmpeg.log"
        REPLAYS.mkdir(parents=True, exist_ok=True)
        for f in (self.final, self.part, self.log): f.unlink(missing_ok=True)

    @staticmethod
    def exe():
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return shutil.which("ffmpeg")

    def write(self, frame):
        if self.failed: return
        try:
            if self.p is None:
                exe = self.exe()
                if not exe:
                    self.failed = True; self.error = "ffmpeg tidak ditemukan (jalankan: python -m pip install imageio-ffmpeg)"; return
                h, w = frame.shape[:2]; self._logf = open(self.log, "wb")
                self.p = subprocess.Popen([exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                    "-framerate", f"{self.fps:.3f}", "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(self.part)],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self._logf, creationflags=0x08000000 if os.name == "nt" else 0)
            self.p.stdin.write(frame.tobytes())
        except Exception as e:
            self.failed = True; self.error = self.error or f"{type(e).__name__}: {e}"

    def _tail(self):
        try:
            lines = self.log.read_text(errors="replace").strip().splitlines()
            return lines[-1][:200] if lines else ""
        except OSError:
            return ""

    def close(self):
        p, self.p = self.p, None
        if not p: return
        try: p.stdin.close(); rc = p.wait(timeout=180)
        except Exception as e: p.kill(); rc = -1; self.error = self.error or f"{type(e).__name__}: {e}"
        if self._logf: self._logf.close(); self._logf = None
        if rc == 0 and self.part.exists():
            os.replace(self.part, self.final); self.log.unlink(missing_ok=True)
        else:
            self.part.unlink(missing_ok=True); self.error = f"ffmpeg gagal (kode {rc}): {self._tail() or self.error or 'tanpa pesan'}"

def _status(job_id):
    return db.q("SELECT status FROM jobs WHERE id=?", (job_id,), one=True)["status"]

_SLOT = threading.Semaphore(1)  # satu job aktif sekaligus: beberapa job paralel = beberapa model YOLO + encoder ffmpeg

def _log_error(job_id, tb):
    """Tampilkan traceback di terminal dan simpan ke data/errors.log (untuk diagnosis)."""
    print(f"[VehiScan] job {job_id} GAGAL:\n{tb}", flush=True)
    try:
        with open(ROOT / "data" / "errors.log", "a", encoding="utf-8") as f: f.write(f"--- job {job_id} {datetime.now():%Y-%m-%d %H:%M:%S}\n{tb}\n")
    except OSError: pass

def run_job(job_id, detector):
    job = db.q("SELECT message FROM jobs WHERE id=?", (job_id,), one=True)
    if not job: return  # job dihapus sebelum sempat jalan
    orig = job["message"] or ""
    if not _SLOT.acquire(blocking=False):  # beri tahu alasan menunggu, jangan membuat job terlihat macet
        _set(job_id, message=orig + " Menunggu giliran: ada job lain yang sedang diproses.")
        _SLOT.acquire()
    try:
        _set(job_id, message=orig)
        _run_job(job_id, detector)
    finally:
        _SLOT.release()

def _run_job(job_id, detector):
    job = db.q("SELECT * FROM jobs WHERE id=?", (job_id,), one=True); cap = rp = None
    if not job: return  # job dihapus saat masih mengantre
    base = job["message"] or ""
    try:
        if detector.ready: _set(job_id, message=base + " Memuat model AI…")
        det = detector.clone() if detector.ready else detector
        if not det.ready:
            raise RuntimeError("Model YOLO belum dimuat: pip install ultralytics, pastikan yolo11s.pt/yolo11_pkji.pt ada di root proyek, lalu Reload AI Engine di Settings.")
        cap = cv2.VideoCapture(job["path"]); fps = cap.get(5) or 25; total = max(int(cap.get(7)), 1)
        ok, first = cap.read()
        if not ok: raise RuntimeError("Frame pertama video tidak bisa dibaca (file rusak atau codec tidak didukung).")
        cfg = cam_cal(job["camera_id"], first.shape)
        if not cfg:
            raise RuntimeError(f"Kamera {job['camera_id']} belum dikalibrasi. Buka menu Calibration, kalibrasi kamera ini, lalu unggah ulang.")
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        cam = db.q("SELECT * FROM cameras WHERE id=?", (job["camera_id"],), one=True)
        if not cam: raise RuntimeError(f"Kamera {job['camera_id']} sudah dihapus dari menu Cameras.")
        est = SpeedEstimator(cfg, db.param("speed_min"), db.param("speed_max")); plates = anpr.new_tracker(); t0 = datetime.fromisoformat(job["started"]); flash = {}; rp = Replay(job_id, fps / job["stride"])
        if _status(job_id) == "cancelling":
            _set(job_id, status="cancelled", message=base + " Dibatalkan."); return
        _set(job_id, status="processing", message=base); i = ev = done = 0; cancelled = False; t_start = time.time()
        while True:
            ok, frame = cap.read()
            if not ok: break
            i += 1
            if (i - 1) % job["stride"]: continue
            _, tracks = det.process(frame, job["camera_id"]); done += 1; t = i / fps
            for tr in tracks:
                x1, y1, x2, y2 = tr["bbox"]; plates.observe(frame, tr["id"], tr["bbox"])
                res = est.update(tr["id"], ((x1 + x2) / 2, y2), t)
                if res is not None:
                    sp, arah = res
                    plate = plates.plate(tr["id"])
                    db.log_detection(cam["name"], plate or "TIDAK TERBACA", tr["cls"], sp,
                                     ts=(t0 + timedelta(seconds=t)).strftime("%Y-%m-%d %H:%M:%S"), src=f"video:{job_id}", direction=arah)
                    flash[tr["id"]] = (sp, i + int(2 * fps), plate or plates.label(tr["id"]))
                    ev += 1
            vis = _overlay(frame, tracks, plates, flash, est, cfg, i, total, ev); rp.write(vis)
            if done % 3 == 1:  # pratinjau cukup tiap 3 frame; encode JPEG tiap frame memboroskan CPU
                PREVIEW[job_id] = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 72])[1].tobytes()
                for k in sorted(PREVIEW)[:-10]: PREVIEW.pop(k, None)
            if len(flash) > 200: flash = {k: v for k, v in flash.items() if v[1] >= i}
            if done % 15 == 0:
                left = (time.time() - t_start) / max(i, 1) * max(total - i, 0)
                _set(job_id, progress=round(i / total * 100, 1), frames=i, events=ev, message=base + f" Sisa ±{left / 60:.1f} menit.")
                if _status(job_id) == "cancelling": cancelled = True; break
        rp.close()
        note = f" ⚠ Replay tidak dibuat: {rp.error}" if rp.error else ""
        if cancelled:
            _set(job_id, status="cancelled", frames=i, events=ev, message=base + " Dibatalkan." + note); return
        msg = "Selesai." if ev else "Selesai, tetapi tidak ada kendaraan yang melewati garis A dan B. Periksa kalibrasi di menu Calibration."
        _set(job_id, status="done", progress=100, frames=i, events=ev, message=base + " " + msg + note)
    except Exception as e:
        _log_error(job_id, traceback.format_exc())
        _set(job_id, status="failed", message=f"{type(e).__name__}: {e}  (detail: data/errors.log)")
    finally:
        if rp: rp.close()
        if cap: cap.release()

def start(job_id, detector):
    threading.Thread(target=run_job, args=(job_id, detector), daemon=True).start()
