"""Uji kotak unggah kedua: foto bukti pendukung yang tidak ikut dihitung.

Surveyor di lapangan memotret nomor rangka, ruang mesin, dan bagian yang lepas dari jarak
dekat. Foto seperti itu tidak memuat bentuk mobil yang utuh, jadi kalau ikut dideteksi dia
menghasilkan bagian yang salah, dan bagian salah itu langsung masuk ke perhitungan biaya.

Yang dijaga di sini satu hal: foto pelengkap boleh sampai ke mata adjuster, tapi tidak
boleh menyentuh satu angka pun.
"""

from pathlib import Path

import pytest

gradio = pytest.importorskip("gradio", reason="butuh dependensi opsional serve")

from tests.test_api import berkas_foto, kirim_klaim, server_uji


@pytest.fixture
def klien(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, nama_db="pelengkap.db") as c:
        yield c


def test_foto_pelengkap_tersimpan_dan_bisa_dibuka(klien):
    klaim = kirim_klaim(klien, pelengkap=3)

    assert klaim["pelengkap"] == [0, 1, 2]

    r = klien.get(f"/api/klaim/{klaim['id']}/foto/1", params={"jenis": "pelengkap"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"


def test_klaim_tanpa_pelengkap_tetap_jalan_seperti_biasa(klien):
    klaim = kirim_klaim(klien)

    assert klaim["pelengkap"] == []
    assert klaim["biaya"] is not None


def test_pelengkap_tidak_mengubah_satu_angka_pun(tmp_path, monkeypatch):
    """Pembanding langsung: klaim yang sama, bedanya cuma ada tidaknya foto pelengkap."""
    with server_uji(tmp_path, monkeypatch, nama_db="polos.db") as c:
        polos = kirim_klaim(c)

    with server_uji(tmp_path, monkeypatch, nama_db="berpelengkap.db") as c:
        berpelengkap = kirim_klaim(c, pelengkap=5)

    assert len(berpelengkap["foto"]) == len(polos["foto"])
    assert berpelengkap["baris_biaya"] == polos["baris_biaya"]
    assert berpelengkap["biaya"]["total_biaya"] == polos["biaya"]["total_biaya"]
    assert [c["kode"] for c in berpelengkap["cek"] if not c["lolos"]] == [
        c["kode"] for c in polos["cek"] if not c["lolos"]
    ]


def test_pelengkap_tidak_punya_sidik_jari(klien):
    """Tanpa sidik jari, foto pelengkap tidak akan pernah dituduh dipakai ulang."""
    from sqlalchemy import select

    from app.db import session as sesi_modul
    from app.db.models import ClaimPhoto

    kirim_klaim(klien, pelengkap=3)

    with sesi_modul.sesi() as s:
        baris = list(
            s.scalars(select(ClaimPhoto).where(ClaimPhoto.jenis == "pelengkap"))
        )

    assert len(baris) == 3
    assert all(b.phash is None for b in baris)


def test_pelengkap_sama_di_dua_klaim_tidak_membuat_c2_gagal(klien):
    """Ruang mesin dan nomor rangka mirip di banyak mobil, jadi wajar berulang.

    Foto kerusakannya dibuat benar-benar berbeda supaya yang diuji memang foto pelengkap
    yang berulang, bukan foto kerusakan yang kebetulan sama.
    """
    kirim_klaim(klien, corak=1, pelengkap=3)
    kedua = kirim_klaim(klien, nomor_polis="POL-2024-0112", corak=2, pelengkap=3)

    c2 = next(c for c in kedua["cek"] if c["kode"] == "C2")
    assert c2["lolos"] is True, c2["alasan"]


def test_pelengkap_kebanyakan_ditolak(klien):
    r = klien.post(
        "/api/klaim",
        params={"nomor_polis": "POL-2024-0037"},
        files=berkas_foto(pelengkap=13),
    )

    assert r.status_code == 400
    assert "pelengkap" in r.json()["detail"].lower()


def test_pelengkap_tidak_ikut_dihitung_sebagai_foto_kerusakan(klien):
    """Enam foto pelengkap tidak menutupi kekurangan foto kerusakan."""
    r = klien.post(
        "/api/klaim",
        params={"nomor_polis": "POL-2024-0037"},
        files=berkas_foto(jumlah=0, pelengkap=6),
    )

    assert r.status_code == 400
    assert "foto kerusakan" in r.json()["detail"]


def test_hapus_klaim_ikut_membuang_berkas_pelengkap(tmp_path, monkeypatch):
    folder = tmp_path / "foto"
    with server_uji(tmp_path, monkeypatch, nama_db="hapuspelengkap.db") as c:
        klaim = kirim_klaim(c, pelengkap=4)
        assert [p for p in folder.rglob("*pelengkap*")], "berkasnya tidak ditulis"

        c.delete(f"/api/klaim/{klaim['id']}")

    assert list(folder.rglob("*.jpg")) == []


def test_berkas_pelengkap_dinamai_terpisah_dari_foto_kerusakan(tmp_path, monkeypatch):
    """Nama berkas yang bertabrakan akan menimpa foto kerusakan tanpa ada yang tahu."""
    folder = tmp_path / "foto"
    with server_uji(tmp_path, monkeypatch, nama_db="namapelengkap.db") as c:
        kirim_klaim(c, pelengkap=4)

    nama = sorted(p.name for p in folder.rglob("*.jpg"))
    assert len({Path(n).name for n in nama}) == len(nama)
    assert sum("pelengkap" in n for n in nama) == 4
