"""Uji penumpukan mask bagian dengan mask kerusakan.

Mask dibuat dari kotak-kotak sederhana supaya luasnya bisa dihitung tangan. Kalau uji ini
memakai mask hasil model sungguhan, angka harapannya jadi tidak bisa diperiksa manusia dan
uji itu berhenti membuktikan apa pun.
"""

import numpy as np
import pytest

from app.pipeline.overlay import (
    MaskDeteksi,
    pusat_kendaraan,
    pusat_x,
    ringkas_antar_foto,
    tentukan_sisi,
    tumpuk,
)

TINGGI, LEBAR = 100, 200


def kotak(x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    """Mask persegi. Luasnya (x1-x0) * (y1-y0), jadi mudah diperiksa tangan."""
    m = np.zeros((TINGGI, LEBAR), dtype=bool)
    m[y0:y1, x0:x1] = True
    return m


def test_luas_mask_dihitung_benar():
    d = MaskDeteksi("Hood", 0.9, kotak(0, 0, 20, 10))
    assert d.luas == 200


def test_pusat_x_mask_kosong_bernilai_none():
    assert pusat_x(np.zeros((10, 10), dtype=bool)) is None


def test_rasio_luas_dihitung_dari_luas_part():
    """Kap mesin 100x40 = 4,000 piksel, penyok menutupi 100x18 = 1,800, jadi 45%."""
    part = [MaskDeteksi("Hood", 0.92, kotak(50, 10, 150, 50))]
    damage = [MaskDeteksi("Dent", 0.88, kotak(50, 10, 150, 28))]

    hasil = tumpuk(part, damage)

    assert len(hasil) == 1
    t = hasil[0]
    assert t.part_class == "Hood"
    assert t.damage_class == "Dent"
    assert t.luas_part_px == 4_000
    assert t.luas_irisan_px == 1_800
    assert t.rasio_luas == pytest.approx(0.45)


def test_kerusakan_yang_cuma_menyenggol_diabaikan():
    """Tanpa ambang irisan, kerusakan yang ujungnya menyentuh part tetangga ikut menagih."""
    part = [
        MaskDeteksi("Hood", 0.9, kotak(0, 0, 100, 50)),
        MaskDeteksi("Fender", 0.9, kotak(100, 0, 200, 50)),
    ]
    # Kerusakan hampir seluruhnya di kap mesin, cuma 5% masuk ke fender.
    damage = [MaskDeteksi("Dent", 0.9, kotak(5, 0, 105, 50))]

    hasil = tumpuk(part, damage, ambang_irisan=0.30)

    assert [t.part_class for t in hasil] == ["Hood"]


def test_kerusakan_bisa_menempel_ke_dua_bagian():
    """Benturan yang merusak bumper sekaligus fender memang harus dihitung dua-duanya."""
    part = [
        MaskDeteksi("Front-bumper", 0.9, kotak(0, 0, 100, 50)),
        MaskDeteksi("Fender", 0.9, kotak(100, 0, 200, 50)),
    ]
    damage = [MaskDeteksi("Dent", 0.9, kotak(50, 0, 150, 50))]

    hasil = tumpuk(part, damage, ambang_irisan=0.30)

    assert {t.part_class for t in hasil} == {"Front-bumper", "Fender"}
    for t in hasil:
        assert t.rasio_luas == pytest.approx(0.5)


def test_bagian_yang_diabaikan_tidak_ikut_dihitung():
    """Plat nomor dipakai untuk pemeriksaan identitas, bukan bagian yang bisa diklaim."""
    part = [
        MaskDeteksi("Front-bumper", 0.9, kotak(0, 0, 100, 50)),
        MaskDeteksi("License-plate", 0.9, kotak(30, 10, 70, 30)),
    ]
    damage = [MaskDeteksi("Scratch", 0.9, kotak(30, 10, 70, 30))]

    hasil = tumpuk(part, damage, bagian_diabaikan=frozenset({"License-plate"}))

    assert [t.part_class for t in hasil] == ["Front-bumper"]


def test_mask_kosong_dilewati_tanpa_error():
    part = [MaskDeteksi("Hood", 0.9, np.zeros((TINGGI, LEBAR), dtype=bool))]
    damage = [MaskDeteksi("Dent", 0.9, kotak(0, 0, 10, 10))]
    assert tumpuk(part, damage) == []


def test_sisi_ditentukan_dari_titik_tengah_mobil():
    """Titik tengah mobil dipakai, bukan titik tengah gambar, karena mobil sering tidak di tengah."""
    part = [
        MaskDeteksi("Hood", 0.9, kotak(40, 0, 160, 40)),
        MaskDeteksi("Headlight", 0.9, kotak(45, 40, 75, 60)),
        MaskDeteksi("Headlight", 0.9, kotak(125, 40, 155, 60)),
    ]
    pusat = pusat_kendaraan(part)

    assert tentukan_sisi(part[1].mask, pusat) == "kiri"
    assert tentukan_sisi(part[2].mask, pusat) == "kanan"


def test_bagian_yang_membentang_di_tengah_tidak_diberi_sisi():
    """Kap mesin membentang melewati tengah, memaksakan label kiri atau kanan menyesatkan."""
    part = [MaskDeteksi("Hood", 0.9, kotak(40, 0, 160, 40))]
    pusat = pusat_kendaraan(part)
    assert tentukan_sisi(part[0].mask, pusat) is None


def test_sisi_none_kalau_tidak_ada_acuan():
    assert tentukan_sisi(kotak(0, 0, 10, 10), None) is None


def test_dua_headlamp_jadi_dua_temuan_berbeda_sisi():
    part = [
        MaskDeteksi("Hood", 0.9, kotak(40, 0, 160, 40)),
        MaskDeteksi("Headlight", 0.9, kotak(45, 40, 75, 60)),
        MaskDeteksi("Headlight", 0.9, kotak(125, 40, 155, 60)),
    ]
    damage = [
        MaskDeteksi("Broken part", 0.9, kotak(45, 40, 75, 60)),
        MaskDeteksi("Broken part", 0.9, kotak(125, 40, 155, 60)),
    ]

    hasil = tumpuk(part, damage)
    headlamp = [t for t in hasil if t.part_class == "Headlight"]

    assert {t.sisi for t in headlamp} == {"kiri", "kanan"}


def test_ringkas_memakai_rasio_tertinggi_antar_foto():
    """Sudut yang menangkap kerusakan menyerong selalu memperkecil luasnya."""
    part = [MaskDeteksi("Hood", 0.9, kotak(50, 10, 150, 50))]

    foto1 = tumpuk(part, [MaskDeteksi("Dent", 0.9, kotak(50, 10, 150, 20))])  # 25%
    foto2 = tumpuk(part, [MaskDeteksi("Dent", 0.9, kotak(50, 10, 150, 28))])  # 45%
    foto3 = tumpuk(part, [MaskDeteksi("Dent", 0.9, kotak(50, 10, 150, 16))])  # 15%

    hasil, jumlah_foto = ringkas_antar_foto([foto1, foto2, foto3])

    assert len(hasil) == 1
    assert hasil[0].rasio_luas == pytest.approx(0.45)
    assert jumlah_foto[("Hood", None)] == 3


def test_ringkas_menghitung_foto_per_bagian_untuk_cek_konsistensi():
    """Angka ini yang dipakai cek C3 untuk menandai bagian yang cuma terlihat sekali."""
    part_depan = [
        MaskDeteksi("Hood", 0.9, kotak(40, 0, 160, 40)),
        MaskDeteksi("Headlight", 0.9, kotak(125, 40, 155, 60)),
    ]
    hanya_hood = [MaskDeteksi("Hood", 0.9, kotak(40, 0, 160, 40))]

    foto1 = tumpuk(part_depan, [
        MaskDeteksi("Dent", 0.9, kotak(40, 0, 160, 20)),
        MaskDeteksi("Broken part", 0.9, kotak(125, 40, 155, 60)),
    ])
    foto2 = tumpuk(hanya_hood, [MaskDeteksi("Dent", 0.9, kotak(40, 0, 160, 20))])
    foto3 = tumpuk(hanya_hood, [MaskDeteksi("Dent", 0.9, kotak(40, 0, 160, 20))])

    _, jumlah_foto = ringkas_antar_foto([foto1, foto2, foto3])

    assert jumlah_foto[("Hood", None)] == 3
    assert jumlah_foto[("Headlight", "kanan")] == 1


def test_ringkas_tanpa_foto_menghasilkan_daftar_kosong():
    hasil, jumlah = ringkas_antar_foto([])
    assert hasil == []
    assert jumlah == {}


def test_hasil_sama_untuk_masukan_sama():
    """Sifat wajib: rasio yang menentukan biaya tidak boleh berubah antar percobaan."""
    part = [MaskDeteksi("Hood", 0.9, kotak(50, 10, 150, 50))]
    damage = [MaskDeteksi("Dent", 0.88, kotak(50, 10, 150, 28))]

    rasio = {tumpuk(part, damage)[0].rasio_luas for _ in range(5)}
    assert len(rasio) == 1


def test_benturan_besar_mengenai_semua_bagian_yang_disapunya():
    """Ambang sisi kerusakan saja akan menolak semuanya untuk benturan yang menyapu luas.

    Tiap bagian cuma memuat sebagian kecil dari total luas kerusakan, jadi syarat "sebagian
    besar kerusakan ada di bagian ini" gagal untuk semuanya, padahal semuanya memang rusak.
    """
    part = [
        MaskDeteksi("Hood", 0.9, kotak(50, 0, 150, 30)),
        MaskDeteksi("Grille", 0.9, kotak(80, 30, 120, 50)),
        MaskDeteksi("Front-bumper", 0.9, kotak(40, 50, 160, 80)),
    ]
    # Satu benturan yang menyapu ketiganya sekaligus.
    damage = [MaskDeteksi("Broken part", 0.9, kotak(40, 0, 160, 80))]

    hasil = tumpuk(part, damage)

    assert {t.part_class for t in hasil} == {"Hood", "Grille", "Front-bumper"}
    for t in hasil:
        assert t.rasio_luas == pytest.approx(1.0)


def test_menyenggol_tetap_ditolak_meski_ada_ambang_kedua():
    """Ambang sisi bagian tidak boleh membuat sentuhan tipis ikut tertagih."""
    part = [
        MaskDeteksi("Hood", 0.9, kotak(0, 0, 100, 50)),
        MaskDeteksi("Fender", 0.9, kotak(100, 0, 200, 50)),
    ]
    damage = [MaskDeteksi("Dent", 0.9, kotak(5, 0, 105, 50))]

    hasil = tumpuk(part, damage)

    assert [t.part_class for t in hasil] == ["Hood"]
