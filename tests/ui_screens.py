"""Chụp ảnh giao diện Studio566 đang chạy (dùng trên GitHub Actions, Windows có sẵn Edge).
python tests/ui_screens.py http://127.0.0.1:8799 <thư mục ảnh>"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

base, out = sys.argv[1].rstrip("/"), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
SHOTS = [("home", 1440, 900), ("new", 1440, 900), ("library", 1440, 900), ("settings", 1440, 900), ("home", 1024, 768)]
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    for route, w, h in SHOTS:
        pg = b.new_page(viewport={"width": w, "height": h})
        errs = []
        pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
        pg.goto(base + "/#/home")
        pg.evaluate("() => { localStorage.setItem('ic.onboarded', '1'); localStorage.setItem('ic.version', '9.9.9'); }")
        pg.goto(base + f"/#/{route}")
        pg.reload()
        pg.wait_for_timeout(3500)
        pg.screenshot(path=str(out / f"{route}-{w}.png"))
        print(route, w, "ok", errs)
        pg.close()
    b.close()
