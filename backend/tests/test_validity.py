"""Uji tujuh pemeriksaan anti-kecurangan.

Tiap pemeriksaan diuji dua arah: kasus yang seharusnya lolos, dan kasus yang seharusnya
gagal. Pemeriksaan yang cuma diuji pada kasus lolos tidak membuktikan apa-apa, karena
fungsi yang selalu mengembalikan "lolos" juga akan lulus uji itu.
"""

import pytest

from app.pipeline.validity import (
    HARD,
    INVALID,
    PERLU_REVIEW,
    SOFT,
    VALID,
    Ambang,
    DataPolis,
    FotoKerusakan,
    HasilStnk,
    TemuanFoto,
    TemuanKlaim,
    TemuanRiwayat,
    cek_c1_ada_kerusakan,
    cek_c2_foto_tidak_dipakai_ulang,
    cek_c3_konsisten_antar_sudut,
    cek_c4_plat_cocok_stnk,
    cek_c5_stnk_terbaca,
    cek_c6_stnk_cocok_polis,
    cek_c7_bagian_pernah_diklaim,
    jalankan_semua,
    jarak_hamming_hex,
    kemiripan_nama,
    normalkan_plat,
    tentukan_verdict,
)

AMBANG = Ambang()


def foto_sehat(id_: str, phash: str = "9f8a3c2d1e0b7654", plat: str | None = "B 1234 XYZ"):
    return FotoKerusakan(
        id=id_,
        phash=phash,
        confidence_kendaraan=0.94,
        plat_terbaca=plat,
        temuan=[
            TemuanFoto("Front-bumper", "Broken part", 0.88),
            TemuanFoto("Hood", "Dent", 0.81),
        ],
    )


@pytest.fixture
def empat_foto():
    return [foto_sehat(f"f{i}", phash=f"9f8a3c2d1e0b765{i}") for i in range(4)]


@pytest.fixture
def stnk_benar():
    return HasilStnk(
        merk="TOYOTA",
        tipe="F601RM GMMFJJ",
        tahun=2013,
        nomor_polisi="B 1234 XYZ",
        nomor_rangka="MHKM1BA3JDK012345",
        nomor_mesin="1NRF012345",
        nama_pemilik="BUDI SANTOSO",
    )


@pytest.fixture
def polis_benar():
    return DataPolis(
        nomor_polisi="B 1234 XYZ",
        nomor_rangka="MHKM1BA3JDK012345",
        nomor_mesin="1NRF012345",
        nama_pemegang="BUDI SANTOSO",
    )


def test_normalkan_plat_menyamakan_bentuk():
    assert normalkan_plat("B 1234 XYZ") == "B1234XYZ"
    assert normalkan_plat("b-1234-xyz") == "B1234XYZ"
    assert normalkan_plat(None) == ""


def test_jarak_hamming_mengenali_gambar_sama():
    assert jarak_hamming_hex("9f8a3c2d1e0b7654", "9f8a3c2d1e0b7654") == 0
    assert jarak_hamming_hex("9f8a3c2d1e0b7654", "9f8a3c2d1e0b7655") == 1
    # Bukan heksadesimal berarti tidak bisa dibandingkan, bukan berarti berbeda.
    assert jarak_hamming_hex("bukanhex!!", "9f8a3c2d1e0b7654") is None


def test_kemiripan_nama_toleran_pada_beda_kecil():
    assert kemiripan_nama("BUDI SANTOSO", "BUDI SANTOSO") == 1.0
    assert kemiripan_nama("BUDI SANTOSO", "budi  santoso") == 1.0
    assert kemiripan_nama("BUDI SANTOSO", "BUDI SANTOSA") > 0.9
    assert kemiripan_nama("BUDI SANTOSO", "AGUS PRASETYO") < 0.5


def test_foto_ruangan_tetap_tertahan_lewat_c1(empat_foto):
    """Penyaring foto yang bukan mobil sekarang ada di cek kerusakan, bukan cek tersendiri.

    Foto ruangan atau tangkapan layar tidak menghasilkan kerusakan apa pun, dan itu yang
    ditangkapnya. Yang berubah cuma jalurnya, bukan ada tidaknya penyaring.
    """
    for f in empat_foto:
        f.temuan = []

    hasil = cek_c1_ada_kerusakan(empat_foto, AMBANG)

    assert hasil.lolos is False
    assert hasil.tingkat == HARD


def test_c1_gagal_kalau_mobilnya_mulus(empat_foto):
    for f in empat_foto:
        f.temuan = []
    hasil = cek_c1_ada_kerusakan(empat_foto, AMBANG)
    assert hasil.lolos is False
    assert hasil.tingkat == HARD


def test_c1_mengabaikan_deteksi_di_bawah_ambang(empat_foto):
    """Deteksi dengan keyakinan rendah tidak dihitung sebagai kerusakan."""
    for f in empat_foto:
        f.temuan = [TemuanFoto("Hood", "Dent", 0.10)]
    assert cek_c1_ada_kerusakan(empat_foto, AMBANG).lolos is False


def test_c2_lolos_kalau_foto_belum_pernah_ada(empat_foto):
    assert cek_c2_foto_tidak_dipakai_ulang(empat_foto, {}, AMBANG).lolos is True


def test_c2_gagal_telak_kalau_foto_identik_dengan_klaim_lain(empat_foto):
    lain = {"9f8a3c2d1e0b7652": "KLM-2024-0118"}
    hasil = cek_c2_foto_tidak_dipakai_ulang(empat_foto, lain, AMBANG)
    assert hasil.lolos is False
    assert hasil.tingkat == HARD
    assert "KLM-2024-0118" in hasil.alasan


def test_c2_menandai_foto_yang_cuma_mirip(empat_foto):
    """Foto hasil simpan ulang berubah sedikit, jadi ditandai untuk dilihat manusia."""
    lain = {"9f8a3c2d1e0b76f2": "KLM-2024-0118"}
    hasil = cek_c2_foto_tidak_dipakai_ulang(empat_foto, lain, AMBANG)
    assert hasil.tingkat == SOFT


def test_c2_foto_tanpa_sidik_jari_dilewati():
    foto = [FotoKerusakan(id="f1", phash=None, confidence_kendaraan=0.9)]
    assert cek_c2_foto_tidak_dipakai_ulang(foto, {"abc": "X"}, AMBANG).lolos is True


def test_c3_menandai_bagian_yang_cuma_terlihat_sekali(empat_foto):
    empat_foto[0].temuan.append(TemuanFoto("Headlight", "Broken part", 0.9, sisi="kanan"))
    hasil = cek_c3_konsisten_antar_sudut(empat_foto, AMBANG)
    assert hasil.lolos is False
    assert hasil.tingkat == SOFT
    assert "Headlight" in hasil.alasan
    assert "sisi kanan" in hasil.alasan


def test_c3_dilewati_kalau_fotonya_sedikit(empat_foto):
    """Untuk tiga foto, wajar satu bagian cuma tertangkap sekali. Memeriksanya = tuduhan palsu."""
    tiga = empat_foto[:3]
    tiga[0].temuan.append(TemuanFoto("Headlight", "Broken part", 0.9))
    hasil = cek_c3_konsisten_antar_sudut(tiga, AMBANG)
    assert hasil.lolos is True
    assert "dilewati" in hasil.alasan


def test_c4_lolos_kalau_plat_sama(empat_foto, stnk_benar):
    assert cek_c4_plat_cocok_stnk(empat_foto, stnk_benar).lolos is True


def test_c4_gagal_telak_kalau_plat_jelas_beda(empat_foto, stnk_benar):
    for f in empat_foto:
        f.plat_terbaca = "B 5678 ABC"
    hasil = cek_c4_plat_cocok_stnk(empat_foto, stnk_benar)
    assert hasil.lolos is False
    assert hasil.tingkat == HARD


def test_c4_beda_satu_karakter_dianggap_salah_baca(empat_foto, stnk_benar):
    """Angka 8 dan huruf B sering tertukar pada plat kotor. Jangan tolak klaim karena itu."""
    for f in empat_foto:
        f.plat_terbaca = "B 1234 XY2"
    hasil = cek_c4_plat_cocok_stnk(empat_foto, stnk_benar)
    assert hasil.tingkat == SOFT
    assert "salah baca" in hasil.alasan


def test_c4_memakai_bacaan_terbaik_dari_semua_foto(empat_foto, stnk_benar):
    """Satu foto bisa terbaca lebih baik dari lainnya, dan itu yang dipakai."""
    empat_foto[0].plat_terbaca = "B 9999 QQQ"
    empat_foto[1].plat_terbaca = "B 1234 XYZ"
    assert cek_c4_plat_cocok_stnk(empat_foto, stnk_benar).lolos is True


def test_c4_plat_tidak_terbaca_jadi_tanda_bukan_penolakan(empat_foto, stnk_benar):
    """Plat tertutup lumpur di lokasi kejadian tidak boleh membuat klaim ditolak."""
    for f in empat_foto:
        f.plat_terbaca = None
    hasil = cek_c4_plat_cocok_stnk(empat_foto, stnk_benar)
    assert hasil.tingkat == SOFT


def test_c5_lolos_untuk_stnk_wajar(stnk_benar):
    assert cek_c5_stnk_terbaca(stnk_benar).lolos is True


def test_c5_gagal_telak_kalau_field_wajib_kosong(stnk_benar):
    stnk_benar.merk = None
    hasil = cek_c5_stnk_terbaca(stnk_benar)
    assert hasil.tingkat == HARD
    assert "merk" in hasil.detail["field_kosong"]


def test_c5_menandai_nomor_rangka_janggal(stnk_benar):
    stnk_benar.nomor_rangka = "MHKM1BA3JD"
    hasil = cek_c5_stnk_terbaca(stnk_benar)
    assert hasil.tingkat == SOFT
    assert "janggal" in hasil.alasan


def test_c5_menandai_tahun_tidak_cocok_kode_rangka(stnk_benar):
    stnk_benar.tahun = 2016
    hasil = cek_c5_stnk_terbaca(stnk_benar)
    assert hasil.tingkat == SOFT
    assert "tidak wajib diikuti semua pabrikan" in hasil.alasan


def test_c6_lolos_kalau_semua_cocok(stnk_benar, polis_benar):
    assert cek_c6_stnk_cocok_polis(stnk_benar, polis_benar, AMBANG).lolos is True


def test_c6_gagal_telak_kalau_nomor_rangka_beda(stnk_benar, polis_benar):
    stnk_benar.nomor_rangka = "MHKM1BA3JDK099887"
    hasil = cek_c6_stnk_cocok_polis(stnk_benar, polis_benar, AMBANG)
    assert hasil.lolos is False
    assert hasil.tingkat == HARD


def test_c6_nomor_polisi_beda_cuma_ditandai(stnk_benar, polis_benar):
    """Nomor polisi bisa berubah karena mutasi daerah, jadi bukan penolakan."""
    stnk_benar.nomor_polisi = "D 4411 KLM"
    hasil = cek_c6_stnk_cocok_polis(stnk_benar, polis_benar, AMBANG)
    assert hasil.tingkat == SOFT
    assert "nomor polisi berbeda" in hasil.alasan


def test_c6_salah_baca_nama_satu_huruf_tetap_lolos(stnk_benar, polis_benar):
    stnk_benar.nama_pemilik = "BUDI SANTOSA"
    assert cek_c6_stnk_cocok_polis(stnk_benar, polis_benar, AMBANG).lolos is True


def test_c6_nama_jauh_berbeda_ditandai(stnk_benar, polis_benar):
    stnk_benar.nama_pemilik = "AGUS PRASETYO"
    hasil = cek_c6_stnk_cocok_polis(stnk_benar, polis_benar, AMBANG)
    assert hasil.tingkat == SOFT
    assert "nama pemilik berbeda" in hasil.alasan


def test_verdict_satu_hard_fail_membuat_invalid():
    from app.pipeline.validity import HasilCek

    assert tentukan_verdict([HasilCek("C1", "x", True, None, "")]) == VALID
    assert tentukan_verdict([HasilCek("C3", "x", False, SOFT, "")]) == PERLU_REVIEW
    assert (
        tentukan_verdict([HasilCek("C3", "x", False, SOFT, ""), HasilCek("C6", "x", False, HARD, "")])
        == INVALID
    )


def test_klaim_sehat_lolos_seluruh_cek(empat_foto, stnk_benar, polis_benar):
    """Urutan dan kode pemeriksaan ikut dijaga, karena keduanya tampil di layar adjuster."""
    hasil, verdict = jalankan_semua(empat_foto, stnk_benar, polis_benar, {})
    assert verdict == VALID
    assert [h.kode for h in hasil] == ["C1", "C2", "C3", "C4", "C5", "C6", "C7"]
    assert all(h.lolos for h in hasil)


def test_semua_cek_tetap_dijalankan_meski_ada_yang_gagal(empat_foto, stnk_benar, polis_benar):
    """Adjuster perlu gambaran utuh, bukan cuma pemeriksaan pertama yang kebetulan gagal."""
    for f in empat_foto:
        f.temuan = []
    stnk_benar.nomor_rangka = "MHKM1BA3JDK099887"

    hasil, verdict = jalankan_semua(empat_foto, stnk_benar, polis_benar, {})
    assert verdict == INVALID
    assert len(hasil) == 7
    gagal = {h.kode for h in hasil if not h.lolos}
    assert {"C1", "C6"} <= gagal


def test_tiap_hasil_punya_alasan_yang_bisa_dibaca(empat_foto, stnk_benar, polis_benar):
    """Alasannya muncul apa adanya di layar adjuster, jadi tidak boleh kosong."""
    hasil, _ = jalankan_semua(empat_foto, stnk_benar, polis_benar, {})
    for h in hasil:
        assert h.alasan.strip(), h.kode
        assert len(h.alasan) > 15, h.kode


def test_hasil_sama_untuk_masukan_sama(empat_foto, stnk_benar, polis_benar):
    """Sifat wajib untuk asuransi: pemeriksaan bisa diulang dan keputusannya identik."""
    def jalankan():
        return jalankan_semua(empat_foto, stnk_benar, polis_benar, {})

    a_hasil, a_verdict = jalankan()
    for _ in range(4):
        b_hasil, b_verdict = jalankan()
        assert b_verdict == a_verdict
        assert [(h.kode, h.lolos, h.alasan) for h in b_hasil] == [
            (h.kode, h.lolos, h.alasan) for h in a_hasil
        ]


# --- C7, kerusakan lama yang diklaim ulang ---


def temuan(part, damage, rasio, sisi=None):
    return TemuanKlaim(part_class=part, sisi=sisi, damage_class=damage, rasio_luas=rasio)


def riwayat(part, damage, rasio, sisi=None, nomor="KLM-2025-0031", status="ditolak"):
    return TemuanRiwayat(
        part_class=part, sisi=sisi, damage_class=damage, rasio_luas=rasio,
        nomor_klaim=nomor, status=status,
    )


def test_c7_polis_tanpa_riwayat_langsung_lolos():
    """Kendaraan yang baru pertama kali diklaim tidak punya apa pun untuk dibandingkan."""
    h = cek_c7_bagian_pernah_diklaim([temuan("Fender", "Dent", 0.22)], [], Ambang())
    assert h.lolos
    assert h.tingkat is None


def test_c7_menandai_kerusakan_dengan_luas_yang_nyaris_sama():
    """Kerusakan yang tidak pernah diperbaiki luasnya praktis tidak berubah."""
    h = cek_c7_bagian_pernah_diklaim(
        [temuan("Fender", "Dent", 0.231, sisi="kiri")],
        [riwayat("Fender", "Dent", 0.224, sisi="kiri")],
        Ambang(),
    )
    assert not h.lolos
    assert h.tingkat == SOFT
    assert "KLM-2025-0031" in h.alasan
    assert h.detail["cocok"][0]["part_class"] == "Fender"


def test_c7_luas_yang_berbeda_jauh_dianggap_kerusakan_baru():
    """Bagian yang sudah diperbaiki lalu rusak lagi punya luas yang berbeda jauh."""
    h = cek_c7_bagian_pernah_diklaim(
        [temuan("Fender", "Dent", 0.61)],
        [riwayat("Fender", "Dent", 0.12)],
        Ambang(),
    )
    assert h.lolos


def test_c7_jenis_kerusakan_berbeda_tidak_ditandai():
    """Baret tahun lalu bukan alasan menolak bagian yang sekarang pecah."""
    h = cek_c7_bagian_pernah_diklaim(
        [temuan("Fender", "Broken part", 0.22)],
        [riwayat("Fender", "Scratch", 0.22)],
        Ambang(),
    )
    assert h.lolos


def test_c7_sisi_berbeda_tidak_ditandai():
    """Fender kiri dan fender kanan dua bagian berbeda meski namanya sama."""
    h = cek_c7_bagian_pernah_diklaim(
        [temuan("Fender", "Dent", 0.22, sisi="kanan")],
        [riwayat("Fender", "Dent", 0.22, sisi="kiri")],
        Ambang(),
    )
    assert h.lolos


def test_c7_sisi_yang_kosong_cocok_dengan_sisi_mana_pun():
    """Foto yang arah hadapnya tidak terbaca tidak boleh membuat kerusakan lama lolos."""
    h = cek_c7_bagian_pernah_diklaim(
        [temuan("Fender", "Dent", 0.22)],
        [riwayat("Fender", "Dent", 0.22, sisi="kiri")],
        Ambang(),
    )
    assert not h.lolos
    assert h.tingkat == SOFT


def test_c7_riwayat_lama_tanpa_sisi_tetap_cocok():
    """Klaim yang tersimpan sebelum sisi dicatat tetap harus bisa dibandingkan."""
    h = cek_c7_bagian_pernah_diklaim(
        [temuan("Fender", "Dent", 0.22, sisi="kanan")],
        [riwayat("Fender", "Dent", 0.22)],
        Ambang(),
    )
    assert not h.lolos


def test_c7_memilih_riwayat_yang_paling_dekat():
    """Kalau ada beberapa yang cocok, yang ditunjuk harus yang luasnya paling mirip."""
    h = cek_c7_bagian_pernah_diklaim(
        [temuan("Fender", "Dent", 0.22)],
        [
            riwayat("Fender", "Dent", 0.26, nomor="KLM-2025-0010"),
            riwayat("Fender", "Dent", 0.221, nomor="KLM-2025-0031"),
        ],
        Ambang(),
    )
    assert h.detail["cocok"][0]["klaim_lama"] == "KLM-2025-0031"


def test_c7_tidak_pernah_membatalkan_klaim():
    """Kerusakan lama di satu bagian tidak membuat seluruh klaim tidak valid."""
    h = cek_c7_bagian_pernah_diklaim(
        [temuan("Fender", "Dent", 0.22)],
        [riwayat("Fender", "Dent", 0.22)],
        Ambang(),
    )
    assert h.tingkat != HARD
