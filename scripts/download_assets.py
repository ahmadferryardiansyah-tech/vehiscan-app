"""Unduh Tailwind & Chart.js ke static/vendor agar UI jalan OFFLINE. Cukup sekali (butuh internet): python scripts/download_assets.py"""
import urllib.request
from pathlib import Path

V = Path(__file__).resolve().parents[1] / "static" / "vendor"; V.mkdir(parents=True, exist_ok=True)
FILES = {"tailwind.js": "https://cdn.tailwindcss.com/3.4.17",
         "chart.umd.min.js": "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"}
for name, url in FILES.items():
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = urllib.request.urlopen(req, timeout=60).read()
    (V / name).write_bytes(data); print(f"OK {name}: {len(data)//1024} KB")
print("Selesai. Restart server; halaman otomatis memakai file lokal.")
