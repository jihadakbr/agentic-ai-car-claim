"""Ukur akurasi pembaca field STNK terhadap kumpulan uji berlabel.

Yang diukur bukan mesin pengenal hurufnya, melainkan bagian yang mengubah teks hasil
pembacaan jadi Merk, Tipe, Nomor Rangka, dan seterusnya. Jawaban benarnya sudah tersimpan
saat berkasnya dibangkitkan, jadi angkanya bisa dihitung, bukan dikira-kira.

Perbandingannya longgar terhadap huruf besar-kecil dan spasi berlebih, karena beda begitu
tidak pernah mengubah hasil pemeriksaan validitas. Selain itu dicocokkan persis.

Jalankan:

    uv run --extra ml python scripts/ukur_ocr_stnk.py
    uv run --extra ml python scripts/ukur_ocr_stnk.py data/folder-lain

Jalur berkas di `jawaban.json` boleh menunjuk subfolder, jadi kumpulan uji yang tersusun per
skenario tetap bisa diukur sekali jalan.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from app.pipeline.stnk_ocr import PembacaRapidOcr, baca_stnk

# Field yang benar-benar dibawa `HasilStnk` ke pipeline. Sisanya digambar di lembar tapi
# tidak pernah dipakai, jadi tidak ada gunanya ikut dinilai.
FIELD = ["merk", "tipe", "tahun", "nomor_polisi", "nomor_rangka", "nomor_mesin",
         "nama_pemilik"]

# Nama field di jawaban benar tidak selalu sama dengan nama di hasil pembacaan.
ASAL = {"tahun": "tahun_pembuatan", "nomor_polisi": "nomor_registrasi"}


def samakan(nilai) -> str:
    return re.sub(r"\s+", " ", str(nilai or "")).strip().upper()


def main() -> int:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "data/foto-klaim-n-stnk")
    berkas_jawaban = folder / "jawaban.json"
    if not berkas_jawaban.exists():
        print(f"Tidak ada jawaban benar di {berkas_jawaban}", file=sys.stderr)
        return 1

    kumpulan = json.loads(berkas_jawaban.read_text(encoding="utf-8"))
    pembaca = PembacaRapidOcr()

    benar = dict.fromkeys(FIELD, 0)
    meleset: dict[str, list[str]] = {f: [] for f in FIELD}

    for contoh in kumpulan:
        gambar = Image.open(folder / contoh["berkas"])
        hasil = baca_stnk(gambar, pembaca)
        kunci = contoh["jawaban_benar"]
        for f in FIELD:
            harusnya = samakan(kunci[ASAL.get(f, f)])
            terbaca = samakan(getattr(hasil.stnk, f))
            if terbaca == harusnya:
                benar[f] += 1
            else:
                meleset[f].append(f"{contoh['berkas']}: '{terbaca}' seharusnya '{harusnya}'")

    n = len(kumpulan)
    print(f"\n{n} berkas diuji dari {folder}\n")
    print(f"{'Field':<16}{'Benar':>8}{'Akurasi':>10}")
    for f in FIELD:
        print(f"{f:<16}{benar[f]:>5}/{n:<3}{benar[f] / n:>9.0%}")
    total = sum(benar.values())
    print(f"{'SEMUA':<16}{total:>5}/{n * len(FIELD):<3}{total / (n * len(FIELD)):>9.0%}")

    print("\nYang meleset:")
    for f in FIELD:
        for baris in meleset[f]:
            print(f"  [{f}] {baris}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
