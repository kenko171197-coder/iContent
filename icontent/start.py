"""Biểu tượng Studio566 chạy file này (bằng Python kèm trong gói, runtime\\python\\pythonw.exe), không chạy thẳng .venv.

Lý do: khi thư viện cài dở, .venv hỏng hay bị phần mềm diệt virus xóa, bấm biểu tượng cũ chỉ ra hộp lỗi của Windows hoặc chẳng
có gì, khách không biết làm gì tiếp. Nay: mở Studio566 như cũ; nếu nó không lên được thì mở ngay cửa sổ Sửa lỗi Studio566
(icontent/support.py) cho biết vì sao, có nút sửa và nút tạo gói báo lỗi. Chỉ dùng thư viện chuẩn của Python.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from . import support

WAIT = 300      # giây: lần đầu mở trên máy chậm (phần mềm diệt virus quét từng file thư viện) có thể mất vài phút


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:      # lỗi của lần mở trước không còn đúng nữa: Sửa lỗi chỉ hiện lỗi của lần này
        support.START_ERROR.unlink(missing_ok=True)
    except OSError:
        pass
    py = support.venv_python(windowless=True)
    if not py.is_file():
        return support.serve(reason="chua-cai")
    env = dict(os.environ, ICONTENT_LAUNCHER="1")
    try:
        p = subprocess.Popen([str(py), "-m", "icontent", "ui", "--app", *argv], cwd=str(support.ROOT), env=env)
    except OSError:      # file Python của .venv hỏng hoặc bị chặn
        return support.serve(reason="khong-chay")
    end = time.time() + WAIT
    while time.time() < end:
        code = p.poll()
        if code is not None:
            # 0: đã mở thêm cửa sổ cho Studio566 đang chạy, hoặc khách mở rồi đóng ngay; khác 0: không mở được
            return 0 if code == 0 else support.serve(reason=f"ma-{code}")
        if support.app_alive(timeout=1.5):
            return 0      # đã lên: Studio566 tự lo phần còn lại (tự chạy lại khi chết bất thường, appwin.supervise)
        time.sleep(1.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
