import cv2, numpy as np

class SpeedEstimator:
    """Homografi piksel->meter + line crossing dua arah, waktu lintas diinterpolasi antar frame."""
    def __init__(self, cfg, vmin=2, vmax=250):
        self.vmin, self.vmax = vmin, vmax
        self.H = cv2.getPerspectiveTransform(np.float32(cfg["src"]), np.float32(cfg["dst"]))
        self.lines = (cfg["line_a"], cfg["line_b"]); self.dist = abs(cfg["line_b"] - cfg["line_a"])
        self.state = {}

    def world_y(self, pt):
        return float(cv2.perspectiveTransform(np.float32([[pt]]), self.H)[0][0][1])

    def update(self, tid, centroid, t):
        """Saat kendaraan melewati garis kedua -> (km/jam, arah) dengan arah 1 = A lalu B, 2 = B lalu A; selain itu None.
        Kendaraan dihitung berapa pun kecepatannya (termasuk stop-and-go); filter kecepatan minimum diterapkan di db.log_detection
        hanya sebagai status 'macet'. Hanya dt=0 (ukuran tidak valid) dan kecepatan > vmax (lonjakan piksel) yang dibuang."""
        y = self.world_y(centroid); s = self.state.get(tid)
        if s is None:
            self.state[tid] = {"y": y, "t": t, "first": None, "done": False}; return None
        out = None
        if not s["done"] and y != s["y"]:
            for k, L in enumerate(self.lines):
                if (s["y"] - L) * (y - L) <= 0:
                    tc = s["t"] + (t - s["t"]) * (L - s["y"]) / (y - s["y"])
                    if s["first"] is None: s["first"] = (k, tc)
                    elif s["first"][0] != k:
                        dt = abs(tc - s["first"][1]); s["done"] = True
                        v = self.dist / dt * 3.6 if dt > 0 else None  # dt=0 = pengukuran tidak valid
                        out = (v, 1 if s["first"][0] == 0 else 2) if v is not None and v <= self.vmax else None
        s["y"], s["t"] = y, t
        return out

    def forget(self, tid): self.state.pop(tid, None)
