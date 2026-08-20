"""Uji penggantian nama berkas dataset.

Seluruh uji jalan di folder tiruan, tidak pernah menyentuh dataset sungguhan. Yang dijaga:
keempat subfolder ikut berubah bersamaan, pasangan gambar dan anotasinya tetap ketemu, dan
penggantian yang setengah jalan tidak pernah terjadi.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from rapikan_nama_dataset import (
    AWALAN_BARU,
    AWALAN_LAMA,
    SUBFOLDER,
    TidakBisaDilanjutkan,
    periksa_tujuan,
    rencana,
)

from app.core.aturan import KELAS_BAGIAN, KELAS_KERUSAKAN

NOMOR = (100, 101, 102)


def buat_folder(akar: Path, kelas: list[str], awalan: str = AWALAN_LAMA) -> Path:
    """Bangun satu folder dataset tiruan berbentuk Supervisely."""
    akar.mkdir(parents=True, exist_ok=True)
    (akar / "meta.json").write_text(
        json.dumps({"classes": [{"title": k} for k in kelas]}), encoding="utf-8"
    )
    file1 = akar / "File1"
    for sub in SUBFOLDER:
        (file1 / sub).mkdir(parents=True, exist_ok=True)
    for n in NOMOR:
        nama = f"{awalan}{n}.png"
        for sub in ("img", "masks_human", "masks_machine"):
            (file1 / sub / nama).write_bytes(b"gambar")
        (file1 / "ann" / f"{nama}.json").write_text("{}", encoding="utf-8")
    return file1


@pytest.fixture
def bagian(tmp_path) -> Path:
    return buat_folder(tmp_path / "Car parts dataset", KELAS_BAGIAN)


def test_keempat_subfolder_ikut_berubah(bagian):
    langkah = rencana(bagian, AWALAN_LAMA, AWALAN_BARU)

    per_sub = {lama.parent.name for lama, _ in langkah}
    assert per_sub == set(SUBFOLDER)
    assert len(langkah) == len(NOMOR) * len(SUBFOLDER)


def test_anotasi_tetap_berpasangan_sesudah_diganti(bagian):
    for lama, baru in rencana(bagian, AWALAN_LAMA, AWALAN_BARU):
        lama.rename(baru)

    for gambar in sorted((bagian / "img").iterdir()):
        assert gambar.name.startswith(AWALAN_BARU)
        assert (bagian / "ann" / f"{gambar.name}.json").exists()


def test_bisa_dikembalikan_ke_nama_semula(bagian):
    sebelum = sorted(p.name for p in (bagian / "img").iterdir())

    for lama, baru in rencana(bagian, AWALAN_LAMA, AWALAN_BARU):
        lama.rename(baru)
    for lama, baru in rencana(bagian, AWALAN_BARU, AWALAN_LAMA):
        lama.rename(baru)

    assert sorted(p.name for p in (bagian / "img").iterdir()) == sebelum


def test_berhenti_kalau_nama_tujuan_sudah_terpakai(bagian):
    """Berhenti sebelum menyentuh berkas, karena penggantian setengah jalan sulit dibereskan."""
    (bagian / "img" / f"{AWALAN_BARU}{NOMOR[0]}.png").write_bytes(b"sudah ada")
    langkah = rencana(bagian, AWALAN_LAMA, AWALAN_BARU)

    with pytest.raises(TidakBisaDilanjutkan):
        periksa_tujuan(langkah)

    assert (bagian / "img" / f"{AWALAN_LAMA}{NOMOR[0]}.png").exists()


def test_dijalankan_dua_kali_tidak_menghasilkan_apa_apa(bagian):
    for lama, baru in rencana(bagian, AWALAN_LAMA, AWALAN_BARU):
        lama.rename(baru)

    assert rencana(bagian, AWALAN_LAMA, AWALAN_BARU) == []


def test_folder_kerusakan_dikenali_dari_kelasnya_bukan_namanya(tmp_path, monkeypatch):
    """Nama folder boleh apa saja, yang menentukan daftar kelas di meta.json."""
    import rapikan_nama_dataset as skrip

    buat_folder(tmp_path / "folder tanpa nama jelas", KELAS_BAGIAN)
    buat_folder(tmp_path / "folder lain", KELAS_KERUSAKAN)
    monkeypatch.setattr(skrip, "SUMBER", tmp_path)

    assert skrip.folder_bagian().name == "folder tanpa nama jelas"
