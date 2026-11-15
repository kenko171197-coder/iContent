"""Chụp ảnh giao diện Studio566 đang chạy (dùng trên GitHub Actions, Windows có sẵn Edge).
python tests/ui_screens.py http://127.0.0.1:8799 <thư mục ảnh>   (chạy trong thư mục cài Studio566)"""
import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

base, out = sys.argv[1].rstrip("/"), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)

# dự án mẫu để chụp Studio
demo = Path("workspace") / "demo566"
demo.mkdir(parents=True, exist_ok=True)
(demo / "meta.json").write_text(json.dumps({"title": "Bà nội sẽ không tha đâu", "platform": "douyin", "duration": 20.0, "width": 540, "height": 960}, ensure_ascii=False), encoding="utf-8")
rows = [(0.4, 2.0, "上来吧，别站在那儿", "Lên đây đi, đừng đứng đó nữa."), (2.2, 3.4, "我…", "Con…"),
        (4.5, 7.8, "奶奶不会放过你的", "Bà nội sẽ không tha cho con đâu."), (8.2, 10.6, "让开，全挡住了", "Tránh ra, che hết rồi."),
        (11.0, 14.5, "你到底想怎么样", "Rốt cuộc con muốn thế nào?"), (15.0, 18.6, "我只是想回家", "Con chỉ muốn về nhà thôi.")]
(demo / "segments.json").write_text(json.dumps([{"id": i + 1, "start": a, "end": b, "text": zh, "trans": vi, "check": "ocr" if i == 1 else ""} for i, (a, b, zh, vi) in enumerate(rows)], ensure_ascii=False), encoding="utf-8")
ff = shutil.which("ffmpeg") or next((str(p) for p in Path(".").rglob("ffmpeg.exe")), None)
if ff:
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x2b2420:s=540x960:d=20", "-f", "lavfi", "-i", "sine=f=300:d=20",
                    "-shortest", "-pix_fmt", "yuv420p", str(demo / "source.mp4")], check=False)

SHOTS = [("home", 1440, 900, None), ("new", 1440, 1000, None), ("settings", 1440, 900, None), ("home", 1024, 768, None),
         ("studio/demo566", 1440, 900, None), ("studio/demo566", 1440, 900, "export"), ("studio/demo566", 1440, 900, "pro")]
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    for route, w, h, extra in SHOTS:
        pg = b.new_page(viewport={"width": w, "height": h})
        errs = []
        pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
        pg.goto(base + "/#/home")
        pg.evaluate("(m) => { localStorage.setItem('ic.onboarded', '1'); localStorage.setItem('ic.version', '9.9.9'); localStorage.setItem('ic.studioMode', m); }",
                    "pro" if extra == "pro" else "simple")
        pg.goto(base + f"/#/{route}")
        pg.reload()
        pg.wait_for_timeout(4000)
        if extra == "export":
            try:
                pg.get_by_role("button", name="Xuất & đăng").click()
                pg.wait_for_timeout(1200)
            except Exception as e:      # noqa: BLE001
                errs.append("click: " + str(e)[:120])
        name = route.replace("/", "-") + f"-{w}" + (f"-{extra}" if extra else "")
        pg.screenshot(path=str(out / f"{name}.png"))
        print(name, "ok", errs)
        if os.environ.get("SHOTS_TO_LOG"):      # xem ảnh qua nhật ký khi không tải được artifact
            jpg = pg.screenshot(type="jpeg", quality=70)
            print(f"SHOT-BEGIN {name}\n" + base64.b64encode(jpg).decode() + "\nSHOT-END")
        pg.close()
    b.close()
