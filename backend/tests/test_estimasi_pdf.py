"""Uji dokumen estimasi dan alamat yang mengirimkannya."""

import pytest

from app.laporan.estimasi_pdf import rupiah, susun_pdf

gradio = pytest.importorskip("gradio", reason="butuh dependensi opsional serve")

from tests.test_api import kirim_klaim, server_uji


@pytest.fixture
def klien(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, nama_db="pdf.db") as c:
        yield c


def test_rupiah_memakai_pemisah_ribuan():
    assert rupiah("12345678.00") == "Rp 12,345,678"
    assert rupiah(None) == ""


def test_pdf_bisa_disusun_dari_klaim_kosong():
    """Klaim tanpa baris biaya tetap harus menghasilkan dokumen, bukan melempar galat."""
    isi = susun_pdf({"nomor_klaim": "KLM-2026-0001", "biaya": {}, "baris_biaya": []})
    assert isi.startswith(b"%PDF")


def test_alamat_pdf_mengirim_dokumen(klien):
    klaim = kirim_klaim(klien)
    r = klien.get(f"/api/klaim/{klaim['id']}/estimasi.pdf")

    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF")
    assert len(r.content) > 1_000


def test_tanpa_unduh_dokumen_dibuka_di_tempat(klien):
    """Tombol Lihat PDF membuka tab baru, jadi dokumennya tidak boleh langsung terunduh."""
    klaim = kirim_klaim(klien)
    r = klien.get(f"/api/klaim/{klaim['id']}/estimasi.pdf")
    assert r.headers["content-disposition"].startswith("inline")


def test_dengan_unduh_dokumen_tersimpan_bernama_nomor_klaim(klien):
    klaim = kirim_klaim(klien)
    r = klien.get(f"/api/klaim/{klaim['id']}/estimasi.pdf", params={"unduh": 1})

    posisi = r.headers["content-disposition"]
    assert posisi.startswith("attachment")
    assert klaim["nomor_klaim"] in posisi


def test_klaim_tidak_ada_dijawab_404(klien):
    r = klien.get("/api/klaim/tidak-ada/estimasi.pdf")
    assert r.status_code == 404


def test_nomor_part_ikut_sampai_ke_rincian_klaim(klien):
    """Kolom nomor part di dokumen diambil dari katalog, bukan dikarang saat mencetak."""
    klaim = kirim_klaim(klien)
    baris = [b for b in klaim["baris_biaya"] if b["sumber"] == "deteksi"]

    assert baris, "klaim contoh harus punya baris hasil deteksi"
    assert all(b["nomor_part"] for b in baris)


def test_peran_tanpa_izin_lihat_klaim_ditolak(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, nama_db="pdf-admin.db") as admin:
        klaim = kirim_klaim(admin)

    with server_uji(
        tmp_path, monkeypatch, nama_db="pdf-admin.db", masuk_sebagai="surveyor"
    ) as surveyor:
        r = surveyor.get(f"/api/klaim/{klaim['id']}/estimasi.pdf")
        assert r.status_code == 403


def test_token_lewat_query_diterima(tmp_path, monkeypatch):
    """Tab baru dan unduhan tidak bisa membawa header, jadi tokennya lewat query."""
    with server_uji(tmp_path, monkeypatch, nama_db="pdf-token.db") as klien:
        klaim = kirim_klaim(klien)
        token = klien.headers["Authorization"].removeprefix("Bearer ")
        del klien.headers["Authorization"]

        r = klien.get(f"/api/klaim/{klaim['id']}/estimasi.pdf", params={"token": token})
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF")
