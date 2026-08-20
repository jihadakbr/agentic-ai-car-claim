"""Uji penggabungan kelas kerusakan, dari nama keluaran model sampai aturan biaya.

Model mengeluarkan delapan nama, sistem memakai empat. Penggabungannya dikerjakan saat
membaca hasil deteksi, jadi yang harus dijaga di sini ada dua: tidak ada nama lama yang
bocor ke lapisan biaya, dan tiap kelas hasil penggabungan tetap punya aturan perbaikan.
"""

import numpy as np
import pytest

from app.core.aturan import GABUNG_KERUSAKAN, KELAS_KERUSAKAN
from app.db.repository import muat_matriks
from app.pipeline.cost_engine import pilih_aturan
from app.pipeline.detektor import DetektorYolo


class MaskPalsu:
    """Menirukan tensor mask Ultralytics secukupnya untuk `_ambil_mask`."""

    def __init__(self, arr):
        self.arr = arr

    def cpu(self):
        return self

    def numpy(self):
        return self.arr


class KotakPalsu:
    def __init__(self, conf, cls):
        self.conf = conf
        self.cls = cls


class HasilPalsu:
    def __init__(self, nama, isi, ukuran):
        self.names = nama
        self.masks = type("M", (), {"data": [MaskPalsu(np.ones(ukuran, dtype=bool)) for _ in isi]})()
        self.boxes = [KotakPalsu(c, k) for k, c in isi]


def ambil(isi, ukuran=(4, 4)):
    nama = {i: k for i, k in enumerate(GABUNG_KERUSAKAN)}
    balik = {k: i for i, k in nama.items()}
    hasil = HasilPalsu(nama, [(balik[k], c) for k, c in isi], ukuran)
    return DetektorYolo._ambil_mask([hasil], 0.10, (ukuran[1], ukuran[0]), GABUNG_KERUSAKAN)


@pytest.mark.parametrize(
    ("keluaran_model", "diharapkan"),
    [
        ("Paint chip", "Scratch"),
        ("Flaking", "Scratch"),
        ("Corrosion", "Scratch"),
        ("Cracked", "Broken part"),
        ("Scratch", "Scratch"),
        ("Dent", "Dent"),
        ("Broken part", "Broken part"),
        ("Missing part", "Missing part"),
    ],
)
def test_nama_kelas_diterjemahkan(keluaran_model, diharapkan):
    assert ambil([(keluaran_model, 0.9)])[0].kelas == diharapkan


def test_kelas_yang_dibuang_tidak_pernah_lolos():
    """Empat nama ini tidak boleh muncul di lapisan mana pun setelah deteksi."""
    semua = ambil([(k, 0.9) for k in GABUNG_KERUSAKAN])
    assert {m.kelas for m in semua} == set(KELAS_KERUSAKAN)


def test_model_bagian_mobil_tidak_ikut_diterjemahkan():
    """Peta penggabungan cuma dilewatkan untuk kerusakan, bukan untuk bagian mobil."""
    nama = {0: "Front-bumper"}
    hasil = HasilPalsu(nama, [(0, 0.9)], (4, 4))
    assert DetektorYolo._ambil_mask([hasil], 0.10, (4, 4))[0].kelas == "Front-bumper"


def test_peta_penggabungan_utuh():
    """Tiap nilai peta harus kelas sistem, dan tiap kelas sistem harus jadi tujuan."""
    assert set(GABUNG_KERUSAKAN.values()) == set(KELAS_KERUSAKAN)
    for kelas in KELAS_KERUSAKAN:
        assert GABUNG_KERUSAKAN[kelas] == kelas


def test_tiap_kelas_punya_aturan_di_seluruh_rentang():
    """Matriks yang benar-benar dipakai datang dari database, bukan dari konstanta."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.models import Base
    from app.db.seed import isi_semua

    mesin = create_engine("sqlite://")
    Base.metadata.create_all(mesin)
    with Session(mesin) as s:
        isi_semua(s)
        s.commit()
        matriks = muat_matriks(s)
    for kelas in KELAS_KERUSAKAN:
        for rasio in (0.0, 0.05, 0.15, 0.25, 1.0):
            assert pilih_aturan(kelas, rasio, matriks) is not None
