"""Isi tabel master ke database.

Jalankan: `uv run python scripts/isi_data_awal.py`

Aman dijalankan berulang. Tabel yang sudah terisi dilewati, jadi tidak ada data ganda.
Alamat database diambil dari `DATABASE_URL`, dan kalau tidak diisi memakai berkas SQLite
di folder backend untuk pengembangan lokal.

Tabel dibuat, tidak pernah diubah. Kalau kolom baru ditambahkan ke skema, database lama
harus dibangun ulang: `uv run python scripts/isi_data_awal.py --ulang`. Perintah itu
menghapus seluruh isinya beserta foto klaim di `FOLDER_FOTO`, jadi jangan diarahkan ke
database yang datanya masih dipakai.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.db.models import Base
from app.db.seed import isi_semua
from app.db.session import alamat_database_tersamar, buat_tabel, get_engine, sesi


def _kosongkan_foto() -> int:
    """Buang foto klaim lama sekalian.

    Penomoran klaim mulai lagi dari awal setelah database dibangun ulang, jadi berkas lama
    memakai nama yang sama dengan klaim baru dan menampilkan foto klaim yang sudah tidak ada.
    """
    folder = Path(os.getenv("FOLDER_FOTO", "data/foto-klaim"))
    if not folder.exists():
        return 0
    berkas = [p for p in folder.rglob("*") if p.is_file()]
    for p in berkas:
        p.unlink()
    return len(berkas)


def main() -> None:
    print(f"Database: {alamat_database_tersamar()}")
    if "--ulang" in sys.argv:
        print("Membuang seluruh tabel lalu membuatnya kembali.")
        Base.metadata.drop_all(get_engine())
        print(f"Foto klaim lama dihapus: {_kosongkan_foto()} berkas")
    buat_tabel()

    with sesi() as s:
        hasil = isi_semua(s)

    total = sum(hasil.values())
    if total == 0:
        print("Semua tabel master sudah terisi, tidak ada yang ditambahkan.")
        return

    print("Baris baru yang ditambahkan:")
    for tabel, jumlah in hasil.items():
        print(f"  {tabel:<16} {jumlah}")


if __name__ == "__main__":
    main()
