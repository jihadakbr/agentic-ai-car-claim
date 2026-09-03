"""Uji penumpukan mask bagian dengan mask kerusakan.

Mask dibuat dari kotak-kotak sederhana supaya luasnya bisa dihitung tangan. Kalau uji ini
memakai mask hasil model sungguhan, angka harapannya jadi tidak bisa diperiksa manusia dan
uji itu berhenti membuktikan apa pun.
"""

import numpy as np
import pytest

from app.pipeline.overlay import (
    ArahHadap,
    MaskDeteksi,
    arah_hadap,
    pusat_kendaraan,
    pusat_x,
    ringkas_antar_foto,
    samakan_sisi,
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


def sisi_dari(part: list[MaskDeteksi], indeks: int) -> str | None:
    """Sisi satu bagian, dihitung seperti `tumpuk` menghitungnya."""
    return tentukan_sisi(
        part[indeks].kelas, part[indeks].mask, pusat_kendaraan(part), arah_hadap(part)
    )


def mobil_dari_depan() -> list[MaskDeteksi]:
    """Kap mesin dan dua lampu depan, tanpa penanda belakang sama sekali."""
    return [
        MaskDeteksi("Hood", 0.9, kotak(40, 0, 160, 40)),
        MaskDeteksi("Headlight", 0.9, kotak(45, 40, 75, 60)),
        MaskDeteksi("Headlight", 0.9, kotak(125, 40, 155, 60)),
    ]


def mobil_dari_belakang() -> list[MaskDeteksi]:
    return [
        MaskDeteksi("Trunk", 0.9, kotak(40, 0, 160, 40)),
        MaskDeteksi("Tail-light", 0.9, kotak(45, 40, 75, 60)),
        MaskDeteksi("Tail-light", 0.9, kotak(125, 40, 155, 60)),
    ]


def mobil_serong(moncong_di_kiri: bool) -> list[MaskDeteksi]:
    """Mobil dilihat menyerong, ujung depan dan belakang terpisah jauh mendatar."""
    depan, belakang = (20, 150) if moncong_di_kiri else (150, 20)
    return [
        MaskDeteksi("Hood", 0.9, kotak(depan, 10, depan + 30, 40)),
        MaskDeteksi("Headlight", 0.9, kotak(depan, 40, depan + 25, 60)),
        MaskDeteksi("Trunk", 0.9, kotak(belakang, 10, belakang + 30, 40)),
        MaskDeteksi("Back-window", 0.9, kotak(belakang, 40, belakang + 25, 60)),
        MaskDeteksi("Fender", 0.9, kotak(depan - 5, 60, depan + 35, 80)),
        MaskDeteksi("Quarter-panel", 0.9, kotak(belakang - 5, 60, belakang + 35, 80)),
    ]


def mobil_samping_separuh_depan(moncong_di_kiri: bool) -> list[MaskDeteksi]:
    """Separuh depan mobil dari samping, tanpa satu pun bagian belakang di foto."""
    ujung, badan = (20, 120) if moncong_di_kiri else (150, 20)
    return [
        MaskDeteksi("Hood", 0.9, kotak(ujung, 10, ujung + 30, 35)),
        MaskDeteksi("Headlight", 0.9, kotak(ujung, 35, ujung + 25, 55)),
        MaskDeteksi("Fender", 0.9, kotak(ujung, 55, ujung + 30, 80)),
        MaskDeteksi("Front-door", 0.9, kotak(badan, 30, badan + 60, 70)),
        MaskDeteksi("Rocker-panel", 0.9, kotak(badan, 70, badan + 60, 85)),
    ]


def test_dilihat_dari_belakang_kiri_mobil_ada_di_kiri_foto():
    """Berdiri di belakang mobil, sisi kirinya memang ada di sebelah kiri kita."""
    part = mobil_dari_belakang()
    assert sisi_dari(part, 1) == "kiri"
    assert sisi_dari(part, 2) == "kanan"


def test_dilihat_dari_depan_kiri_mobil_pindah_ke_kanan_foto():
    """Maju ke depan mobil dan keduanya bertukar. Ini yang dulu salah."""
    part = mobil_dari_depan()
    assert sisi_dari(part, 1) == "kanan"
    assert sisi_dari(part, 2) == "kiri"


def test_foto_serong_memberi_satu_sisi_yang_sama_ke_semua_bagian():
    """Yang terlihat cuma satu sisi mobil, jadi membelahnya per posisi di foto keliru."""
    part = mobil_serong(moncong_di_kiri=True)

    # Fender di ujung kiri gambar, quarter panel di ujung kanan, tapi keduanya sisi kiri.
    assert sisi_dari(part, 4) == "kiri"
    assert sisi_dari(part, 5) == "kiri"


def test_foto_serong_dengan_moncong_di_kanan_memberi_sisi_kanan():
    part = mobil_serong(moncong_di_kiri=False)
    assert sisi_dari(part, 4) == "kanan"
    assert sisi_dari(part, 5) == "kanan"


def test_foto_samping_tanpa_bagian_belakang_tetap_terbaca_serong():
    """Separuh depan mobil dari samping. Dulu dikira tampak depan lurus, lalu sisinya
    dibelah per posisi di foto sehingga satu mobil dapat kiri dan kanan sekaligus."""
    part = mobil_samping_separuh_depan(moncong_di_kiri=False)
    assert arah_hadap(part) == ArahHadap("serong", "kanan")
    assert {sisi_dari(part, i) for i in range(2, len(part))} == {"kanan"}


def test_foto_samping_dengan_moncong_di_kiri_memberi_sisi_kiri():
    part = mobil_samping_separuh_depan(moncong_di_kiri=True)
    assert arah_hadap(part) == ArahHadap("serong", "kiri")
    assert {sisi_dari(part, i) for i in range(2, len(part))} == {"kiri"}


def test_foto_samping_separuh_belakang_ikut_terbaca_serong():
    """Buritan di kanan foto berarti moncongnya di kiri, jadi sisi kiri yang terlihat."""
    part = [
        MaskDeteksi("Trunk", 0.9, kotak(150, 10, 180, 35)),
        MaskDeteksi("Tail-light", 0.9, kotak(155, 35, 180, 55)),
        MaskDeteksi("Quarter-panel", 0.9, kotak(150, 55, 180, 80)),
        MaskDeteksi("Back-door", 0.9, kotak(20, 30, 80, 70)),
        MaskDeteksi("Rocker-panel", 0.9, kotak(20, 70, 80, 85)),
    ]
    assert arah_hadap(part) == ArahHadap("serong", "kiri")
    assert sisi_dari(part, 2) == "kiri"


def test_tampak_depan_lurus_tidak_ikut_terbaca_serong():
    """Pintu yang ikut terlihat sedikit di kedua sisi tidak menggeser titik tengahnya."""
    part = [
        MaskDeteksi("Hood", 0.9, kotak(40, 0, 160, 40)),
        MaskDeteksi("Headlight", 0.9, kotak(45, 40, 75, 60)),
        MaskDeteksi("Headlight", 0.9, kotak(125, 40, 155, 60)),
        MaskDeteksi("Front-door", 0.9, kotak(30, 40, 45, 80)),
        MaskDeteksi("Front-door", 0.9, kotak(155, 40, 170, 80)),
    ]
    assert arah_hadap(part) == ArahHadap("depan")
    assert sisi_dari(part, 1) == "kanan"
    assert sisi_dari(part, 2) == "kiri"


def test_bagian_yang_cuma_ada_satu_tidak_pernah_diberi_sisi():
    """Kap mesin cuma ada satu per mobil, jadi label kiri atau kanan pasti salah."""
    assert sisi_dari(mobil_dari_depan(), 0) is None
    assert sisi_dari(mobil_serong(moncong_di_kiri=True), 0) is None


def test_sisi_kosong_kalau_arah_hadap_tidak_terbaca():
    """Close-up fender tanpa lampu, kap, bagasi, atau roda. Menebak di sini tidak berdasar."""
    part = [MaskDeteksi("Fender", 0.9, kotak(20, 20, 80, 60))]
    assert arah_hadap(part) is None
    assert sisi_dari(part, 0) is None


def test_bagian_yang_membentang_di_tengah_tidak_diberi_sisi():
    """Spion yang mask-nya menutupi tengah mobil tidak dipaksa punya sisi."""
    part = [
        MaskDeteksi("Hood", 0.9, kotak(40, 0, 160, 40)),
        MaskDeteksi("Mirror", 0.9, kotak(40, 40, 160, 60)),
    ]
    assert sisi_dari(part, 1) is None


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
    assert jumlah_foto[("Headlight", "kiri")] == 1


def test_sisi_kosong_diisi_dari_foto_lain_supaya_tidak_tertagih_dua_kali():
    """Fender yang sama tidak boleh jadi dua baris cuma karena satu foto tidak jelas arahnya."""
    jelas = mobil_serong(moncong_di_kiri=True)
    fender = jelas[4]
    kabur = [MaskDeteksi("Fender", 0.9, fender.mask)]
    penyok = [MaskDeteksi("Dent", 0.9, kotak(20, 60, 40, 80))]

    per_foto = samakan_sisi([tumpuk(jelas, penyok), tumpuk(kabur, penyok)])
    hasil, jumlah_foto = ringkas_antar_foto(per_foto)

    assert [t.sisi for t in hasil if t.part_class == "Fender"] == ["kiri"]
    assert jumlah_foto[("Fender", "kiri")] == 2


def test_dua_fender_yang_benar_benar_rusak_tetap_dua_baris():
    """Penyeragaman sisi tidak boleh menggabungkan bagian yang memang ada dua."""
    part = mobil_dari_depan()
    lampu = [
        MaskDeteksi("Broken part", 0.9, kotak(45, 40, 75, 60)),
        MaskDeteksi("Broken part", 0.9, kotak(125, 40, 155, 60)),
    ]

    hasil, _ = ringkas_antar_foto(samakan_sisi([tumpuk(part, lampu)]))
    headlamp = [t for t in hasil if t.part_class == "Headlight"]

    assert {t.sisi for t in headlamp} == {"kiri", "kanan"}


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
