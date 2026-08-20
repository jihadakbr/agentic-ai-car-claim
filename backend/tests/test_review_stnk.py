"""Uji pemeriksaan manusia atas hasil baca STNK.

Yang dijaga di sini: koreksi tersimpan per field, field yang ditandai salah wajib membawa
nilai benarnya, dan koreksi tidak boleh mengubah verdict validitas yang sudah keluar.
"""

import pytest

gradio = pytest.importorskip("gradio", reason="butuh dependensi opsional serve")

from tests.test_api import kirim_klaim, server_uji


@pytest.fixture
def klien(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, nama_db="review-stnk.db") as c:
        yield c


def test_klaim_baru_belum_punya_pemeriksaan_stnk(klien):
    kirim = kirim_klaim(klien)
    assert kirim["review_stnk"] == []


def test_foto_stnk_bisa_dibuka_dari_rincian(klien):
    """Tanpa fotonya, adjuster tidak punya bahan pembanding untuk menilai bacaan mesin."""
    kirim = kirim_klaim(klien)
    urutan = kirim["stnk"]["urutan_foto"]
    assert urutan is not None

    r = klien.get(f"/api/klaim/{kirim['id']}/foto/{urutan}", params={"jenis": "stnk"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/")


def test_field_yang_salah_tersimpan_beserta_nilai_benarnya(klien):
    kirim = kirim_klaim(klien)

    r = klien.post(
        f"/api/klaim/{kirim['id']}/review-stnk",
        json={"penilaian": [
            {"field": "nomor_polisi", "benar": False, "nilai_benar": "B 1234 XYZ"},
            {"field": "nomor_rangka", "benar": True},
        ]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["dinilai"] == 2

    detail = klien.get(f"/api/klaim/{kirim['id']}").json()
    per_field = {x["field"]: x for x in detail["review_stnk"]}
    assert per_field["nomor_polisi"]["benar"] is False
    assert per_field["nomor_polisi"]["nilai_benar"] == "B 1234 XYZ"
    assert per_field["nomor_polisi"]["oleh"] == "admin"
    assert per_field["nomor_rangka"]["benar"] is True
    assert per_field["nomor_rangka"]["nilai_benar"] is None


def test_ditandai_salah_tanpa_nilai_benar_ditolak(klien):
    kirim = kirim_klaim(klien)

    r = klien.post(
        f"/api/klaim/{kirim['id']}/review-stnk",
        json={"penilaian": [{"field": "merk", "benar": False, "nilai_benar": "  "}]},
    )
    assert r.status_code == 400


def test_field_tak_dikenal_ditolak(klien):
    kirim = kirim_klaim(klien)

    r = klien.post(
        f"/api/klaim/{kirim['id']}/review-stnk",
        json={"penilaian": [{"field": "warna_mobil", "benar": True}]},
    )
    assert r.status_code == 400


def test_menilai_ulang_menimpa_bukan_menumpuk(klien):
    """Kalau menumpuk, satu field yang dinilai dua kali terhitung dua kali di ketelitiannya."""
    kirim = kirim_klaim(klien)
    alamat = f"/api/klaim/{kirim['id']}/review-stnk"

    klien.post(alamat, json={"penilaian": [
        {"field": "merk", "benar": False, "nilai_benar": "TOYOTA"},
    ]})
    klien.post(alamat, json={"penilaian": [{"field": "merk", "benar": True}]})

    detail = klien.get(f"/api/klaim/{kirim['id']}").json()
    merk = [x for x in detail["review_stnk"] if x["field"] == "merk"]
    assert len(merk) == 1
    assert merk[0]["benar"] is True
    assert merk[0]["nilai_benar"] is None


def test_koreksi_tidak_mengubah_verdict_validitas(klien):
    """Verdict yang sudah dilihat orang tidak boleh berubah karena isian yang datang belakangan."""
    kirim = kirim_klaim(klien)
    sebelum = kirim["verdict_validitas"]
    cek_sebelum = {c["kode"]: c["lolos"] for c in kirim["cek"]}

    klien.post(
        f"/api/klaim/{kirim['id']}/review-stnk",
        json={"penilaian": [
            {"field": "nomor_rangka", "benar": False, "nilai_benar": "MHKSALAH000000000"},
        ]},
    )

    detail = klien.get(f"/api/klaim/{kirim['id']}").json()
    assert detail["verdict_validitas"] == sebelum
    assert {c["kode"]: c["lolos"] for c in detail["cek"]} == cek_sebelum


def test_pemeriksaan_stnk_ikut_hilang_saat_klaim_dihapus(klien):
    kirim = kirim_klaim(klien)
    klien.post(
        f"/api/klaim/{kirim['id']}/review-stnk",
        json={"penilaian": [{"field": "merk", "benar": True}]},
    )

    assert klien.delete(f"/api/klaim/{kirim['id']}").status_code == 200
    assert klien.get(f"/api/klaim/{kirim['id']}").status_code == 404
