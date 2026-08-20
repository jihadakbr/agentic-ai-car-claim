"""Cari koordinat tiap teks di templat STNK.

Alat sekali pakai untuk mengisi `_KOTAK` di `app.pipeline.stnk_generator`. Koordinat yang
ditebak dari mata hampir selalu meleset, dan melesetnya baru ketahuan setelah teks pengganti
menimpa label sebelahnya.

Keluarannya dua berkas di folder yang sama dengan templat:

- `kalibrasi.json`, daftar teks yang terbaca beserta kotaknya
- `kalibrasi.png`, templat dengan kotak-kotak itu digambar dan dinomori

RapidOCR dipanggil langsung, bukan lewat `PembacaRapidOcr`, karena di sini yang dibutuhkan
kotak utuh sampai tingginya, sedangkan pembaca produksi cuma membawa titik kiri atas dan
lebar.

Jalankan:

    uv run python scripts/kalibrasi_stnk_acuan.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

TEMPLAT = Path("data/acuan/stnk-acuan.jpg")


def main() -> int:
    if not TEMPLAT.exists():
        print(f"Templat tidak ada di {TEMPLAT}, jalankan siapkan_stnk_acuan.py dulu",
              file=sys.stderr)
        return 1

    from rapidocr import RapidOCR

    img = Image.open(TEMPLAT).convert("RGB")
    hasil = RapidOCR()(np.array(img), use_cls=False)
    if hasil is None or hasil.boxes is None:
        print("Tidak ada teks yang terbaca", file=sys.stderr)
        return 1

    d = ImageDraw.Draw(img)
    isi = []
    for i, (teks, skor, kotak) in enumerate(
        zip(hasil.txts, hasil.scores, hasil.boxes, strict=True)
    ):
        titik = np.array(kotak, dtype=float)
        x0, y0 = int(titik[:, 0].min()), int(titik[:, 1].min())
        x1, y1 = int(titik[:, 0].max()), int(titik[:, 1].max())
        d.rectangle([x0, y0, x1, y1], outline=(220, 30, 30), width=2)
        d.text((x0, max(0, y0 - 12)), str(i), fill=(220, 30, 30))
        isi.append({"no": i, "teks": teks, "skor": round(float(skor), 3),
                    "kotak": [x0, y0, x1, y1]})

    (TEMPLAT.parent / "kalibrasi.json").write_text(
        json.dumps(isi, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    img.save(TEMPLAT.parent / "kalibrasi.png")
    print(f"{len(isi)} kotak teks terbaca")
    for b in isi:
        print(f"  [{b['no']:>3}] {b['kotak']!s:<26} {b['teks']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
