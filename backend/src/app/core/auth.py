"""Masuk, kata sandi, dan token peran.

Semuanya memakai pustaka bawaan Python, tanpa menambah dependensi. Untuk demo dengan tiga
akun tetap, satu berkas ini sudah cukup, dan menambah pustaka autentikasi penuh justru
menambah permukaan yang harus dijelaskan saat presentasi.

Dua hal yang dipegang di sini:

- Kata sandi tidak pernah disimpan apa adanya, cuma turunannya lewat PBKDF2 dengan garam
  berbeda tiap pengguna.
- Token ditandatangani, bukan sekadar ditebak-tebak. Peran yang tertulis di dalam token
  tidak bisa diubah tanpa merusak tanda tangannya.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

SURVEYOR = "surveyor"
ADJUSTER = "adjuster"
ADMIN = "admin"
PERAN = (SURVEYOR, ADJUSTER, ADMIN)

PUTARAN = 200_000
UMUR_TOKEN_DETIK = 12 * 60 * 60


class TokenTidakSah(Exception):
    """Token tidak bisa dipercaya, entah rusak, dipalsukan, atau sudah kedaluwarsa."""


def garam_baru() -> str:
    return secrets.token_hex(16)


def hash_sandi(sandi: str, garam: str) -> str:
    turunan = hashlib.pbkdf2_hmac("sha256", sandi.encode(), garam.encode(), PUTARAN)
    return turunan.hex()


def periksa_sandi(sandi: str, garam: str, harapan: str) -> bool:
    # compare_digest, bukan ==, supaya lama pembandingan tidak membocorkan berapa banyak
    # karakter awal yang sudah benar.
    return hmac.compare_digest(hash_sandi(sandi, garam), harapan)


def rahasia() -> bytes:
    """Kunci penanda tangan token.

    Nilai bawaan sengaja ada supaya sistem tetap bisa dijalankan tanpa pengaturan apa pun.
    Di server yang bisa diakses orang lain, isi `RAHASIA_TOKEN` dengan nilai acak, karena
    kunci yang tertulis di repo publik sama saja dengan tidak ada kunci.
    """
    return os.getenv("RAHASIA_TOKEN", "rahasia-demo-agentic-ai-car-claim").encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _dari_b64(teks: str) -> bytes:
    return base64.urlsafe_b64decode(teks + "=" * (-len(teks) % 4))


def buat_token(username: str, peran: str, umur_detik: int = UMUR_TOKEN_DETIK) -> str:
    muatan = {"sub": username, "peran": peran, "exp": int(time.time()) + umur_detik}
    isi = _b64(json.dumps(muatan, separators=(",", ":")).encode())
    tanda = _b64(hmac.new(rahasia(), isi.encode(), hashlib.sha256).digest())
    return f"{isi}.{tanda}"


def baca_token(token: str) -> dict:
    """Buka token setelah memastikan tanda tangannya benar dan masa berlakunya belum lewat."""
    try:
        isi, tanda = token.split(".")
    except ValueError as e:
        raise TokenTidakSah("Bentuk token tidak dikenali") from e

    harapan = _b64(hmac.new(rahasia(), isi.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(tanda, harapan):
        raise TokenTidakSah("Tanda tangan token tidak cocok")

    try:
        muatan = json.loads(_dari_b64(isi))
    except (ValueError, json.JSONDecodeError) as e:
        raise TokenTidakSah("Isi token tidak bisa dibaca") from e

    if muatan.get("exp", 0) < time.time():
        raise TokenTidakSah("Token sudah kedaluwarsa, silakan masuk lagi")

    return muatan


def sandi_demo() -> str:
    """Kata sandi ketiga akun contoh.

    Nilainya ikut terbaca di repo publik, dan itu diterima karena seluruh data di sistem ini
    buatan. Jangan pernah dipakai di tempat lain.
    """
    return os.getenv("PASSWORD_DEMO", "Kijang@2026")
