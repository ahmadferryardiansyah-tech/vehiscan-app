"""YOLO11 + ByteTrack + ROI masking. Bobot custom PKJI diprioritaskan; fallback COCO -> PKJI."""
import json
from pathlib import Path
import cv2, numpy as np, yaml

from src.database import db_manager as db

ROOT = Path(__file__).resolve().parents[2]
PKJI_CODES = {"SM", "MP", "KS", "LB", "LT"}  # kode PKJI 2023
LEGACY = {"KB": "LT", "BB": "LB"}  # bobot lama (training dengan nama KB/BB) tetap bisa dipakai
_cal = {"mtime": 0, "data": {}}

def model_cfg():
    """model.yaml sebagai default, ditimpa parameter dari halaman Parameter (database)."""
    c = yaml.safe_load((ROOT / "configs" / "model.yaml").read_text())
    c.update(conf=db.param("conf"), iou=db.param("iou"), imgsz=db.param("imgsz"), device=db.param("device"), half=bool(db.param("half")))
    c["plate"] = {"every": db.param("plate_every"), "max_tries": db.param("plate_max_tries"), "min_vehicle_width": db.param("plate_min_width")}
    return c

def get_cal():
    """calibration.json dibaca ulang otomatis saat file berubah (mis. setelah simpan dari halaman Calibration)."""
    p = ROOT / "configs" / "calibration.json"; m = p.stat().st_mtime
    if m != _cal["mtime"]: _cal.update(mtime=m, data=json.loads(p.read_text()))
    return _cal["data"]

def cam_cal(cam_id, shape=None):
    """Kalibrasi kamera, titik di-skala bila resolusi frame berbeda dari frame saat kalibrasi."""
    cfg = get_cal().get("cameras", {}).get(str(cam_id))
    if not cfg: return None
    fr = cfg.get("frame")
    if shape is not None and fr and (shape[1], shape[0]) != tuple(fr):
        sx, sy = shape[1] / fr[0], shape[0] / fr[1]
        cfg = {**cfg, "src": [[x * sx, y * sy] for x, y in cfg["src"]], "roi": [[x * sx, y * sy] for x, y in cfg.get("roi", [])]}
    return cfg

class VehicleDetector:
    def __init__(self, autoload=True):
        self.model = None; self.msg = "belum dimuat"; self.cfg = {}; self.tracker_path = str(ROOT / "configs" / "tracker.yaml")
        if autoload: self.load()

    @property
    def ready(self): return self.model is not None

    def clone(self):
        """Instance baru dengan model & tracker sendiri (analisis video tidak bentrok dengan stream live)."""
        return VehicleDetector()

    def _write_tracker(self):
        tk = yaml.safe_load((ROOT / "configs" / "tracker.yaml").read_text())
        for k in ("track_buffer", "match_thresh", "track_high_thresh"): tk[k] = db.param(k)
        p = ROOT / "data" / "tracker.run.yaml"; p.parent.mkdir(exist_ok=True); p.write_text(yaml.safe_dump(tk)); self.tracker_path = str(p)

    def load(self):
        """Dipanggil saat startup dan tombol 'Reload AI Engine'."""
        try:
            import torch
            from ultralytics import YOLO
            self.cfg = cfg = model_cfg(); self._write_tracker(); model = used = None
            for name in cfg["weights"]:
                p = ROOT / name
                if p.exists(): model, used = YOLO(str(p)), name; break
                if "pkji" not in name:  # bobot standar: ultralytics mengunduh otomatis bila ada internet
                    try: model, used = YOLO(name), name; break
                    except Exception: continue
            if model is None: raise FileNotFoundError("tidak ada bobot (yolo11_pkji.pt / yolo11s.pt)")
            cuda = torch.cuda.is_available()
            self.device = (0 if cuda else "cpu") if cfg["device"] == "auto" else cfg["device"]
            self.half = bool(cfg["half"]) and self.device != "cpu"
            names = model.names
            if set(names.values()) <= PKJI_CODES | set(LEGACY): self.cls_map, kind = {i: LEGACY.get(n, n) for i, n in names.items()}, "kelas PKJI custom"
            else: self.cls_map, kind = {i: cfg["coco_map"][n] for i, n in names.items() if n in cfg["coco_map"]}, "COCO→PKJI"
            self.classes = sorted(self.cls_map)
            model.predict(np.zeros((360, 640, 3), np.uint8), verbose=False, imgsz=cfg["imgsz"], device=self.device, half=self.half)  # warm-up
            self.model = model
            self.msg = f"YOLO11 aktif: {used} ({kind}) · device={self.device}{' FP16' if self.half else ''}"
        except Exception as e:
            self.model = None; self.msg = f"AI Engine belum aktif: {e}"
        return self.ready

    def mask(self, frame, cam_id):
        cfg = cam_cal(cam_id, frame.shape); roi = cfg.get("roi") if cfg else None
        if not roi or len(roi) < 3: return frame
        m = np.zeros(frame.shape[:2], np.uint8); cv2.fillPoly(m, [np.int32(roi)], 255)
        return cv2.bitwise_and(frame, frame, mask=m)

    def process(self, frame, cam_id):
        """-> (frame asli, [{id, cls (kode PKJI), bbox, conf}]). Gambar overlay lewat draw()."""
        c = self.cfg
        res = self.model.track(self.mask(frame, cam_id), persist=True, tracker=self.tracker_path, verbose=False,
                               imgsz=c["imgsz"], conf=c["conf"], iou=c["iou"], device=self.device, half=self.half, classes=self.classes)[0]
        tracks, b = [], res.boxes
        if b is not None and b.id is not None:
            for xy, i, k, p in zip(b.xyxy.tolist(), b.id.tolist(), b.cls.tolist(), b.conf.tolist()):
                code = self.cls_map.get(int(k))
                if code: tracks.append({"id": int(i), "cls": code, "bbox": tuple(map(int, xy)), "conf": p})
        return frame, tracks

    @staticmethod
    def draw(frame, tracks, labels=None):
        for t in tracks:
            x1, y1, x2, y2 = t["bbox"]; cv2.rectangle(frame, (x1, y1), (x2, y2), (211, 211, 34), 2)
            txt = f"{t['cls']} #{t['id']} {(labels or {}).get(t['id']) or ''}".strip()
            cv2.putText(frame, txt, (x1, max(y1 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, .55, (211, 211, 34), 2)
        return frame
