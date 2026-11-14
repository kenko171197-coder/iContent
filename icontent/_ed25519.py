"""Ed25519 thuần Python (RFC 8032), không phụ thuộc thư viện ngoài.

Chỉ cần cho phía người dùng là `verify()` (kiểm chữ ký bằng khoá công khai). `sign()`/`publickey()` để công cụ
cấp key của tác giả dùng khi máy tác giả không cài `cryptography`. Dùng `pow()` tích hợp của Python (chạy ở tầng C)
cho luỹ thừa modulo nên một lần kiểm chỉ mất vài chục mili giây.

Giống hệt bản của iTube và iKey_bot (cùng tác giả). Tính đúng đắn được đối chiếu với vector chuẩn RFC 8032 trong tests/test_features.py.
"""
from __future__ import annotations

import hashlib

_b = 256
_q = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_d = (-121665 * pow(121666, _q - 2, _q)) % _q
_I = pow(2, (_q - 1) // 4, _q)


def _sha512(m: bytes) -> bytes:
    return hashlib.sha512(m).digest()


def _inv(x: int) -> int:
    return pow(x, _q - 2, _q)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(_d * y * y + 1)
    x = pow(xx, (_q + 3) // 8, _q)
    if (x * x - xx) % _q != 0:
        x = (x * _I) % _q
    if x % 2 != 0:
        x = _q - x
    return x


_By = (4 * _inv(5)) % _q
_Bx = _xrecover(_By)
_B = (_Bx % _q, _By % _q)


def _edwards(P: tuple[int, int], Q: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = P
    x2, y2 = Q
    denom = _d * x1 * x2 * y1 * y2
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + denom)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - denom)
    return (x3 % _q, y3 % _q)


def _scalarmult(P: tuple[int, int], e: int) -> tuple[int, int]:
    Q = (0, 1)
    while e > 0:
        if e & 1:
            Q = _edwards(Q, P)
        P = _edwards(P, P)
        e >>= 1
    return Q


def _bit(h: bytes, i: int) -> int:
    return (h[i // 8] >> (i % 8)) & 1


def _encodeint(y: int) -> bytes:
    return y.to_bytes(32, "little")


def _encodepoint(P: tuple[int, int]) -> bytes:
    x, y = P
    return ((y & ((1 << 255) - 1)) | ((x & 1) << 255)).to_bytes(32, "little")


def _decodeint(s: bytes) -> int:
    return int.from_bytes(s, "little")


def _Hint(m: bytes) -> int:
    return int.from_bytes(_sha512(m), "little")


def _secret_scalar(h: bytes) -> int:
    a = 2 ** (_b - 2) + sum(2 ** i * _bit(h, i) for i in range(3, _b - 2))
    return a


def publickey(seed: bytes) -> bytes:
    """Khoá công khai 32 byte từ hạt giống bí mật 32 byte."""
    if len(seed) != 32:
        raise ValueError("Hạt giống Ed25519 phải đúng 32 byte")
    h = _sha512(seed)
    A = _scalarmult(_B, _secret_scalar(h))
    return _encodepoint(A)


def sign(seed: bytes, msg: bytes) -> bytes:
    """Chữ ký 64 byte cho msg bằng hạt giống bí mật 32 byte."""
    if len(seed) != 32:
        raise ValueError("Hạt giống Ed25519 phải đúng 32 byte")
    h = _sha512(seed)
    a = _secret_scalar(h)
    pk = _encodepoint(_scalarmult(_B, a))
    r = _Hint(h[32:64] + msg)
    R = _scalarmult(_B, r)
    S = (r + _Hint(_encodepoint(R) + pk + msg) * a) % _L
    return _encodepoint(R) + _encodeint(S)


def _isoncurve(P: tuple[int, int]) -> bool:
    x, y = P
    return (-x * x + y * y - 1 - _d * x * x * y * y) % _q == 0


def _decodepoint(s: bytes) -> tuple[int, int]:
    y = int.from_bytes(s, "little") & ((1 << 255) - 1)
    x = _xrecover(y)
    if (x & 1) != _bit(s, _b - 1):
        x = _q - x
    P = (x, y)
    if not _isoncurve(P):
        raise ValueError("Điểm không nằm trên đường cong")
    return P


def verify(public_key: bytes, signature: bytes, msg: bytes) -> bool:
    """True nếu signature (64 byte) hợp lệ cho msg với public_key (32 byte). Không bao giờ ném lỗi."""
    try:
        if len(signature) != 64 or len(public_key) != 32:
            return False
        R = _decodepoint(signature[:32])
        A = _decodepoint(public_key)
        S = _decodeint(signature[32:])
        if S >= _L:
            return False
        h = _Hint(_encodepoint(R) + public_key + msg)
        return _scalarmult(_B, S) == _edwards(R, _scalarmult(A, h))
    except (ValueError, IndexError):
        return False
