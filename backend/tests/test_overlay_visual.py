"""Uji penggambaran hasil deteksi ke atas foto.

Yang dijamin di sini bukan gambarnya bagus, karena itu tidak bisa diuji otomatis, tapi
bahwa gambarnya benar-benar berubah dari foto asal, ukurannya tetap, dan tidak ada
masukan aneh yang membuatnya gagal saat presentasi.
"""

import numpy as np
from PIL import Image

from app.pipeline.overlay import MaskDeteksi
from app.pipeline.overlay_visual import gambar, kotak_batas

LEBAR, TINGGI = 400, 300


def foto() -> Image.Image:
    return Image.new("RGB", (LEBAR, TINGGI), (128, 128, 128))


def mask_kotak(x0, y0, x1, y1) -> np.ndarray:
    m = np.zeros((TINGGI, LEBAR), dtype=bool)
    m[y0:y1, x0:x1] = True
    return m


def test_ukuran_gambar_tidak_berubah():
    hasil = gambar(foto(), [MaskDeteksi("Hood", 0.93, mask_kotak(50, 40, 250, 160))], [])
    assert hasil.size == (LEBAR, TINGGI)


def test_gambar_benar_benar_berubah_dari_aslinya():
    asli = foto()
    hasil = gambar(
        asli,
        [MaskDeteksi("Hood", 0.93, mask_kotak(50, 40, 250, 160))],
        [MaskDeteksi("Dent", 0.88, mask_kotak(80, 60, 200, 140))],
    )
    assert np.any(np.array(hasil) != np.array(asli))


def test_foto_asli_tidak_ikut_tercoret():
    """Adjuster membandingkan foto asli dengan yang berlapis, jadi aslinya harus utuh."""
    asli = foto()
    sebelum = np.array(asli).copy()
    gambar(asli, [MaskDeteksi("Hood", 0.9, mask_kotak(10, 10, 100, 100))], [])
    assert np.array_equal(np.array(asli), sebelum)


def test_tanpa_temuan_tetap_menghasilkan_gambar():
    """Foto yang tidak menemukan apa pun tetap harus tampil, bukan menggagalkan klaim."""
    hasil = gambar(foto(), [], [])
    assert hasil.size == (LEBAR, TINGGI)


def test_bagian_yang_diabaikan_tidak_digambar():
    """Plat nomor bukan bagian yang diklaim, jadi tidak perlu ikut ditandai."""
    plat = [MaskDeteksi("License-plate", 0.8, mask_kotak(50, 50, 150, 100))]
    lecet = [MaskDeteksi("Scratch", 0.8, mask_kotak(60, 60, 120, 90))]

    dengan = gambar(foto(), plat, lecet)
    tanpa = gambar(foto(), plat, lecet, bagian_diabaikan=frozenset({"License-plate"}))

    assert not np.array_equal(np.array(dengan), np.array(tanpa))


def test_bagian_yang_mulus_tidak_digambar():
    """Yang perlu dilihat adjuster bagian yang rusak. Bagian mulus cuma menutupi fotonya."""
    hood = MaskDeteksi("Hood", 0.93, mask_kotak(50, 40, 250, 160))
    pintu_mulus = MaskDeteksi("Door", 0.9, mask_kotak(260, 40, 380, 200))
    penyok = [MaskDeteksi("Dent", 0.88, mask_kotak(80, 60, 200, 140))]

    tanpa_pintu = gambar(foto(), [hood], penyok)
    dengan_pintu = gambar(foto(), [hood, pintu_mulus], penyok)

    assert np.array_equal(np.array(tanpa_pintu), np.array(dengan_pintu))


def test_mask_kosong_tidak_menggagalkan():
    kosong = np.zeros((TINGGI, LEBAR), dtype=bool)
    hasil = gambar(foto(), [MaskDeteksi("Hood", 0.9, kosong)], [MaskDeteksi("Dent", 0.8, kosong)])
    assert hasil.size == (LEBAR, TINGGI)


def test_mask_beda_ukuran_dilewati_bukan_menggagalkan():
    """Ukuran mask yang tidak cocok tanda ada yang salah, tapi klaim tidak boleh berhenti."""
    salah = np.ones((50, 50), dtype=bool)
    hasil = gambar(foto(), [MaskDeteksi("Hood", 0.9, salah)], [])
    assert hasil.size == (LEBAR, TINGGI)


def test_kotak_batas_menunjuk_tepi_mask():
    assert kotak_batas(mask_kotak(50, 40, 250, 160)) == [50, 40, 249, 159]


def test_kotak_batas_mask_kosong_bernilai_none():
    assert kotak_batas(np.zeros((TINGGI, LEBAR), dtype=bool)) is None


def test_penanda_contoh_cuma_muncul_kalau_diminta():
    """Detektor contoh menaruh bentuk di posisi tetap, dan itu harus terbaca di gambarnya."""
    hood = [MaskDeteksi("Hood", 0.93, mask_kotak(50, 40, 250, 160))]
    penyok = [MaskDeteksi("Dent", 0.88, mask_kotak(80, 60, 200, 140))]

    polos = gambar(foto(), hood, penyok)
    ditandai = gambar(foto(), hood, penyok, contoh=True)

    assert not np.array_equal(np.array(polos), np.array(ditandai))
    # Penandanya di pita atas, jadi bagian bawah gambar harus tetap sama persis.
    assert np.array_equal(np.array(polos)[120:], np.array(ditandai)[120:])
