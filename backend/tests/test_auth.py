"""Uji kata sandi, token, dan pembagian peran.

Bagian token diuji tanpa server sama sekali. Bagian peran diuji lewat HTTP, karena yang
ingin dibuktikan bukan cuma bahwa fungsinya benar, tapi bahwa alamatnya benar-benar
menolak peran yang tidak berhak. Menu yang disembunyikan di frontend tidak menahan siapa
pun yang mengetik alamatnya langsung.
"""

import time

import pytest

from app.core import auth

gradio = pytest.importorskip("gradio", reason="butuh dependensi opsional serve")

from tests.test_api import SANDI, berkas_foto, lengkapi_review, server_uji


def test_sandi_yang_benar_diterima():
    garam = auth.garam_baru()
    hash_ = auth.hash_sandi("Kijang@2026", garam)
    assert auth.periksa_sandi("Kijang@2026", garam, hash_)


def test_sandi_yang_salah_ditolak():
    garam = auth.garam_baru()
    hash_ = auth.hash_sandi("Kijang@2026", garam)
    assert not auth.periksa_sandi("kijang@2026", garam, hash_)


def test_garam_berbeda_menghasilkan_turunan_berbeda():
    """Dua akun dengan sandi sama tidak boleh punya turunan yang sama di database."""
    a = auth.hash_sandi("Kijang@2026", auth.garam_baru())
    b = auth.hash_sandi("Kijang@2026", auth.garam_baru())
    assert a != b


def test_token_membawa_username_dan_peran():
    muatan = auth.baca_token(auth.buat_token("adjuster", auth.ADJUSTER))
    assert muatan["sub"] == "adjuster"
    assert muatan["peran"] == auth.ADJUSTER


def test_token_yang_diubah_ditolak():
    """Menaikkan peran sendiri dengan menyunting isi token harus gagal."""
    token = auth.buat_token("surveyor", auth.SURVEYOR)
    _, tanda = token.split(".")
    palsu = auth.buat_token("surveyor", auth.ADMIN).split(".")[0]

    with pytest.raises(auth.TokenTidakSah):
        auth.baca_token(f"{palsu}.{tanda}")


def test_token_kedaluwarsa_ditolak():
    token = auth.buat_token("admin", auth.ADMIN, umur_detik=-1)
    with pytest.raises(auth.TokenTidakSah):
        auth.baca_token(token)


def test_token_ngawur_ditolak():
    for token in ("", "bukan-token", "a.b.c"):
        with pytest.raises(auth.TokenTidakSah):
            auth.baca_token(token)


def test_masa_berlaku_token_dua_belas_jam():
    muatan = auth.baca_token(auth.buat_token("admin", auth.ADMIN))
    sisa = muatan["exp"] - time.time()
    assert 11 * 3600 < sisa <= 12 * 3600


def test_masuk_dengan_sandi_benar(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, "masuk.db", masuk_sebagai=None) as c:
        r = c.post("/api/login", json={"username": "adjuster", "password": SANDI})
        assert r.status_code == 200
        assert r.json()["peran"] == "adjuster"
        assert r.json()["token"]


def test_username_salah_dan_sandi_salah_dijawab_sama(tmp_path, monkeypatch):
    """Pesan yang berbeda akan membocorkan username mana yang benar-benar ada."""
    with server_uji(tmp_path, monkeypatch, "pesan.db", masuk_sebagai=None) as c:
        tidak_ada = c.post("/api/login", json={"username": "hantu", "password": SANDI})
        sandi_salah = c.post("/api/login", json={"username": "admin", "password": "salah"})

    assert tidak_ada.status_code == sandi_salah.status_code == 401
    assert tidak_ada.json()["detail"] == sandi_salah.json()["detail"]


def test_tanpa_token_ditolak_401(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, "tanpa.db", masuk_sebagai=None) as c:
        assert c.get("/api/klaim").status_code == 401
        assert c.get("/api/polis/POL-2024-0037").status_code == 401
        assert c.get("/api/saya").status_code == 401


def test_kesehatan_tetap_terbuka_tanpa_masuk(tmp_path, monkeypatch):
    """Dipanggil untuk memanaskan server sebelum presentasi, jadi tidak boleh dikunci."""
    with server_uji(tmp_path, monkeypatch, "sehat.db", masuk_sebagai=None) as c:
        assert c.get("/api/kesehatan").status_code == 200


def test_surveyor_tidak_boleh_membuka_daftar_klaim(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, "sv.db", masuk_sebagai="surveyor") as c:
        assert c.get("/api/klaim").status_code == 403

        kirim = c.post(
            "/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto()
        )
        assert kirim.status_code == 202

        putus = c.post(
            f"/api/klaim/{kirim.json()['id']}/keputusan", json={"keputusan": "setuju"}
        )
        assert putus.status_code == 403


def test_adjuster_tidak_boleh_mengirim_klaim(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, "adj.db", masuk_sebagai="adjuster") as c:
        assert c.get("/api/klaim").status_code == 200
        assert c.get("/api/polis/POL-2024-0037").status_code == 403

        r = c.post(
            "/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto()
        )
        assert r.status_code == 403


def test_admin_boleh_keduanya(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, "adm.db", masuk_sebagai="admin") as c:
        assert c.get("/api/polis/POL-2024-0037").status_code == 200
        kirim = c.post(
            "/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto()
        )
        assert kirim.status_code == 202
        assert c.get("/api/klaim").status_code == 200
        klaim = c.get(f"/api/klaim/{kirim.json()['id']}").json()
        lengkapi_review(c, klaim)
        assert c.post(
            f"/api/klaim/{klaim['id']}/keputusan", json={"keputusan": "setuju"}
        ).status_code == 200


def test_saya_mengembalikan_akun_yang_masuk(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, "saya.db", masuk_sebagai="surveyor") as c:
        data = c.get("/api/saya").json()
    assert data["username"] == "surveyor"
    assert data["peran"] == "surveyor"
    assert data["nama"]


def test_sandi_tidak_pernah_tersimpan_apa_adanya(tmp_path, monkeypatch):
    from sqlalchemy import select

    from app.db import session as sesi_modul
    from app.db.models import AppUser

    with (
        server_uji(tmp_path, monkeypatch, "hash.db", masuk_sebagai=None),
        sesi_modul.sesi() as s,
    ):
        akun = list(s.scalars(select(AppUser)))
        assert len(akun) == 3
        for a in akun:
            assert SANDI not in a.sandi_hash
            assert a.sandi_hash != SANDI
            assert len(a.sandi_hash) == 64


def test_ringkasan_hanya_untuk_adjuster_dan_admin(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, "ring1.db", masuk_sebagai="surveyor") as c:
        assert c.get("/api/overview").status_code == 403

    with server_uji(tmp_path, monkeypatch, "ring2.db", masuk_sebagai="adjuster") as c:
        assert c.get("/api/overview").status_code == 200

    with server_uji(tmp_path, monkeypatch, "ring3.db", masuk_sebagai="admin") as c:
        assert c.get("/api/overview").status_code == 200


def test_review_deteksi_tertutup_untuk_surveyor(tmp_path, monkeypatch):
    """Yang menilai ketepatan model adalah adjuster, karena dia yang menanggung
    keputusannya. Surveyor cuma melihat overlay untuk memastikan fotonya layak."""
    with server_uji(tmp_path, monkeypatch, "rev1.db", masuk_sebagai="surveyor") as c:
        kirim = c.post(
            "/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto()
        ).json()
        r = c.post(
            f"/api/klaim/{kirim['id']}/review-deteksi",
            json={"penilaian": [{"temuan_id": "apa-saja", "benar": True}]},
        )
        assert r.status_code == 403


def test_surveyor_hanya_boleh_melihat_status_kirimannya_sendiri(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, "status1.db", masuk_sebagai="surveyor") as c:
        milik_sendiri = c.post(
            "/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto()
        ).json()["id"]
        assert c.get(f"/api/klaim/{milik_sendiri}/status").status_code == 200

        # Klaim yang sama dikirim admin, jadi bukan kiriman surveyor ini.
        r = c.post("/api/login", json={"username": "admin", "password": SANDI})
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        milik_admin = c.post(
            "/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto()
        ).json()["id"]

        r = c.post("/api/login", json={"username": "surveyor", "password": SANDI})
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        assert c.get(f"/api/klaim/{milik_admin}/status").status_code == 403


def test_hapus_klaim_hanya_untuk_admin(tmp_path, monkeypatch):
    """Menghapus klaim membuang jejak auditnya sekalian, jadi adjuster pun tidak boleh."""
    with server_uji(tmp_path, monkeypatch, "hapus1.db", masuk_sebagai="surveyor") as c:
        kirim = c.post(
            "/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto()
        ).json()
        assert c.delete(f"/api/klaim/{kirim['id']}").status_code == 403

    with server_uji(tmp_path, monkeypatch, "hapus2.db", masuk_sebagai="adjuster") as c:
        assert c.delete("/api/klaim/apa-saja").status_code == 403

    with server_uji(tmp_path, monkeypatch, "hapus3.db", masuk_sebagai="admin") as c:
        kirim = c.post(
            "/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto()
        ).json()
        assert c.delete(f"/api/klaim/{kirim['id']}").status_code == 200


def test_foto_tidak_bisa_diambil_tanpa_masuk(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, "fotoauth.db", masuk_sebagai="surveyor") as c:
        kirim = c.post(
            "/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto()
        ).json()
        alamat = f"/api/klaim/{kirim['id']}/foto/0"
        assert c.get(alamat).status_code == 200

        # Surveyor boleh melihat foto yang baru dia kirim, tapi tanpa token tetap ditolak.
        del c.headers["Authorization"]
        assert c.get(alamat).status_code == 401
