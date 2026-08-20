"""Uji Manajemen Akses: pengguna, peran, hak akses, dan log aktivitasnya.

Yang paling penting dibuktikan di sini bukan bahwa layarnya bisa mengubah data, tapi bahwa
perubahannya benar-benar menutup dan membuka alamat API, dan bahwa sistem tidak bisa
dikunci sampai tidak ada seorang pun yang bisa membetulkannya kembali.
"""

import pytest

from app.core import izin

gradio = pytest.importorskip("gradio", reason="butuh dependensi opsional serve")

from tests.test_api import SANDI, server_uji


@pytest.fixture
def admin(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, "akses.db", masuk_sebagai="admin") as c:
        yield c


def masuk_sebagai(klien, username):
    r = klien.post("/api/login", json={"username": username, "password": SANDI})
    assert r.status_code == 200, r.text
    klien.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return r.json()


def test_login_membawa_daftar_izin(admin):
    punya_surveyor = ["klaim.kirim", "klaim.lacak_sendiri", "polis.lihat"]
    data = masuk_sebagai(admin, "surveyor")
    assert data["izin"] == punya_surveyor
    assert admin.get("/api/saya").json()["izin"] == punya_surveyor


def test_peran_bawaan_terisi_beserta_haknya(admin):
    data = admin.get("/api/akses/peran").json()
    peran = {p["kode"]: p for p in data["peran"]}

    assert peran["admin"]["bawaan"] is True
    assert peran["admin"]["jumlah_pengguna"] == 1
    assert "akses.kelola" in peran["admin"]["izin"]
    assert "klaim.putuskan" in peran["adjuster"]["izin"]
    assert "klaim.putuskan" not in peran["surveyor"]["izin"]
    assert len(data["katalog_izin"]) == len(izin.KATALOG)


def test_hak_yang_dicabut_langsung_menutup_alamatnya(admin):
    """Perubahan harus berlaku tanpa menunggu orangnya masuk ulang."""
    masuk_sebagai(admin, "adjuster")
    assert admin.get("/api/overview").status_code == 200

    masuk_sebagai(admin, "admin")
    sisa = ["klaim.lihat", "klaim.review_deteksi", "klaim.putuskan"]
    r = admin.put("/api/akses/peran/adjuster/izin", json={"izin": sisa})
    assert r.status_code == 200

    masuk_sebagai(admin, "adjuster")
    assert admin.get("/api/overview").status_code == 403
    assert admin.get("/api/klaim").status_code == 200


def test_hak_yang_diberikan_langsung_membuka_alamatnya(admin):
    masuk_sebagai(admin, "surveyor")
    assert admin.get("/api/overview").status_code == 403

    masuk_sebagai(admin, "admin")
    admin.put(
        "/api/akses/peran/surveyor/izin",
        json={"izin": ["polis.lihat", "klaim.kirim", "overview.lihat"]},
    )

    masuk_sebagai(admin, "surveyor")
    assert admin.get("/api/overview").status_code == 200


def test_peran_pengguna_bisa_dipindah(admin):
    r = admin.post("/api/akses/pengguna/surveyor", json={"peran": "adjuster"})
    assert r.status_code == 200
    assert r.json() == {"username": "surveyor", "dari": "surveyor", "ke": "adjuster"}

    masuk_sebagai(admin, "surveyor")
    assert admin.get("/api/klaim").status_code == 200
    assert admin.get("/api/polis/POL-2024-0037").status_code == 403


def test_peran_baru_bisa_dibuat_lalu_dipakai(admin):
    admin.post(
        "/api/akses/peran",
        json={"kode": "peninjau", "nama": "Peninjau", "keterangan": "Cuma boleh melihat"},
    )
    admin.put("/api/akses/peran/peninjau/izin", json={"izin": ["klaim.lihat"]})
    admin.post("/api/akses/pengguna/surveyor", json={"peran": "peninjau"})

    masuk_sebagai(admin, "surveyor")
    assert admin.get("/api/klaim").status_code == 200
    assert admin.get("/api/overview").status_code == 403
    assert admin.post("/api/klaim/apa-saja/keputusan", json={"keputusan": "setuju"}).status_code == 403


def test_peran_bawaan_dan_yang_masih_dipakai_tidak_bisa_dihapus(admin):
    bawaan = admin.delete("/api/akses/peran/adjuster")
    assert bawaan.status_code == 400
    assert "bawaan" in bawaan.json()["detail"]

    admin.post("/api/akses/peran", json={"kode": "peninjau", "nama": "Peninjau"})
    admin.post("/api/akses/pengguna/surveyor", json={"peran": "peninjau"})
    dipakai = admin.delete("/api/akses/peran/peninjau")
    assert dipakai.status_code == 400
    assert "masih dipakai" in dipakai.json()["detail"]

    admin.post("/api/akses/pengguna/surveyor", json={"peran": "surveyor"})
    assert admin.delete("/api/akses/peran/peninjau").status_code == 200


def test_pengelola_akses_terakhir_tidak_bisa_dilucuti(admin):
    """Kalau ini boleh, layar Manajemen Akses tidak bisa dibuka siapa pun lagi selamanya."""
    pindah = admin.post("/api/akses/pengguna/admin", json={"peran": "surveyor"})
    assert pindah.status_code == 400
    assert "satu-satunya akun" in pindah.json()["detail"]

    matikan = admin.post("/api/akses/pengguna/admin", json={"aktif": False})
    assert matikan.status_code == 400

    cabut = admin.put(
        "/api/akses/peran/admin/izin", json={"izin": ["klaim.lihat"]}
    )
    assert cabut.status_code == 400
    assert "satu-satunya peran" in cabut.json()["detail"]


def test_hak_akses_yang_tidak_dikenal_ditolak(admin):
    r = admin.put("/api/akses/peran/adjuster/izin", json={"izin": ["klaim.lihat", "ngawur"]})
    assert r.status_code == 400
    assert "ngawur" in r.json()["detail"]


def test_log_aktivitas_mencatat_siapa_mengubah_apa(admin):
    admin.post("/api/akses/pengguna/surveyor", json={"peran": "adjuster"})
    admin.put("/api/akses/peran/adjuster/izin", json={"izin": ["klaim.lihat"]})

    log = admin.get("/api/akses/log").json()
    aksi = [b["aksi"] for b in log]
    assert "peran_pengguna_diubah" in aksi
    assert "hak_akses_diubah" in aksi

    ubah = next(b for b in log if b["aksi"] == "peran_pengguna_diubah")
    assert ubah["detail"]["oleh"] == "admin"
    assert ubah["detail"]["dari"] == "surveyor"
    assert ubah["waktu"].endswith("+00:00")

    hak = next(b for b in log if b["aksi"] == "hak_akses_diubah")
    assert "overview.lihat" in hak["detail"]["dicabut"]


def test_manajemen_akses_tertutup_untuk_selain_pemegang_haknya(admin):
    for peran in ("surveyor", "adjuster"):
        masuk_sebagai(admin, peran)
        assert admin.get("/api/akses/pengguna").status_code == 403
        assert admin.get("/api/akses/peran").status_code == 403
        assert admin.get("/api/akses/log").status_code == 403
        assert admin.post("/api/akses/peran", json={"kode": "x", "nama": "X"}).status_code == 403
