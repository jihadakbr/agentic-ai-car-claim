"""Uji pembangkit STNK buatan."""

import itertools
import random
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.vin import masalah_format, tahun_cocok
from app.db.models import Base
from app.db.seed import POLIS as seed_polis
from app.db.seed import isi_semua
from app.pipeline import stnk_generator
from app.pipeline.stnk_dataset import (
    dengan_kesalahan,
    kumpulkan_dari_database,
    tulis_berkas,
)
from app.pipeline.stnk_generator import (
    _FIELD,
    _PENGISI,
    LEBAR,
    TEMPLAT,
    TINGGI,
    DataStnk,
    _font_acuan,
    _tulis,
    buat_stnk,
    render,
    render_dari_acuan,
)

butuh_templat = pytest.mark.skipif(
    not TEMPLAT.exists(),
    reason="templat acuan ada di data/ yang tidak ikut repo, "
           "jalankan scripts/siapkan_stnk_acuan.py",
)


@pytest.fixture
def s() -> Session:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as sesi:
        isi_semua(sesi)
        sesi.commit()
        yield sesi


@pytest.fixture
def contoh_data() -> DataStnk:
    return DataStnk(
        nomor_registrasi="B 1234 XYZ",
        nama_pemilik="BUDI SANTOSO",
        alamat="Jl. Kebon Jeruk Raya No. 27",
        merk="TOYOTA",
        tipe="F601RM GMMFJJ",
        jenis="MOBIL PENUMPANG",
        model="MINIBUS",
        tahun_pembuatan=2013,
        isi_silinder="1329 CC",
        nomor_rangka="MHKM1BA3JDK012345",
        nomor_mesin="1NRF012345",
        warna="HITAM",
        bahan_bakar="BENSIN",
        warna_tnkb="HITAM",
        tahun_registrasi=2013,
    )


def test_render_menghasilkan_gambar_berukuran_benar(contoh_data):
    img = render(contoh_data)
    assert isinstance(img, Image.Image)
    assert img.size == (LEBAR, TINGGI)


def test_gambar_bersih_tidak_seragam(contoh_data):
    """Kalau seluruh piksel sama, berarti teksnya gagal digambar."""
    img = render(contoh_data)
    warna = img.convert("L").getcolors(maxcolors=256 * 256)
    assert len(warna) > 5


def test_kerusakan_mengubah_gambar(contoh_data):
    bersih = render(contoh_data)
    rusak = buat_stnk(contoh_data, rng=random.Random(1), tingkat_kerusakan=1.0)
    assert not np.array_equal(np.asarray(bersih), np.asarray(rusak))


def test_tingkat_nol_tidak_mengubah_apa_pun(contoh_data):
    """Dipakai untuk membuat kumpulan uji yang mudah, sebagai batas atas akurasi."""
    bersih = render(contoh_data)
    hasil = buat_stnk(contoh_data, rng=random.Random(1), tingkat_kerusakan=0, gaya="gambar")
    assert np.array_equal(np.asarray(bersih), np.asarray(hasil))


def test_hasil_bisa_diulang_dengan_seed_sama(contoh_data):
    """Data demo harus bisa dibangkitkan ulang persis sama."""
    a = buat_stnk(contoh_data, rng=random.Random(99))
    b = buat_stnk(contoh_data, rng=random.Random(99))
    assert np.array_equal(np.asarray(a), np.asarray(b))


def test_seed_berbeda_menghasilkan_gambar_berbeda(contoh_data):
    a = buat_stnk(contoh_data, rng=random.Random(1))
    b = buat_stnk(contoh_data, rng=random.Random(2))
    assert not np.array_equal(np.asarray(a), np.asarray(b))


@butuh_templat
def test_gaya_acuan_memakai_ukuran_templat(contoh_data):
    with Image.open(TEMPLAT) as templat:
        ukuran = templat.size
    assert render_dari_acuan(contoh_data, random.Random(3)).size == ukuran


def test_gaya_acuan_jatuh_ke_gaya_gambar_kalau_templat_tidak_ada(contoh_data, monkeypatch):
    """Repo yang baru di-clone belum punya templat, dan uji tidak boleh ikut mati."""
    monkeypatch.setattr(stnk_generator, "TEMPLAT", Path("data/acuan/tidak-ada.jpg"))
    hasil = buat_stnk(contoh_data, rng=random.Random(1), tingkat_kerusakan=0, gaya="acuan")
    assert hasil.size == (LEBAR, TINGGI)


def test_area_tulis_tidak_saling_tindih():
    """Dua nilai yang area tulisnya bertindih akan saling menimpa dan dua-duanya gagal dibaca.

    Yang diperiksa area tulisnya, membentang sampai batas kanan, bukan kotak hapusnya.
    Kotak hapus memang boleh beririsan, sebab di lembar aslinya beberapa isian tercetak
    saling menyerempet.
    """
    semua = list(_FIELD.items()) + list(_PENGISI.items())
    for (nama_a, (a, batas_a)), (nama_b, (b, batas_b)) in itertools.combinations(semua, 2):
        bertindih = (
            a[0] < batas_b and b[0] < batas_a and a[1] < b[3] and b[1] < a[3]
        )
        assert not bertindih, f"area tulis {nama_a} dan {nama_b} bertindih"


def test_nilai_panjang_dikecilkan_supaya_tidak_meluber():
    """Nilai karangan bisa lebih panjang daripada nilai asli yang kotaknya diukur."""
    d = ImageDraw.Draw(Image.new("RGB", (2104, 656)))
    kotak = (300, 100, 500, 140)
    batas_kanan = 700
    teks = "MHKM1BA3JDK012345 PANJANG SEKALI SAMPAI MELUBER"

    ukuran = _tulis(d, teks, kotak, batas_kanan)

    kiri, atas, kanan, bawah = d.textbbox((0, 0), teks, font=_font_acuan(ukuran))
    assert kanan - kiri <= batas_kanan - kotak[0]
    assert bawah - atas <= kotak[3] - kotak[1]


def test_jawaban_benar_lengkap(contoh_data):
    """Tiap field harus punya jawaban benar, karena itu yang dipakai mengukur akurasi."""
    jawaban = contoh_data.sebagai_jawaban_benar()
    for kunci in ("merk", "tipe", "tahun_pembuatan", "nomor_registrasi", "nomor_rangka"):
        assert kunci in jawaban
        assert jawaban[kunci] not in (None, "")


def test_stnk_dari_database_cocok_dengan_polisnya(s):
    """STNK buatan tidak dikarang lepas, tapi diambil dari data polis yang ada."""
    rng = random.Random(7)
    contoh = kumpulkan_dari_database(s, rng)
    assert len(contoh) == len(seed_polis)

    for c in contoh:
        assert c.sengaja_salah is None
        assert masalah_format(c.data.nomor_rangka) == []
        assert tahun_cocok(c.data.nomor_rangka, c.data.tahun_pembuatan) is True


def test_versi_sengaja_salah_benar_benar_berbeda(s):
    """Tanpa contoh yang sengaja salah, cek kecurangan tidak pernah terbukti bekerja."""
    rng = random.Random(7)
    asli = kumpulkan_dari_database(s, rng)[0]

    beda_rangka = dengan_kesalahan(asli, "nomor_rangka_beda", rng)
    assert beda_rangka.data.nomor_rangka != asli.data.nomor_rangka
    assert masalah_format(beda_rangka.data.nomor_rangka) == []

    beda_nopol = dengan_kesalahan(asli, "nomor_polisi_beda", rng)
    assert beda_nopol.data.nomor_registrasi != asli.data.nomor_registrasi

    rangka_pendek = dengan_kesalahan(asli, "nomor_rangka_pendek", rng)
    assert masalah_format(rangka_pendek.data.nomor_rangka) != []

    tahun_geser = dengan_kesalahan(asli, "tahun_tidak_cocok_vin", rng)
    assert tahun_cocok(tahun_geser.data.nomor_rangka, tahun_geser.data.tahun_pembuatan) is False


def test_jenis_kesalahan_tak_dikenal_ditolak(s):
    rng = random.Random(7)
    asli = kumpulkan_dari_database(s, rng)[0]
    with pytest.raises(ValueError):
        dengan_kesalahan(asli, "kesalahan_yang_tidak_ada", rng)


def test_menulis_berkas_gambar(s, tmp_path):
    rng = random.Random(7)
    contoh = kumpulkan_dari_database(s, rng)[:2]
    jalur = tulis_berkas(contoh, tmp_path / "stnk", rng, gaya="gambar")

    assert len(jalur) == 2
    for p in jalur:
        assert p.exists()
        assert p.stat().st_size > 5_000
        with Image.open(p) as img:
            assert img.size == (LEBAR, TINGGI)


def test_setiap_contoh_dapat_berkas_sendiri(s, tmp_path):
    """Nama berkas harus unik. Bug sebelumnya membuat berkas saling menimpa."""
    rng = random.Random(7)
    dasar = kumpulkan_dari_database(s, rng)
    contoh = [dasar[i % len(dasar)] for i in range(8)]

    jalur = tulis_berkas(contoh, tmp_path / "stnk", rng)

    assert len(jalur) == 8
    assert len(set(jalur)) == 8
    assert len(list((tmp_path / "stnk").glob("*.jpg"))) == 8


def test_tingkat_kerusakan_boleh_berbeda_per_berkas(s, tmp_path):
    rng = random.Random(7)
    contoh = kumpulkan_dari_database(s, rng)[:3]
    jalur = tulis_berkas(contoh, tmp_path / "stnk", rng, tingkat_kerusakan=[0.0, 0.7, 1.4])
    assert len(jalur) == 3


def test_jumlah_tingkat_tidak_cocok_ditolak(s, tmp_path):
    rng = random.Random(7)
    contoh = kumpulkan_dari_database(s, rng)[:3]
    with pytest.raises(ValueError, match="tidak sama dengan"):
        tulis_berkas(contoh, tmp_path / "stnk", rng, tingkat_kerusakan=[0.5, 1.0])
