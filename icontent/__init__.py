"""Studio566 — tải video nền tảng Trung Quốc, tự làm phụ đề, dịch, lồng tiếng theo timeline và dựng lại."""

import os as _os

__version__ = "0.9.0"

# Bộ đệm mô hình Hugging Face lưu file thật, không dùng symlink. Máy bật Developer Mode (hoặc chạy quyền admin) mặc định có
# symlink, ONNX Runtime 1.2x+ thì từ chối file .data nằm ngoài thư mục của file .onnx sau khi giải symlink, nên giọng VieNeu
# không nạp được. Phải đặt trước khi thư viện nào import huggingface_hub (nó đọc biến này lúc import). Xem fixes.unsymlink_models.
_os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
_os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
