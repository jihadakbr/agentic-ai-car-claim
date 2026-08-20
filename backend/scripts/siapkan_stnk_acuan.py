"""Siapkan templat STNK dari foto acuan.

Foto acuan memuat dua lembar: STNK di atas dan TBPKP di bawah. Yang dibaca pipeline cuma
STNK, jadi lembar bawah dibuang di sini sekalian membuang separuh data pribadi pemiliknya.

Lembarnya difoto miring. Kemiringan itu diluruskan supaya kotak tiap field jadi persegi
lurus dan gampang ditambal. Kemiringan yang acak tetap ada nanti, ditambahkan `rusak_sedikit`
saat berkas dibangkitkan, jadi tiap lembar hasil tidak miring dengan sudut yang sama.

Jalankan sekali:

    uv run python scripts/siapkan_stnk_acuan.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ASAL = Path("data/acuan/stnk-acuan-asli.jpeg")
TUJUAN = Path("data/acuan/stnk-acuan.jpg")

# Diukur dari foto acuan: tepi atas lembar turun 0.961 derajat dari kiri ke kanan.
SUDUT_LURUS = -0.961

# Batas lembar STNK pada gambar yang sudah diluruskan, berhenti tepat di atas celah gelap
# yang memisahkannya dari lembar TBPKP.
POTONG = (74, 8, 1126, 336)

# Fotonya kurang tajam untuk teks sekecil ini. Diperbesar supaya pendeteksi teks OCR punya
# tinggi huruf yang cukup, sekaligus supaya teks pengganti bisa digambar tajam.
SKALA = 2


def main() -> int:
    if not ASAL.exists():
        print(f"Foto acuan tidak ada di {ASAL}", file=sys.stderr)
        return 1

    img = Image.open(ASAL).convert("RGB")
    lurus = img.rotate(SUDUT_LURUS, resample=Image.BICUBIC, fillcolor=(40, 35, 30))
    lembar = lurus.crop(POTONG)
    lebar, tinggi = lembar.size
    hasil = lembar.resize((lebar * SKALA, tinggi * SKALA), Image.LANCZOS)

    TUJUAN.parent.mkdir(parents=True, exist_ok=True)
    hasil.save(TUJUAN, quality=95)
    print(f"Tersimpan: {TUJUAN} ({hasil.size[0]}x{hasil.size[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
