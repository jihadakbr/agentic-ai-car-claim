"""Ubah nilai ambang di tabel `config` tanpa membangun ulang database.

Kenapa perlu skrip sendiri: `isi_data_awal.py` sengaja cuma menambahkan kunci yang belum
ada dan tidak pernah menimpa nilai yang sudah tersimpan, supaya ambang yang sudah disetel
sesuai keadaan lapangan tidak terhapus tiap kali data awal dijalankan lagi. Konsekuensinya,
mengubah nilai bawaan di kode tidak berpengaruh pada database yang sudah terisi, dan
perubahannya harus disebut di sini secara sadar.

Jalankan dari folder backend:

    uv run python scripts/setel_config.py min_foto_kerusakan=1
    uv run python scripts/setel_config.py min_foto_kerusakan=1 min_foto_bagian_diganti=1

Tanpa argumen, isinya cuma ditampilkan tanpa mengubah apa pun.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import select

from app.db.models import Config
from app.db.session import buat_tabel, sesi


def tampilkan(s) -> None:
    print(f"\n{'Kunci':<32}{'Nilai':>10}")
    for c in s.scalars(select(Config).order_by(Config.key)):
        print(f"{c.key:<32}{c.value:>10}")


def main() -> int:
    buat_tabel()
    pasangan = []
    for arg in sys.argv[1:]:
        if "=" not in arg:
            print(f"Bentuknya kunci=nilai, yang diterima: {arg}", file=sys.stderr)
            return 1
        kunci, nilai = arg.split("=", 1)
        pasangan.append((kunci.strip(), nilai.strip()))

    with sesi() as s:
        if not pasangan:
            tampilkan(s)
            return 0

        for kunci, nilai in pasangan:
            baris = s.scalar(select(Config).where(Config.key == kunci))
            if baris is None:
                print(f"Kunci {kunci} tidak ada di database", file=sys.stderr)
                return 1
            if baris.value == nilai:
                print(f"{kunci}: sudah {nilai}, tidak diubah")
                continue
            print(f"{kunci}: {baris.value} -> {nilai}")
            baris.value = nilai
        s.commit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
