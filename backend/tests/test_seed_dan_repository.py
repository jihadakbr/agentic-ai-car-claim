"""Uji pengisian data awal dan jembatan database ke cost engine.

Uji terpenting di sini `test_avanza_lewat_database_sama_dengan_kasus_acuan`, yang menjalankan
perhitungan yang sama seperti di `test_cost_engine.py` tapi seluruh harganya dibaca dari
database, bukan dari angka yang ditulis di berkas uji. Kalau seed dan cost engine sepakat,
angkanya harus tetap sama.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.vin import masalah_format, tahun_cocok
from app.db.models import Base, LaborRate, PartCatalog, Policy, VehicleModel
from app.db.repository import (
    KonfigurasiTidakAda,
    ambil_config_float,
    ambil_config_rupiah,
    cari_kendaraan,
    muat_katalog,
    muat_matriks,
    muat_tarif,
)
from app.db.seed import isi_semua
from app.pipeline.cost_engine import Temuan, hitung_biaya, susun_estimasi


@pytest.fixture
def s() -> Session:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as sesi:
        isi_semua(sesi)
        sesi.commit()
        yield sesi


def test_seed_mengisi_semua_tabel_master(s):
    hasil = {
        "vehicle_model": s.scalar(select(VehicleModel).limit(1)),
        "part_catalog": s.scalar(select(PartCatalog).limit(1)),
        "labor_rate": s.scalar(select(LaborRate).limit(1)),
        "policy": s.scalar(select(Policy).limit(1)),
    }
    for nama, baris in hasil.items():
        assert baris is not None, f"tabel {nama} kosong setelah seed"


def test_seed_aman_dijalankan_dua_kali(s):
    sebelum = len(list(s.scalars(select(VehicleModel))))
    isi_semua(s)
    s.commit()
    assert len(list(s.scalars(select(VehicleModel)))) == sebelum


def test_config_wajib_ada(s):
    assert ambil_config_float(s, "ambang_total_loss") == 0.75
    assert ambil_config_rupiah(s, "own_risk") == Decimal(300_000)
    assert ambil_config_float(s, "faktor_salvage") == 0.30

    with pytest.raises(KonfigurasiTidakAda):
        ambil_config_float(s, "kunci_yang_tidak_ada")


def test_cari_kendaraan_dari_hasil_baca_stnk(s):
    """Pencocokan harus tahan terhadap beda huruf besar kecil dan spasi berlebih."""
    ketemu = cari_kendaraan(s, "TOYOTA", "F601RM GMMFJJ", 2013)
    assert ketemu is not None
    assert ketemu.nama_tampil == "Toyota Avanza 1.3 G"

    assert cari_kendaraan(s, "toyota", "  F601RM   GMMFJJ ", 2013) is not None
    assert cari_kendaraan(s, "TOYOTA", "F601RM GMMFJJ", 2020) is None


def test_bagian_bukan_klaim_tidak_masuk_katalog(s):
    """Plat nomor dipakai untuk pemeriksaan identitas, bukan bagian yang bisa diklaim."""
    kendaraan = cari_kendaraan(s, "TOYOTA", "F601RM GMMFJJ", 2013)
    katalog = muat_katalog(s, kendaraan.id)
    assert "License-plate" not in katalog


def test_bagian_tersembunyi_ditandai_di_katalog(s):
    """Radiator dan airbag tidak akan pernah dideteksi model, jadi harus bisa dibedakan."""
    kendaraan = cari_kendaraan(s, "TOYOTA", "F601RM GMMFJJ", 2013)
    katalog = muat_katalog(s, kendaraan.id)
    assert katalog["Radiator"].terlihat_dari_luar is False
    assert katalog["Airbag-pengemudi"].terlihat_dari_luar is False
    assert katalog["Front-bumper"].terlihat_dari_luar is True


def test_jam_standar_khusus_menang_atas_bawaan(s):
    tarif = muat_tarif(s)
    from app.pipeline.cost_engine import cari_tarif

    assert cari_tarif("ganti part", "Headlight", tarif).jam_standar == 0.8
    assert cari_tarif("ganti part", "Panel-bodi-depan", tarif).jam_standar == 5.0


def test_avanza_lewat_database_sama_dengan_kasus_acuan(s):
    """Perhitungan lengkap dengan seluruh harga dibaca dari database."""
    kendaraan = cari_kendaraan(s, "TOYOTA", "F601RM GMMFJJ", 2013)
    assert kendaraan is not None

    katalog = muat_katalog(s, kendaraan.id)
    matriks = muat_matriks(s)
    tarif = muat_tarif(s)

    terdeteksi = [
        Temuan("Front-bumper", "Broken part", 0.72),
        Temuan("Hood", "Dent", 0.45),
        Temuan("Fender", "Dent", 0.38, sisi="kiri"),
        Temuan("Fender", "Dent", 0.41, sisi="kanan"),
        Temuan("Headlight", "Broken part", 0.60, sisi="kiri"),
        Temuan("Headlight", "Broken part", 0.55, sisi="kanan"),
        Temuan("Grille", "Missing part", 0.90),
        Temuan("Windshield", "Broken part", 0.30),
    ]
    dari_aturan = [
        Temuan(kelas, "Broken part", 1.0, sumber="aturan")
        for kelas in (
            "Radiator",
            "Kondensor-AC",
            "Panel-bodi-depan",
            "Airbag-pengemudi",
            "Airbag-penumpang",
            "Modul-airbag",
        )
    ]

    baris, tidak_ketemu = hitung_biaya(terdeteksi + dari_aturan, katalog, matriks, tarif)
    assert tidak_ketemu == []

    est = susun_estimasi(
        baris,
        harga_pasar_bekas=Decimal(kendaraan.harga_pasar_bekas),
        ambang_total_loss=ambil_config_float(s, "ambang_total_loss"),
        own_risk=ambil_config_rupiah(s, "own_risk"),
        faktor_salvage=ambil_config_float(s, "faktor_salvage"),
    )

    assert est.harga_pasar_bekas == Decimal(95_000_000)
    assert est.total_part == Decimal(81_505_000)
    assert est.total_jasa == Decimal(14_595_000)
    assert est.total_biaya == Decimal(96_100_000)
    assert round(est.total_loss_ratio * 100, 1) == 101.2
    assert est.rekomendasi == "total_loss"
    assert est.harga_tawaran_salvage == Decimal(28_500_000)


def test_kendaraan_lain_harganya_ikut_faktor(s):
    """Katalog kendaraan lain diturunkan dari acuan, bukan angka acak."""
    acuan = cari_kendaraan(s, "TOYOTA", "F601RM GMMFJJ", 2013)
    lebih_baru = cari_kendaraan(s, "TOYOTA", "F653RM GMMFJJ", 2019)

    harga_acuan = muat_katalog(s, acuan.id)["Front-bumper"].harga
    harga_baru = muat_katalog(s, lebih_baru.id)["Front-bumper"].harga

    assert harga_baru > harga_acuan
    # Faktor 1.15 lalu dibulatkan ke kelipatan 50,000.
    assert harga_baru == Decimal(3_300_000)


def test_polis_menempel_ke_kendaraan_yang_benar(s):
    polis = s.scalar(select(Policy).where(Policy.nomor_polis == "POL-2024-0037"))
    assert polis is not None
    assert polis.nomor_polisi == "B 1234 XYZ"
    assert polis.nama_pemegang == "BUDI SANTOSO"

    kendaraan = s.get(VehicleModel, polis.vehicle_model_id)
    assert kendaraan.nama_tampil == "Toyota Avanza 1.3 G"
    assert kendaraan.tahun == 2013


def test_nomor_rangka_polis_berformat_vin(s):
    """VIN wajib 17 karakter tanpa huruf I, O, dan Q."""
    for polis in s.scalars(select(Policy)):
        assert masalah_format(polis.nomor_rangka) == [], polis.nomor_polis


def test_kode_tahun_nomor_rangka_cocok_dengan_kendaraannya(s):
    """Data demo harus lolos pemeriksaan yang dibuat sistem ini sendiri.

    Kalau nomor rangka di data awal saja kode tahunnya tidak cocok, cek C5 akan menandai
    seluruh klaim demo sebagai mencurigakan, dan itu memalukan saat presentasi.
    """
    for polis in s.scalars(select(Policy)):
        kendaraan = s.get(VehicleModel, polis.vehicle_model_id)
        assert tahun_cocok(polis.nomor_rangka, kendaraan.tahun) is True, polis.nomor_polis


def test_alamat_database_tersamar_menyembunyikan_sandi(monkeypatch):
    """Alamat database ikut tercetak ke log server, jadi sandinya tidak boleh ikut.

    Log Space tersimpan dan bisa dibaca siapa pun yang punya akses ke sana. Sisa alamatnya
    sengaja dibiarkan utuh, karena gunanya memang memastikan aplikasi menunjuk database yang
    benar.
    """
    from app.db.session import alamat_database_tersamar

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres.abc:SandiRahasia@aws-0-ap-southeast-1"
        ".pooler.supabase.com:5432/postgres",
    )
    hasil = alamat_database_tersamar()

    assert "SandiRahasia" not in hasil
    assert hasil.startswith("postgresql+psycopg://postgres.abc:***@")
    assert "aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres" in hasil


def test_alamat_sqlite_tidak_diubah(monkeypatch):
    from app.db.session import alamat_database_tersamar

    monkeypatch.setenv("DATABASE_URL", "sqlite:///dev.db")
    assert alamat_database_tersamar() == "sqlite:///dev.db"
