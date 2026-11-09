from pathlib import Path
from fastapi import Request
from fastapi.templating import Jinja2Templates
ROOT = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(ROOT / "templates"))

def _vendor():
    """True bila Tailwind & Chart.js sudah diunduh ke static/vendor (jalankan: python scripts/download_assets.py) -> tampilan jalan offline."""
    v = ROOT / "static" / "vendor"
    return (v / "tailwind.js").exists() and (v / "chart.umd.min.js").exists()

def page(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, {"active": request.url.path, "vendor": _vendor(), **ctx})
