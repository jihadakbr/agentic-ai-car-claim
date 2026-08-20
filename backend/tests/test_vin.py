"""Uji pembacaan dan pembangkitan nomor rangka."""

import random

import pytest

from app.core.vin import (
    buat_vin,
    kode_tahun,
    masalah_format,
    tahun_cocok,
    tahun_dari_kode,
)


def test_kode_tahun_mengikuti_urutan_standar():
    """Urutan kode melewati huruf I, O, Q, U, dan Z."""
    assert kode_tahun(2010) == "A"
    assert kode_tahun(2013) == "D"
    assert kode_tahun(2018) == "J"  # huruf I dilewati
    assert kode_tahun(2019) == "K"
    assert kode_tahun(2023) == "P"  # huruf O dilewati


def test_kode_tahun_berulang_tiap_tiga_puluh_tahun():
    assert kode_tahun(1985) == kode_tahun(2015)
    assert kode_tahun(2001) == "1"
    assert kode_tahun(2009) == "9"


def test_tahun_dari_kode_kembalikan_beberapa_kemungkinan():
    """Satu kode selalu cocok ke lebih dari satu tahun karena berulang."""
    assert 2013 in tahun_dari_kode("D")
    assert 1983 in tahun_dari_kode("D")
    # Dengan tahun acuan, yang jauh dari masa kini dibuang.
    assert tahun_dari_kode("D", tahun_acuan=2013) == [1983, 2013, 2043]


def test_format_wajar_tidak_menghasilkan_masalah():
    assert masalah_format("MHKM1BA3JDK012345") == []


def test_panjang_salah_terdeteksi():
    masalah = masalah_format("MHKM1BA3JFK")
    assert len(masalah) == 1
    assert "11 karakter" in masalah[0]


def test_huruf_terlarang_terdeteksi():
    """Huruf I, O, dan Q tidak pernah dipakai supaya tidak tertukar dengan angka 1 dan 0."""
    masalah = masalah_format("MHKM1BA3JDK01234O")
    assert any("O" in m for m in masalah)


def test_nomor_rangka_kosong_dilaporkan_jelas():
    assert masalah_format("") == ["Nomor rangka tidak terbaca sama sekali"]
    assert masalah_format(None) == ["Nomor rangka tidak terbaca sama sekali"]


def test_tahun_cocok_membedakan_tidak_tahu_dari_tidak_cocok():
    """None berarti tidak bisa dinilai, False berarti benar-benar tidak cocok."""
    assert tahun_cocok("MHKM1BA3JDK012345", 2013) is True
    assert tahun_cocok("MHKM1BA3JDK012345", 2019) is False
    # Terlalu pendek untuk punya karakter ke-10, jadi tidak bisa dinilai.
    assert tahun_cocok("MHKM1BA3", 2013) is None


def test_vin_buatan_selalu_lolos_pemeriksaan_sendiri():
    """Nomor rangka yang dibangkitkan untuk STNK buatan harus wajar formatnya."""
    r = random.Random(42)
    for tahun in range(2010, 2026):
        for urut in range(3):
            vin = buat_vin("MHK", tahun, urut, rng=r)
            assert masalah_format(vin) == [], vin
            assert tahun_cocok(vin, tahun) is True, vin


def test_vin_buatan_bisa_diulang_dengan_seed_sama():
    """Dipakai supaya data demo bisa dibangkitkan ulang persis sama."""
    a = buat_vin("MHK", 2013, 1, rng=random.Random(7))
    b = buat_vin("MHK", 2013, 1, rng=random.Random(7))
    assert a == b


@pytest.mark.parametrize("tahun", [2013, 2019, 2020])
def test_kode_tahun_ada_di_karakter_kesepuluh(tahun):
    vin = buat_vin("MHK", tahun, 99, rng=random.Random(1))
    assert vin[9] == kode_tahun(tahun)
