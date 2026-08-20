"""Uji layar Klaim Saya: surveyor memantau kirimannya sendiri, tanpa melihat penilaian.

Yang paling penting dibuktikan: daftarnya benar-benar disaring di server, dan bahan
keputusan adjuster tidak ikut terkirim. Menyaringnya di frontend tidak cukup, sebab datanya
tetap sampai ke browser dan tinggal dibuka di tab jaringan.
"""

import pytest

from app.core import izin
from app.db.seed import isi_peran

gradio = pytest.importorskip("gradio", reason="butuh dependensi opsional serve")

from tests.test_api import SANDI, berkas_foto, server_uji

DILARANG = ("total_biaya", "verdict_validitas", "rekomendasi", "total_loss_ratio", "narasi")


def kirim(klien, nomor_polis="POL-2024-0037") -> str:
    r = klien.post("/api/klaim", params={"nomor_polis": nomor_polis}, files=berkas_foto())
    assert r.status_code == 202, r.text
    return r.json()["id"]


def masuk(klien, username: str) -> None:
    r = klien.post("/api/login", json={"username": username, "password": SANDI})
    assert r.status_code == 200, r.text
    klien.headers["Authorization"] = f"Bearer {r.json()['token']}"


@pytest.fixture
def klien(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, nama_db="kiriman.db", masuk_sebagai="surveyor") as c:
        yield c


def test_daftar_kosong_untuk_akun_yang_belum_pernah_mengirim(klien):
    assert klien.get("/api/klaim/saya").json() == []


def test_klaim_yang_dikirim_muncul_di_daftar(klien):
    id_klaim = kirim(klien)

    daftar = klien.get("/api/klaim/saya").json()

    assert [k["id"] for k in daftar] == [id_klaim]
    assert daftar[0]["nomor_polis"] == "POL-2024-0037"
    assert daftar[0]["status"]
    assert "permintaan_foto" in daftar[0]


def test_daftar_tidak_membawa_bahan_keputusan_adjuster(klien):
    """Aturannya: surveyor tidak pernah melihat biaya, verdict, maupun rekomendasi."""
    kirim(klien)

    daftar = klien.get("/api/klaim/saya").json()

    for terlarang in DILARANG:
        assert terlarang not in daftar[0], f"{terlarang} tidak boleh sampai ke surveyor"


def test_surveyor_cuma_melihat_kirimannya_sendiri(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, nama_db="dua.db", masuk_sebagai="admin") as c:
        kirim(c)
        assert len(c.get("/api/klaim/saya").json()) == 1

        masuk(c, "surveyor")
        assert c.get("/api/klaim/saya").json() == []


def test_yang_berhak_melihat_semua_klaim_dapat_semuanya(tmp_path, monkeypatch):
    """Admin memantau kiriman siapa pun dari satu layar, termasuk miliknya sendiri."""
    with server_uji(tmp_path, monkeypatch, nama_db="tiga.db", masuk_sebagai="surveyor") as c:
        kirim(c)

        masuk(c, "admin")
        kirim(c, "POL-2024-0245")

        daftar = c.get("/api/klaim/saya").json()

    assert len(daftar) == 2
    assert {k["surveyor"] for k in daftar} == {"surveyor", "admin"}
    for k in daftar:
        for terlarang in DILARANG:
            assert terlarang not in k, f"{terlarang} tidak boleh sampai ke layar ini"


def test_peran_tanpa_hak_lacak_ditolak(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, nama_db="lacak.db", masuk_sebagai="adjuster") as c:
        assert c.get("/api/klaim/saya").status_code == 403


def test_status_klaim_orang_lain_ditolak_walau_perannya_bernama_bebas(tmp_path, monkeypatch):
    """Pemeriksaannya harus berbasis hak, bukan nama peran.

    Sebelumnya kepemilikan diperiksa dengan membandingkan nama peran ke teks "surveyor",
    sehingga peran buatan bernama lain lolos begitu saja dan bisa membaca klaim siapa pun.
    """
    with server_uji(tmp_path, monkeypatch, nama_db="peran.db", masuk_sebagai="admin") as c:
        id_klaim = kirim(c)

        c.post("/api/akses/peran", json={
            "kode": "surveyor_lapangan", "nama": "Surveyor Lapangan", "keterangan": "uji",
        })
        c.put("/api/akses/peran/surveyor_lapangan/izin", json={
            "izin": [izin.POLIS_LIHAT, izin.KLAIM_KIRIM, izin.KLAIM_LACAK],
        })
        c.post("/api/akses/pengguna/surveyor", json={"peran": "surveyor_lapangan"})

        masuk(c, "surveyor")
        r = c.get(f"/api/klaim/{id_klaim}/status")

    assert r.status_code == 403


def test_isi_peran_melengkapi_hak_baru_tanpa_mencabut_yang_ada(tmp_path, monkeypatch):
    """Database yang sudah jalan harus ikut mendapat hak yang baru muncul di versi baru."""
    from sqlalchemy import select

    from app.db.models import RolePermission
    from app.db.session import sesi

    with server_uji(tmp_path, monkeypatch, nama_db="lengkapi.db", masuk_sebagai="admin"):
        with sesi() as s:
            s.add(RolePermission(role_kode="surveyor", izin=izin.OVERVIEW_LIHAT))
            s.query(RolePermission).filter(
                RolePermission.role_kode == "surveyor",
                RolePermission.izin == izin.KLAIM_LACAK,
            ).delete()
            s.commit()

        with sesi() as s:
            peran_baru, izin_baru = isi_peran(s)
            s.commit()

            punya = set(s.scalars(
                select(RolePermission.izin).where(RolePermission.role_kode == "surveyor")
            ))

    assert peran_baru == 0
    assert izin_baru == 1
    assert izin.KLAIM_LACAK in punya, "hak bawaan yang hilang harus dikembalikan"
    assert izin.OVERVIEW_LIHAT in punya, "hak tambahan tidak boleh ikut dicabut"
