"""Tempat foto klaim disimpan.

Dipisah jadi antarmuka karena tempat penyimpanannya berbeda antara laptop dan server. Di
laptop foto ditulis ke folder biasa. Di Hugging Face Space, folder itu terhapus setiap kali
Space dinyalakan ulang, jadi foto seluruh klaim akan hilang tanpa pemberitahuan kalau tetap
ditulis ke disk.

Dengan pemisahan ini, pindah ke penyimpanan cloud cukup mengisi variabel lingkungan, tanpa
menyentuh kode yang memproses klaim.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Protocol

from PIL import Image

MUTU_JPEG = 85


class Penyimpan(Protocol):
    """Antarmuka penyimpanan foto.

    `simpan` mengembalikan lokasi yang bisa dipakai `buka` untuk mengambilnya lagi. Bentuk
    lokasinya sengaja tidak ditentukan, karena untuk folder berupa jalur berkas dan untuk
    penyimpanan cloud berupa kunci objek.
    """

    def simpan(self, nama: str, gambar: Image.Image) -> str: ...

    def buka(self, lokasi: str) -> Image.Image: ...

    def hapus(self, lokasi: str) -> None: ...


def _ke_jpeg(gambar: Image.Image) -> bytes:
    penyangga = io.BytesIO()
    gambar.convert("RGB").save(penyangga, format="JPEG", quality=MUTU_JPEG)
    return penyangga.getvalue()


class PenyimpanFolder:
    """Menulis ke folder di disk. Dipakai saat pengembangan di laptop."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def simpan(self, nama: str, gambar: Image.Image) -> str:
        berkas = self.folder / nama
        berkas.write_bytes(_ke_jpeg(gambar))
        return str(berkas)

    def buka(self, lokasi: str) -> Image.Image:
        return Image.open(lokasi).convert("RGB")

    def hapus(self, lokasi: str) -> None:
        # Berkas yang sudah tidak ada bukan kegagalan. Penghapusan klaim tidak boleh
        # batal setengah jalan cuma karena satu foto lebih dulu hilang.
        Path(lokasi).unlink(missing_ok=True)


class PenyimpanSupabase:
    """Menulis ke Supabase Storage lewat REST API.

    BELUM DIUJI. Kodenya ditulis mengikuti dokumentasi, tapi belum pernah dijalankan ke
    akun Supabase sungguhan, jadi perlakukan sebagai rancangan sampai deploy pertama
    benar-benar dicoba.
    """

    def __init__(self, url: str, kunci: str, bucket: str):
        self.url = url.rstrip("/")
        self.kunci = kunci
        self.bucket = bucket

    def _kepala(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.kunci}", "apikey": self.kunci}

    def simpan(self, nama: str, gambar: Image.Image) -> str:
        import httpx

        alamat = f"{self.url}/storage/v1/object/{self.bucket}/{nama}"
        jawaban = httpx.post(
            alamat,
            content=_ke_jpeg(gambar),
            headers={**self._kepala(), "Content-Type": "image/jpeg", "x-upsert": "true"},
            timeout=30,
        )
        jawaban.raise_for_status()
        return nama

    def buka(self, lokasi: str) -> Image.Image:
        import httpx

        alamat = f"{self.url}/storage/v1/object/{self.bucket}/{lokasi}"
        jawaban = httpx.get(alamat, headers=self._kepala(), timeout=30)
        jawaban.raise_for_status()
        return Image.open(io.BytesIO(jawaban.content)).convert("RGB")

    def hapus(self, lokasi: str) -> None:
        import httpx

        alamat = f"{self.url}/storage/v1/object/{self.bucket}/{lokasi}"
        jawaban = httpx.delete(alamat, headers=self._kepala(), timeout=30)
        if jawaban.status_code != 404:
            jawaban.raise_for_status()


def buat_penyimpan(folder_bawaan: Path | None = None) -> Penyimpan:
    """Pilih tempat penyimpanan sesuai variabel lingkungan yang terisi.

    Pemilihannya sama seperti cara detektor dipilih: kalau pengaturannya lengkap pakai yang
    itu, kalau tidak pakai yang lokal, tanpa mengubah kode.
    """
    url = os.getenv("SUPABASE_URL")
    kunci = os.getenv("SUPABASE_KEY")
    bucket = os.getenv("SUPABASE_BUCKET")
    if url and kunci and bucket:
        return PenyimpanSupabase(url, kunci, bucket)

    folder = folder_bawaan or Path(os.getenv("FOLDER_FOTO", "data/foto-klaim"))
    return PenyimpanFolder(folder)
