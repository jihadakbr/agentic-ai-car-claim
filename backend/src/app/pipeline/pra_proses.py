"""Merapikan foto sebelum masuk ke model deteksi.

Tiga hal terjadi di sini, dan ketiganya murni perhitungan tanpa AI:

1. Foto diputar tegak sesuai catatan orientasi kamera. HP menyimpan foto dalam posisi
   sensornya lalu menambahkan catatan arah putarnya, dan mengabaikan catatan itu membuat
   model deteksi menerima mobil dalam posisi miring.
2. Foto diperkecil, karena model bekerja di resolusi jauh lebih rendah dari foto asli.
3. Sidik jari isi gambar dihitung, dipakai mendeteksi foto yang dipakai ulang dari klaim
   lain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import imagehash
import numpy as np
from PIL import ExifTags, Image, ImageOps

SISI_TERPANJANG = 1280

# Nomor tag EXIF yang dipetakan ke nama yang bisa dibaca manusia.
_TAG = {v: k for k, v in ExifTags.TAGS.items()}
_TAG_DIPAKAI = ("DateTimeOriginal", "Make", "Model", "Software")


@dataclass
class FotoSiap:
    gambar: Image.Image
    phash: str
    exif: dict = field(default_factory=dict)
    lebar_asli: int = 0
    tinggi_asli: int = 0
    ketajaman: float = 0.0


def baca_exif(gambar: Image.Image) -> dict:
    """Ambil metadata yang berguna saja, bukan seluruh isi EXIF.

    Yang diambil terbatas pada waktu pengambilan dan identitas perangkat. Selain hemat
    tempat, ini juga menghindari menyimpan koordinat lokasi yang tidak dibutuhkan sistem.
    """
    try:
        mentah = gambar.getexif()
    except (AttributeError, OSError):
        return {}
    if not mentah:
        return {}

    hasil = {}
    for nama in _TAG_DIPAKAI:
        nomor = _TAG.get(nama)
        if nomor is None:
            continue
        nilai = mentah.get(nomor)
        if nilai not in (None, ""):
            hasil[nama] = str(nilai).strip()
    return hasil


def perkecil(gambar: Image.Image, sisi_terpanjang: int = SISI_TERPANJANG) -> Image.Image:
    """Perkecil sambil menjaga perbandingan sisi. Foto yang sudah kecil dibiarkan."""
    lebar, tinggi = gambar.size
    terpanjang = max(lebar, tinggi)
    if terpanjang <= sisi_terpanjang:
        return gambar
    skala = sisi_terpanjang / terpanjang
    return gambar.resize((round(lebar * skala), round(tinggi * skala)), Image.LANCZOS)


def ketajaman(gambar: Image.Image) -> float:
    """Seberapa tajam gambarnya, dari sebaran perubahan terang antar piksel bertetangga.

    Foto buram tidak punya tepi yang tegas, jadi perubahannya kecil dan sebarannya sempit.
    Dihitung sendiri tanpa model, sehingga tetap bekerja walau detektornya kebetulan yakin
    pada foto yang manusianya sendiri tidak bisa membacanya.

    Dihitung setelah foto diperkecil, karena nilainya ikut berubah oleh ukuran gambar dan
    ambangnya ditetapkan pada ukuran itu.
    """
    g = np.asarray(gambar.convert("L"), dtype=np.float32)
    if min(g.shape) < 3:
        return 0.0
    tepi = (
        4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    )
    return float(tepi.var())


def sidik_jari(gambar: Image.Image) -> str:
    """Sidik jari isi gambar, bukan isi berkas.

    Berbeda dari hash berkas biasa, nilainya nyaris tidak berubah kalau foto disimpan ulang
    dengan kualitas berbeda. Itu yang membuatnya bisa mengenali foto klaim lama yang dibuka
    lalu disimpan ulang untuk diajukan sebagai klaim baru.
    """
    return str(imagehash.phash(gambar))


def siapkan(gambar: Image.Image, sisi_terpanjang: int = SISI_TERPANJANG) -> FotoSiap:
    exif = baca_exif(gambar)
    lebar_asli, tinggi_asli = gambar.size

    tegak = ImageOps.exif_transpose(gambar)
    if tegak.mode != "RGB":
        tegak = tegak.convert("RGB")

    kecil = perkecil(tegak, sisi_terpanjang)
    return FotoSiap(
        gambar=kecil,
        phash=sidik_jari(kecil),
        exif=exif,
        lebar_asli=lebar_asli,
        tinggi_asli=tinggi_asli,
        ketajaman=ketajaman(kecil),
    )


def siapkan_berkas(jalur: Path, sisi_terpanjang: int = SISI_TERPANJANG) -> FotoSiap:
    with Image.open(jalur) as gambar:
        return siapkan(gambar, sisi_terpanjang)
