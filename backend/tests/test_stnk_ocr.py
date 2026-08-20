"""Uji pemasangan teks OCR ke field STNK.

Sebagian besar uji di sini memberi kotak teks langsung, tanpa memuat model OCR, supaya
cepat dan supaya yang diuji benar-benar logika pemasangan field. Satu uji terpisah di akhir
menjalankan model sungguhan pada STNK sintetis, dan itu yang mengukur akurasinya.
"""

import random

import pytest

from app.pipeline import stnk_generator
from app.pipeline.stnk_ocr import KotakTeks, cocokkan_label, susun

LEBAR, TINGGI = 900, 620


def kotak(*isi: tuple[str, float, float]) -> list[KotakTeks]:
    return [KotakTeks(teks=t, x=x, y=y) for t, x, y in isi]


def test_label_dan_nilai_dalam_satu_kotak():
    hasil = susun(kotak(("No. Registrasi : B 1234 XYZ", 40, 120)), LEBAR, TINGGI)
    assert hasil.stnk.nomor_polisi == "B 1234 XYZ"


def test_label_dan_nilai_terpisah_pada_baris_yang_sama():
    hasil = susun(kotak(("Merk", 40, 300), ("TOYOTA", 185, 300)), LEBAR, TINGGI)
    assert hasil.stnk.merk == "TOYOTA"


def test_label_salah_baca_tetap_dikenali():
    """OCR sering menggeser tanda baca, dan itu tidak boleh menggagalkan pembacaan."""
    hasil = susun(kotak(("No, Rangka", 500, 240), ("MHKM1BA3JDK012345", 690, 240)), LEBAR, TINGGI)
    assert hasil.stnk.nomor_rangka == "MHKM1BA3JDK012345"


def test_label_kolom_kiri_tidak_mengambil_nilai_kolom_kanan():
    """Nilai kolom kiri hilang, dan sistem harus mengakuinya hilang, bukan meminjam sebelah."""
    hasil = susun(
        kotak(("Merk", 40, 300), ("No. Mesin", 515, 300), ("1NRF012345", 690, 300)),
        LEBAR,
        TINGGI,
    )
    assert hasil.stnk.merk is None
    assert hasil.stnk.nomor_mesin == "1NRF012345"


def test_nilai_pada_baris_lain_tidak_terambil():
    hasil = susun(kotak(("Merk", 40, 300), ("TOYOTA", 185, 420)), LEBAR, TINGGI)
    assert hasil.stnk.merk is None


def test_tahun_diambil_sebagai_angka():
    hasil = susun(kotak(("Tahun Pembuatan", 515, 125), ("2013", 690, 125)), LEBAR, TINGGI)
    assert hasil.stnk.tahun == 2013


def test_tahun_yang_bukan_angka_jadi_kosong():
    hasil = susun(kotak(("Tahun Pembuatan", 515, 125), ("-", 690, 125)), LEBAR, TINGGI)
    assert hasil.stnk.tahun is None


def test_label_yang_tertelan_kotak_sebelahnya_tetap_terbaca():
    """OCR kerap menyatukan nilai kolom kiri dengan label kolom kanan jadi satu kotak."""
    gabung = KotakTeks(teks="JL KEBON JERUK NO 27 No. Rangka", x=180, y=240, lebar=380)
    nilai = KotakTeks(teks="MHKM1BA3JDK012345", x=690, y=240)
    hasil = susun([gabung, nilai], LEBAR, TINGGI)
    assert hasil.stnk.nomor_rangka == "MHKM1BA3JDK012345"


def test_field_wajib_yang_kosong_dilaporkan():
    hasil = susun(kotak(("Merk", 40, 300), ("TOYOTA", 185, 300)), LEBAR, TINGGI)
    assert set(hasil.field_hilang) == {"tahun", "nomor_polisi", "nomor_rangka"}


def test_teks_yang_bukan_label_tidak_dipaksakan():
    assert cocokkan_label("DOKUMEN CONTOH, BUKAN STNK ASLI") is None
    assert cocokkan_label("") is None


def test_nilai_tidak_pernah_diperbaiki():
    """Nomor rangka salah baca harus lolos apa adanya, supaya cek validitas yang menangkapnya."""
    hasil = susun(kotak(("No. Rangka", 500, 240), ("MHKM1BA3JDKO12345", 690, 240)), LEBAR, TINGGI)
    assert hasil.stnk.nomor_rangka == "MHKM1BA3JDKO12345"


def data_uji() -> stnk_generator.DataStnk:
    return stnk_generator.DataStnk(
        nomor_registrasi="B 1234 XYZ",
        nama_pemilik="BUDI SANTOSO",
        alamat="JL KEBON JERUK RAYA NO 27 JAKARTA BARAT",
        merk="TOYOTA",
        tipe="AVANZA 1.3 G",
        jenis="MINIBUS",
        model="MPV",
        tahun_pembuatan=2013,
        isi_silinder="1329 CC",
        nomor_rangka="MHKM1BA3JDK012345",
        nomor_mesin="1NRF012345",
        warna="HITAM",
        bahan_bakar="BENSIN",
        warna_tnkb="HITAM",
        tahun_registrasi=2024,
    )


@pytest.mark.lambat
def test_model_sungguhan_membaca_stnk_yang_sudah_dirusak():
    """Ukur akurasi pembacaan pada STNK sintetis, yang jawaban benarnya sudah diketahui."""
    ocr = pytest.importorskip("rapidocr", reason="butuh dependensi opsional ml")
    assert ocr

    from app.pipeline.stnk_ocr import PembacaRapidOcr, baca_stnk

    data = data_uji()
    pembaca = PembacaRapidOcr()
    benar = {
        "merk": "TOYOTA",
        "tipe": "AVANZA 1.3 G",
        "tahun": 2013,
        "nomor_polisi": "B 1234 XYZ",
        "nomor_rangka": "MHKM1BA3JDK012345",
        "nomor_mesin": "1NRF012345",
        "nama_pemilik": "BUDI SANTOSO",
    }

    total = cocok = 0
    salah_nilai = []
    for biji in (1, 2, 3, 4, 5):
        gambar = stnk_generator.buat_stnk(data, random.Random(biji), tingkat_kerusakan=0.6)
        hasil = baca_stnk(gambar, pembaca)
        for nama, nilai in benar.items():
            total += 1
            terbaca = getattr(hasil.stnk, nama)
            if terbaca == nilai:
                cocok += 1
            elif terbaca is not None:
                salah_nilai.append((nama, terbaca))

    # Ambang dipasang di bawah hasil ukuran, bukan pas, supaya uji ini menangkap kemunduran
    # nyata tanpa gagal karena selisih satu field pada satu gambar.
    assert cocok / total >= 0.90, f"akurasi field {cocok}/{total}, salah baca {salah_nilai}"
