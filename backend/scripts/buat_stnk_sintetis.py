"""Bangkitkan kumpulan foto STNK buatan beserta jawaban benarnya.

Jalankan: `uv run python scripts/buat_stnk_sintetis.py --jumlah 40`

Untuk tiap polis di database dibuat beberapa varian dengan tingkat kerusakan gambar
berbeda, dari yang mudah dibaca sampai yang memang sulit. Ditambah beberapa berkas yang
sengaja dibuat tidak cocok dengan polisnya, supaya pemeriksaan kecurangan punya bahan uji.

Jawaban benarnya ditulis ke `jawaban.json` di folder yang sama, dipakai untuk menghitung
akurasi pembaca field nanti.
"""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.db.session import buat_tabel, sesi
from app.pipeline.stnk_dataset import (
    dengan_kesalahan,
    kumpulkan_dari_database,
    tulis_berkas,
)

JENIS_KESALAHAN = [
    "nomor_rangka_beda",
    "nomor_polisi_beda",
    "tahun_tidak_cocok_vin",
    "nomor_rangka_pendek",
]


def main() -> None:
    p = argparse.ArgumentParser(description="Bangkitkan foto STNK buatan")
    p.add_argument("--jumlah", type=int, default=40, help="jumlah berkas yang dibuat")
    p.add_argument("--seed", type=int, default=2026, help="benih acak, supaya bisa diulang")
    p.add_argument(
        "--folder",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "stnk-sintetis",
    )
    p.add_argument(
        "--gaya",
        choices=["acuan", "gambar"],
        default="acuan",
        help="acuan memakai templat foto, gambar menggambar lembar sendiri",
    )
    args = p.parse_args()

    rng = random.Random(args.seed)
    buat_tabel()

    with sesi() as s:
        dasar = kumpulkan_dari_database(s, rng)

    if not dasar:
        print("Tabel polis masih kosong. Jalankan scripts/isi_data_awal.py lebih dulu.")
        raise SystemExit(1)

    # Sekitar seperempat dibuat sengaja salah, supaya cek validitas punya kasus gagal yang
    # cukup untuk diukur, bukan cuma kasus lolos.
    contoh = []
    for i in range(args.jumlah):
        asal = dasar[i % len(dasar)]
        if i % 4 == 3:
            contoh.append(dengan_kesalahan(asal, rng.choice(JENIS_KESALAHAN), rng))
        else:
            contoh.append(asal)

    # Tingkat kerusakan gambar dibuat bertingkat, supaya bisa dilihat pada kondisi seperti
    # apa pembacaan mulai gagal. Seluruh contoh dikirim sekali jalan supaya nomor urut di
    # nama berkasnya benar dan tidak ada yang saling menimpa.
    tingkat = [[0.3, 0.7, 1.0, 1.4][i % 4] for i in range(len(contoh))]
    jalur = tulis_berkas(contoh, args.folder, rng, tingkat_kerusakan=tingkat, gaya=args.gaya)

    jawaban = [
        {
            "berkas": j.name,
            "nomor_polis": c.nomor_polis,
            "sengaja_salah": c.sengaja_salah,
            "jawaban_benar": c.jawaban_benar,
        }
        for j, c in zip(jalur, contoh, strict=True)
    ]
    berkas_jawaban = args.folder / "jawaban.json"
    berkas_jawaban.write_text(json.dumps(jawaban, indent=2, ensure_ascii=False), encoding="utf-8")

    jumlah_salah = sum(1 for c in contoh if c.sengaja_salah)
    print(f"Dibuat {len(jalur)} berkas di {args.folder}")
    print(f"  cocok dengan polis  : {len(jalur) - jumlah_salah}")
    print(f"  sengaja tidak cocok : {jumlah_salah}")
    print(f"Jawaban benar ditulis ke {berkas_jawaban.name}")


if __name__ == "__main__":
    main()
