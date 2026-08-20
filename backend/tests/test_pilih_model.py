"""Uji pemilihan bobot model dan penjaga kecocokan kelasnya.

Dua kekeliruan yang dijaga di sini pernah benar-benar mungkin terjadi: menyangka model
sungguhan sudah aktif padahal yang jalan detektor contoh, dan memasang bobot bagian dan
kerusakan yang tertukar karena nama folder datasetnya memang tertukar terhadap isinya.
"""

import pytest
from PIL import Image

from app.api.server import buat_detektor, jalur_model
from app.core.aturan import KELAS_BAGIAN, KELAS_KERUSAKAN
from app.pipeline.detektor import DetektorContoh, KelasModelTidakCocok, periksa_kelas


@pytest.fixture(autouse=True)
def tanpa_env(monkeypatch):
    monkeypatch.setenv("MODEL_PART", "")
    monkeypatch.setenv("MODEL_DAMAGE", "")


def test_tanpa_bobot_jalur_kosong(monkeypatch, tmp_path):
    monkeypatch.setattr("app.api.server.FOLDER_MODEL", tmp_path)
    assert jalur_model() is None


def test_bobot_setengah_dianggap_belum_ada(monkeypatch, tmp_path):
    """Model bagian sungguhan bersama kerusakan contoh menghasilkan campuran tak berarti."""
    (tmp_path / "part.pt").write_bytes(b"bukan bobot sungguhan")
    monkeypatch.setattr("app.api.server.FOLDER_MODEL", tmp_path)
    assert jalur_model() is None


def test_dua_bobot_lengkap_terbaca(monkeypatch, tmp_path):
    (tmp_path / "part.pt").write_bytes(b"x")
    (tmp_path / "damage.pt").write_bytes(b"x")
    monkeypatch.setattr("app.api.server.FOLDER_MODEL", tmp_path)

    jalur = jalur_model()
    assert jalur is not None
    assert jalur[0].name == "part.pt"
    assert jalur[1].name == "damage.pt"


def test_env_menimpa_folder_bawaan(monkeypatch, tmp_path):
    lain = tmp_path / "lain"
    lain.mkdir()
    (lain / "a.pt").write_bytes(b"x")
    (lain / "b.pt").write_bytes(b"x")
    monkeypatch.setenv("MODEL_PART", str(lain / "a.pt"))
    monkeypatch.setenv("MODEL_DAMAGE", str(lain / "b.pt"))

    assert jalur_model() == (lain / "a.pt", lain / "b.pt")


def test_tanpa_bobot_dipakai_detektor_contoh(monkeypatch, tmp_path):
    monkeypatch.setattr("app.api.server.FOLDER_MODEL", tmp_path)
    assert isinstance(buat_detektor(), DetektorContoh)


def test_kelas_cocok_diterima(tmp_path):
    nama = dict(enumerate(KELAS_BAGIAN))
    periksa_kelas(nama, KELAS_BAGIAN, "bagian mobil", tmp_path / "part.pt")


def test_bobot_tertukar_ditolak(tmp_path):
    """Justru kekeliruan yang paling mungkin: nama folder datasetnya memang tertukar."""
    nama = dict(enumerate(KELAS_KERUSAKAN))
    with pytest.raises(KelasModelTidakCocok) as galat:
        periksa_kelas(nama, KELAS_BAGIAN, "bagian mobil", tmp_path / "part.pt")

    pesan = str(galat.value)
    assert "Dent" in pesan
    assert "Hood" in pesan


def test_kelas_kurang_disebut_namanya(tmp_path):
    nama = dict(enumerate(KELAS_KERUSAKAN[:-1]))
    with pytest.raises(KelasModelTidakCocok, match=KELAS_KERUSAKAN[-1]):
        periksa_kelas(nama, KELAS_KERUSAKAN, "kerusakan", tmp_path / "damage.pt")


def test_deteksi_banyak_sama_dengan_memanggil_satu_satu():
    """Jalur satu panggilan untuk seluruh foto tidak boleh mengubah hasil apa pun.

    Pengelompokan itu dibuat demi kuota GPU di Hugging Face, bukan demi hasil. Kalau
    keluarannya sampai berbeda, angka biaya ikut berubah tanpa ada yang memintanya.
    """
    detektor = DetektorContoh()
    gambar = [
        Image.new("RGB", (640, 480), warna)
        for warna in ((30, 30, 30), (200, 40, 40), (80, 120, 200))
    ]

    satu_satu = [detektor.deteksi(g) for g in gambar]
    sekaligus = detektor.deteksi_banyak(gambar)

    assert len(sekaligus) == len(satu_satu)
    for a, b in zip(satu_satu, sekaligus, strict=True):
        assert a.confidence_kendaraan == b.confidence_kendaraan
        for lapis in ("part", "damage"):
            kiri, kanan = getattr(a, lapis), getattr(b, lapis)
            assert [m.kelas for m in kiri] == [m.kelas for m in kanan]
            assert [m.mask.sum() for m in kiri] == [m.mask.sum() for m in kanan]
