"""Memasang foto pilihan ke folder skenario demo.

Dikerjakan lewat API, bukan disalin manual lewat penjelajah berkas, karena aturannya mudah
keliru: nama berkasnya harus persis, akhirannya harus ikut berkas asalnya, dan folder 0
serta folder 2 wajib memakai berkas yang sama persis. Satu kekeliruan kecil di situ baru
ketahuan saat demo berlangsung.

Bagian ini alat bantu, bukan bagian produk. Yang boleh memanggilnya cuma pengelola akses.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

AKAR = Path(__file__).resolve().parent.parent.parent.parent
SKENARIO = AKAR / "data" / "foto-klaim-n-stnk"
SUMBER = AKAR / "data" / "kaggle"

# Folder yang isinya foto bengkel sungguhan, sengaja tidak ikut diganti.
DILEWATI = {"6 - contoh-riil-1-mobil"}

# Folder foto dipakai ulang harus memakai berkas yang sama persis dengan foto pertama
# folder klaim normal, kalau tidak pemeriksaan C2 tidak punya apa pun untuk ditangkap.
# Memasang ke salah satunya berarti memasang ke dua-duanya, dan itu cuma berlaku untuk
# slot pertama karena folder klaim normal punya empat foto sementara pasangannya satu.
PASANGAN_SAMA = ("0 - klaim normal", "1 - foto-dipakai-ulang")
SLOT_BERPASANGAN = 1

BENTUK_FOLDER = re.compile(r"^\d+ - ")


class TargetTidakSah(ValueError):
    """Folder atau berkas asal yang diminta bukan target yang diizinkan."""


def _folder_skenario() -> list[Path]:
    """Folder skenario yang boleh jadi tujuan pemasangan.

    Kosong kalau foldernya memang tidak ada, misalnya di server tempat bahan demo tidak
    ikut diunggah. Itu keadaan wajar, bukan galat, dan layar memakainya untuk mematikan
    sendiri tombol pemasangan.
    """
    if not SKENARIO.is_dir():
        return []
    return sorted(
        p
        for p in SKENARIO.iterdir()
        if p.is_dir() and BENTUK_FOLDER.match(p.name) and p.name not in DILEWATI
    )


def daftar_target() -> list[dict]:
    """Folder skenario beserta berapa foto kerusakan yang dipakainya sekarang.

    Jumlah slotnya dibaca dari isi folder, bukan dipatok di kode, supaya skenario yang
    fotonya ditambah atau dikurangi tidak perlu diikuti perubahan kode.
    """
    hasil = []
    for f in _folder_skenario():
        foto = sorted(f.glob("kerusakan-*"))
        pasangan = (
            [n for n in PASANGAN_SAMA if n != f.name] if f.name in PASANGAN_SAMA else []
        )
        hasil.append({
            "folder": f.name,
            "slot": [
                {"nomor": i + 1, "berkas": p.name} for i, p in enumerate(foto)
            ],
            # Folder lain yang ikut ditimpa bersamaan, ditampilkan supaya tidak mengejutkan.
            "ikut": pasangan,
        })
    return hasil


def pasang(asal: str, folder: str, slot: int) -> list[str]:
    """Salin satu foto ke slot yang dituju, beserta folder pasangannya kalau ada.

    Berkas lama di slot itu dibuang lebih dulu apa pun akhirannya. Tanpa itu, memasang
    berkas `.png` di atas `.jpg` menyisakan dua foto di satu slot dan skenarionya berubah
    tanpa disadari.
    """
    berkas = (AKAR / asal).resolve()
    if not berkas.is_file() or not berkas.is_relative_to(SUMBER.resolve()):
        raise TargetTidakSah(f"Berkas asal harus berada di dalam {SUMBER.name}")

    nama_folder = [f.name for f in _folder_skenario()]
    if folder not in nama_folder:
        raise TargetTidakSah(f"Folder {folder} bukan folder skenario")

    tujuan = [folder]
    if folder in PASANGAN_SAMA and slot == SLOT_BERPASANGAN:
        tujuan += [n for n in PASANGAN_SAMA if n != folder and n in nama_folder]

    ditulis = []
    for nama in tujuan:
        f = SKENARIO / nama
        for lama in f.glob(f"kerusakan-{slot:02d}.*"):
            lama.unlink()
        baru = f / f"kerusakan-{slot:02d}{berkas.suffix.lower()}"
        shutil.copy(berkas, baru)
        ditulis.append(f"{nama}/{baru.name}")
    return ditulis
