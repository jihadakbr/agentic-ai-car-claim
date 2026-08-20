"""Titik masuk untuk Hugging Face Space.

Space mencari berkas bernama `app.py` di akar repo, jadi nama dan letaknya tidak boleh
diubah. Isinya sengaja tipis: menyiapkan isi database kalau masih kosong, lalu menyalakan
server yang sama dengan yang dipakai saat pengembangan.

Penyiapan dikerjakan saat Space menyala, bukan saat permintaan pertama masuk, supaya klaim
pertama yang dikirim di depan atasan tidak menanggung waktu pengisian data.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from sqlalchemy import select

from app.api.server import buat_server
from app.core.log import redam_galat_koneksi
from app.db.models import Claim, Policy
from app.db.seed import isi_semua
from app.db.session import buat_tabel, sesi


def siapkan_isi() -> None:
    """Isi data master, dan klaim contoh kalau memang diminta lewat lingkungan."""
    buat_tabel()
    with sesi() as s:
        if s.scalar(select(Policy).limit(1)) is None:
            hasil = isi_semua(s)
            print(f"Data master diisi: {hasil}")

    with sesi() as s:
        ada_contoh = s.scalar(select(Claim).where(Claim.contoh_demo.is_(True)).limit(1))

    # Bawaannya mati di mana pun, termasuk di Space. Klaim contoh membuat Daftar Klaim
    # sudah terisi sebelum siapa pun mengirim apa-apa, dan saat demo itu justru mengaburkan
    # mana yang baru saja dikirim. Nyalakan sendiri lewat BUAT_KLAIM_DEMO kalau memang
    # butuh jaring pengaman, misalnya saat antrean GPU sedang panjang.
    if ada_contoh is None and os.getenv("BUAT_KLAIM_DEMO", "0") == "1":
        from scripts.buat_klaim_demo import main as buat_demo

        buat_demo()


def ringkasan_kesiapan(server) -> None:
    """Cetak apa yang aktif dan apa yang belum, supaya tidak perlu ditebak dari log."""
    from app.api.server import jalur_model
    from app.core.penyedia import buat_klien
    from app.db.session import alamat_database_tersamar

    klien = buat_klien()
    # Jalur bobotnya ditanya ke fungsi yang sama dengan yang dipakai server saat memilih
    # detektor. Kalau ringkasan ini menyimpulkan sendiri, dia bisa mengaku model aktif
    # padahal server jatuh ke detektor contoh, dan itu kebohongan yang paling mahal.
    bobot = jalur_model()
    detektor = (
        f"DetektorYolo ({bobot[0].name}, {bobot[1].name})"
        if bobot
        else "DetektorContoh, deteksi masih dibuat-buat karena bobot model belum dipasang"
    )
    penyedia_llm = (
        ", ".join(k.nama for k in klien.klien)
        if klien is not None and hasattr(klien, "klien")
        else "tidak ada, penilaian agent mati dan narasi disusun kode"
    )

    # flush dipaksa karena keluaran tertahan di penyangga selama server masih berjalan,
    # dan ringkasan yang baru muncul saat server dimatikan tidak ada gunanya.
    baris = [
        "-" * 62,
        f"  Database : {alamat_database_tersamar()}",
        f"  Detektor : {detektor}",
        f"  LLM      : {penyedia_llm}",
        "-" * 62,
    ]
    print("\n" + "\n".join(baris) + "\n", flush=True)


redam_galat_koneksi()
siapkan_isi()
demo = buat_server()
ringkasan_kesiapan(demo)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))
