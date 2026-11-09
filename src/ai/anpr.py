"""ANPR plat Indonesia: (opsional detektor plat YOLO) + RapidOCR + normalisasi 'AB 1234 XY'."""
import re
import cv2
from src.ai.detector import ROOT, model_cfg
from src.database import db_manager as db

PLATE = re.compile(r"^([A-Z]{1,2})(\d{1,4})([A-Z]{1,3})$")
TO_L = {"0": "O", "1": "I", "8": "B", "5": "S", "2": "Z"}
TO_D = {"O": "0", "I": "1", "B": "8", "S": "5", "Z": "2", "Q": "0", "D": "0"}

def normalize(raw):
    """Teks OCR -> 'AB 1234 XY' (koreksi huruf/angka yang tertukar), None bila bukan format plat."""
    s = re.sub(r"[^A-Z0-9]", "", raw.upper()); m = PLATE.match(s)
    if m: return " ".join(m.groups())
    best = None
    for pl in (2, 1):
        for sl in (3, 2, 1):
            mid = s[pl:len(s) - sl]
            if len(s) < pl + sl + 1 or not 1 <= len(mid) <= 4: continue
            pre = "".join(TO_L.get(c, c) for c in s[:pl]); suf = "".join(TO_L.get(c, c) for c in s[len(s) - sl:])
            d = "".join(TO_D.get(c, c) for c in mid)
            if pre.isalpha() and suf.isalpha() and d.isdigit():
                cost = sum(a != b for a, b in zip(s, pre + d + suf))  # jumlah karakter yang harus dikoreksi
                if best is None or cost < best[0]: best = (cost, f"{pre} {d} {suf}")
    return best[1] if best else None

class PlateReader:
    def __init__(self):
        self.ocr = self.det = None; self.msg = "belum dimuat"; self.load()

    @property
    def ready(self): return self.ocr is not None

    def load(self):
        try:
            try: from rapidocr_onnxruntime import RapidOCR
            except ImportError: from rapidocr import RapidOCR
            self.ocr = RapidOCR(); self.msg = "ANPR aktif (RapidOCR)"
        except Exception as e:
            self.ocr = None; self.msg = f"ANPR nonaktif: {e}. Jalankan: pip install rapidocr-onnxruntime"; return False
        wp = ROOT / "yolo11_plate.pt"  # opsional: detektor plat khusus, meningkatkan akurasi
        if wp.exists():
            try:
                from ultralytics import YOLO
                self.det = YOLO(str(wp)); self.msg += " + detektor plat yolo11_plate.pt"
            except Exception: self.det = None
        return True

    def _plate_crop(self, crop):
        b = self.det.predict(crop, verbose=False, conf=.3)[0].boxes
        if b is None or not len(b): return None
        x1, y1, x2, y2 = map(int, b.xyxy[int(b.conf.argmax())].tolist()); p = 4
        return crop[max(y1 - p, 0):y2 + p, max(x1 - p, 0):x2 + p]

    def _ocr(self, img):
        out = self.ocr(img)
        if isinstance(out, tuple): items = [(t, float(s)) for _, t, s in (out[0] or [])]
        else: items = list(zip(out.txts or [], [float(x) for x in (out.scores or [])]))
        cands = [[i] for i in items] + ([items] if len(items) > 1 else []) + ([items[:2]] if len(items) > 2 else [])
        best = (None, 0.0)
        for c in cands:
            p = normalize("".join(t for t, _ in c))
            if p:
                sc = sum(s for _, s in c) / len(c)
                if sc > best[1]: best = (p, sc)
        return best

    def read(self, img, bbox=None):
        """-> (plat|None, skor). bbox = kendaraan (plat dicari di 60% bagian bawah); tanpa bbox = gambar utuh."""
        if not self.ready: return None, 0.0
        if bbox:
            x1, y1, x2, y2 = map(int, bbox); crop = img[max(y1 + int((y2 - y1) * .4), 0):max(y2, 0), max(x1, 0):max(x2, 0)]
        else: crop = img
        if crop.size == 0: return None, 0.0
        if self.det is not None:
            pc = self._plate_crop(crop)
            if pc is not None and pc.size: crop = pc
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY); sc = min(4.0, max(1.0, 320 / g.shape[1]))
        if sc > 1: g = cv2.resize(g, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC)
        g = cv2.createCLAHE(2.0, (8, 8)).apply(g)
        m = max(12, g.shape[0] // 5); g = cv2.copyMakeBorder(g, m, m, m, m, cv2.BORDER_REPLICATE)  # margin: detektor teks butuh ruang di tepi
        return self._ocr(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR))

_reader = None
def get_reader():
    global _reader
    if _reader is None: _reader = PlateReader()
    return _reader

class PlateTracker:
    """OCR hemat: tiap N frame per kendaraan, simpan hasil terbaik, berhenti bila skor >= 0.9 atau percobaan habis."""
    def __init__(self, reader, thr, every=4, max_tries=10, min_vehicle_width=60):
        self.r, self.thr, self.every, self.max, self.minw = reader, thr, every, max_tries, min_vehicle_width
        self.best, self.n, self.tries = {}, {}, {}

    def observe(self, frame, tid, bbox):
        if bbox[2] - bbox[0] < self.minw or not self.r.ready: return
        self.n[tid] = self.n.get(tid, 0) + 1
        b = self.best.get(tid)
        if self.n[tid] % self.every or (b and b[1] >= .9) or self.tries.get(tid, 0) >= self.max: return
        self.tries[tid] = self.tries.get(tid, 0) + 1
        p, s = self.r.read(frame, bbox)
        if p and (not b or s > b[1]): self.best[tid] = (p, s)

    def label(self, tid):
        b = self.best.get(tid); return b[0] if b else None

    def plate(self, tid):
        b = self.best.get(tid); return b[0] if b and b[1] >= self.thr else None

    def forget(self, tid):
        for d in (self.best, self.n, self.tries): d.pop(tid, None)

def new_tracker():
    return PlateTracker(get_reader(), float(db.param("anpr_conf")), **model_cfg()["plate"])
