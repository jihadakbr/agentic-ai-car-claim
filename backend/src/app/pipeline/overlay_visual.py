"""Menggambar hasil deteksi ke atas foto.

Tanpa ini, adjuster memutuskan klaim dari tabel angka tanpa pernah bisa memeriksa apakah
model benar-benar melihat kerusakan yang dimaksud. Angka rasio luas 96% tidak berarti apa
pun kalau ternyata model menandai bagian yang salah.

Gambarnya dibuat di server, bukan di browser, supaya hasilnya sama di layar mana pun dan
tetap benar setelah model sungguhan dipasang menggantikan detektor contoh.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.pipeline.overlay import MaskDeteksi

# Biru untuk bagian mobil, merah untuk kerusakan. Dua warna saja, karena menambah warna
# ketiga membuat gambarnya perlu dijelaskan lebih dulu sebelum bisa dibaca.
WARNA_PART = (37, 99, 235)
WARNA_DAMAGE = (220, 38, 38)

TEBAL_GARIS = 3
KEPEKATAN_ISI = 0.35


def _font(ukuran: int) -> ImageFont.ImageFont:
    for nama in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(nama, ukuran)
        except OSError:
            continue
    return ImageFont.load_default()


def _tepi(mask: np.ndarray) -> np.ndarray:
    """Ambil garis tepi mask dengan menggesernya satu piksel ke empat arah.

    Cara ini dipilih supaya tidak perlu OpenCV. Hasilnya cukup untuk garis setebal beberapa
    piksel, dan yang dibutuhkan di sini memang cuma garis, bukan bentuk polygon yang presisi.
    """
    m = mask.astype(bool)
    dalam = (
        np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1)
    )
    return m & ~dalam


def _tebalkan(tepi: np.ndarray, tebal: int) -> np.ndarray:
    hasil = tepi.copy()
    for geser in range(1, tebal):
        hasil |= np.roll(tepi, geser, 0) | np.roll(tepi, -geser, 0)
        hasil |= np.roll(tepi, geser, 1) | np.roll(tepi, -geser, 1)
    return hasil


def _kotak(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """Kotak batas mask, dipakai menaruh label dan disimpan untuk keperluan nanti."""
    baris, kolom = np.nonzero(mask)
    if baris.size == 0:
        return None
    return int(kolom.min()), int(baris.min()), int(kolom.max()), int(baris.max())


def kotak_batas(mask: np.ndarray) -> list[int] | None:
    hasil = _kotak(mask)
    return list(hasil) if hasil else None


def _warnai(petak: np.ndarray, mask: np.ndarray, warna: tuple[int, int, int],
            kepekatan: float) -> None:
    """Campur warna ke piksel yang tertutup mask, di tempat."""
    pilih = mask.astype(bool)
    if not pilih.any():
        return
    asal = petak[pilih].astype(np.float32)
    campur = asal * (1 - kepekatan) + np.array(warna, dtype=np.float32) * kepekatan
    petak[pilih] = campur.astype(np.uint8)


def _kena_kerusakan(p: MaskDeteksi, damage: list[MaskDeteksi]) -> bool:
    """Apakah bagian ini benar-benar bersinggungan dengan salah satu mask kerusakan.

    Bagian yang mulus tidak digambar sama sekali. Menggambar semua bagian membuat foto
    penuh kotak biru yang tidak satu pun jadi biaya, dan kerusakannya justru tenggelam.
    """
    return any(
        d.mask.shape == p.mask.shape and bool((p.mask.astype(bool) & d.mask.astype(bool)).any())
        for d in damage
    )


def gambar(
    foto: Image.Image,
    part: list[MaskDeteksi],
    damage: list[MaskDeteksi],
    bagian_diabaikan: frozenset[str] = frozenset(),
    contoh: bool = False,
) -> Image.Image:
    """Salin foto lalu gambari mask bagian dan mask kerusakan di atasnya.

    Foto aslinya tidak disentuh, karena adjuster perlu membandingkan keduanya.
    """
    dasar = foto.convert("RGB")
    petak = np.array(dasar)
    tinggi, lebar = petak.shape[:2]

    dipakai = [
        p
        for p in part
        if p.kelas not in bagian_diabaikan and p.luas > 0 and _kena_kerusakan(p, damage)
    ]

    # Kerusakan diarsir lebih dulu supaya garis tepi bagian tetap terlihat di atasnya.
    for d in damage:
        if d.mask.shape != (tinggi, lebar):
            continue
        _warnai(petak, d.mask, WARNA_DAMAGE, KEPEKATAN_ISI)

    for p in dipakai:
        if p.mask.shape != (tinggi, lebar):
            continue
        _warnai(petak, _tebalkan(_tepi(p.mask), TEBAL_GARIS), WARNA_PART, 1.0)

    for d in damage:
        if d.mask.shape != (tinggi, lebar):
            continue
        _warnai(petak, _tebalkan(_tepi(d.mask), TEBAL_GARIS), WARNA_DAMAGE, 1.0)

    hasil = Image.fromarray(petak)
    d_gambar = ImageDraw.Draw(hasil)
    f = _font(max(13, lebar // 60))

    for p in dipakai:
        kotak = _kotak(p.mask)
        if kotak is None:
            continue
        x0, y0, _, _ = kotak
        teks = f"{p.kelas} {p.confidence:.0%}"
        _label(d_gambar, (x0 + 4, max(2, y0 + 4)), teks, WARNA_PART, f)

    for d in damage:
        kotak = _kotak(d.mask)
        if kotak is None:
            continue
        _, _, x1, y1 = kotak
        teks = f"{d.kelas} {d.confidence:.0%}"
        _label(d_gambar, (max(2, x1 - 160), max(2, y1 - 26)), teks, WARNA_DAMAGE, f)

    if contoh:
        _tanda_contoh(d_gambar, lebar, _font(max(15, lebar // 45)))
    return hasil


def _tanda_contoh(d: ImageDraw.ImageDraw, lebar: int, f) -> None:
    """Tandai gambar yang bentuknya bukan hasil model.

    Detektor contoh menaruh bentuk di posisi tetap tanpa membaca isi foto. Tanpa penanda,
    gambarnya terlihat persis seperti hasil deteksi sungguhan dan gampang disalahartikan
    saat presentasi.
    """
    teks = "CONTOH, bukan hasil model"
    kotak = d.textbbox((0, 0), teks, font=f)
    x = max(8, lebar - (kotak[2] - kotak[0]) - 24)
    d.rectangle([x - 8, 8, x + (kotak[2] - kotak[0]) + 8, 16 + (kotak[3] - kotak[1])],
                fill=(180, 83, 9))
    d.text((x, 12), teks, font=f, fill=(255, 255, 255))


def _label(d: ImageDraw.ImageDraw, posisi, teks: str, warna, f) -> None:
    """Tulis label di atas kotak berwarna, supaya tetap terbaca di foto terang maupun gelap."""
    x, y = posisi
    kotak = d.textbbox((x, y), teks, font=f)
    d.rectangle([kotak[0] - 4, kotak[1] - 3, kotak[2] + 4, kotak[3] + 3], fill=warna)
    d.text((x, y), teks, font=f, fill=(255, 255, 255))


