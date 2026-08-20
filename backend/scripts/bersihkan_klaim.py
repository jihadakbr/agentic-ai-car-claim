"""Hapus klaim percobaan beserta fotonya, untuk mengembalikan keadaan bersih.

Menghapus berkas di folder foto secara manual berbahaya: baris `claim_photo` tetap ada dan
menunjuk berkas yang sudah hilang, lalu membuka fotonya di layar adjuster menghasilkan galat
500, bukan pesan yang bisa dibaca. Skrip ini memakai jalur hapus yang sama dengan tombol
hapus di layar admin, yang membuang baris beserta berkasnya sekaligus.

Klaim contoh demo dilewati secara bawaan, karena `buat_klaim_demo.py` sudah menghapus dan
membangkitkannya sendiri tiap kali dijalankan.

Jalankan dari folder backend:

    uv run python scripts/bersihkan_klaim.py
    uv run python scripts/bersihkan_klaim.py --semua
    uv run python scripts/bersihkan_klaim.py --lihat
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select

from app.api.penyimpanan import hapus_klaim
from app.api.server import FOLDER_FOTO
from app.core.berkas import buat_penyimpan
from app.db.models import Claim
from app.db.session import buat_tabel, sesi


def main() -> int:
    p = argparse.ArgumentParser(description="Hapus klaim percobaan beserta fotonya")
    p.add_argument("--semua", action="store_true", help="ikut menghapus klaim contoh demo")
    p.add_argument("--lihat", action="store_true", help="cuma tampilkan, tidak menghapus")
    args = p.parse_args()

    buat_tabel()
    lemari = buat_penyimpan(FOLDER_FOTO)

    with sesi() as s:
        q = select(Claim).order_by(Claim.created_at)
        if not args.semua:
            q = q.where(Claim.contoh_demo.is_(False))
        klaim = list(s.scalars(q))

        if not klaim:
            print("Tidak ada klaim yang perlu dihapus.")
            return 0

        print(f"{len(klaim)} klaim akan dihapus:")
        for k in klaim:
            tanda = " (contoh demo)" if k.contoh_demo else ""
            print(f"  {k.nomor_klaim}  {k.status}  surveyor={k.surveyor or '-'}{tanda}")

        if args.lihat:
            print("\nTidak ada yang dihapus, ini cuma tampilan.")
            return 0

        total_foto = sum(hapus_klaim(s, k, lemari)["foto_dihapus"] for k in klaim)

    print(f"\nSelesai. {len(klaim)} klaim dan {total_foto} foto dihapus.")
    print("Klaim contoh TIDAK dibangun ulang. Jalankan buat_klaim_demo.py hanya kalau memang")
    print("menginginkannya kembali, bukan sebagai lanjutan pembersihan ini.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
