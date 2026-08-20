"""Uji surat perintah kerja dan penawaran beli, beserta alamat yang mengirimkannya."""

import pytest

from app.laporan.surat_pdf import susun_penawaran, susun_spk

gradio = pytest.importorskip("gradio", reason="butuh dependensi opsional serve")

from tests.test_api import kirim_klaim, lengkapi_review, server_uji


@pytest.fixture
def klien(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, nama_db="surat.db") as c:
        yield c


KLAIM_KOSONG = {"nomor_klaim": "KLM-2026-0001", "biaya": {}, "keputusan": []}


def test_spk_bisa_disusun_tanpa_blok_biaya():
    """Klaim tanpa estimasi tetap harus menghasilkan dokumen, bukan melempar galat."""
    isi = susun_spk(KLAIM_KOSONG, {"nomor": "SPK-2026-0001", "tujuan": "Bengkel",
                                   "nilai": "1000000"})
    assert isi.startswith(b"%PDF")


def test_penawaran_bisa_disusun_tanpa_blok_biaya():
    isi = susun_penawaran(KLAIM_KOSONG, {"tujuan": "Budi", "nilai": "50000000",
                                         "harga_pasar_bekas": "160000000",
                                         "faktor_salvage": 0.3})
    assert isi.startswith(b"%PDF")


def test_surat_belum_ada_sebelum_klaim_diputuskan(klien):
    klaim = kirim_klaim(klien)
    r = klien.get(f"/api/klaim/{klaim['id']}/surat.pdf")
    assert r.status_code == 404

    assert klien.get(f"/api/klaim/{klaim['id']}").json()["surat"] is None


def test_alamat_surat_mengirim_dokumen_setelah_disetujui(klien):
    klaim = kirim_klaim(klien)
    lengkapi_review(klien, klaim)
    klien.post(f"/api/klaim/{klaim['id']}/keputusan", json={"keputusan": "setuju"})

    r = klien.get(f"/api/klaim/{klaim['id']}/surat.pdf")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF")
    assert "inline" in r.headers["content-disposition"]

    unduh = klien.get(f"/api/klaim/{klaim['id']}/surat.pdf?unduh=1")
    assert "attachment" in unduh.headers["content-disposition"]


def test_klaim_total_loss_mencetak_penawaran_beli(tmp_path, monkeypatch):
    """Klaim total loss tidak punya SPK, jadi yang tercetak harus penawaran belinya."""
    from app.pipeline.detektor import DetektorContoh

    berat = DetektorContoh(kerusakan="Dent", rasio_kerusakan=0.95)
    with server_uji(tmp_path, monkeypatch, "surat-salvage.db", detektor=berat) as c:
        kirim = kirim_klaim(c)
        lengkapi_review(c, kirim)
        c.post(f"/api/klaim/{kirim['id']}/keputusan", json={"keputusan": "setuju"})

        surat = c.get(f"/api/klaim/{kirim['id']}").json()["surat"]
        assert surat["jenis"] == "penawaran_beli"

        r = c.get(f"/api/klaim/{kirim['id']}/surat.pdf?unduh=1")
        assert r.status_code == 200, r.text
        assert r.content.startswith(b"%PDF")
        assert f"Penawaran-{kirim['nomor_klaim']}.pdf" in r.headers["content-disposition"]


def test_surat_ikut_hilang_saat_keputusan_dibatalkan(klien):
    """Surat yang sudah ditarik tidak boleh tetap bisa dicetak."""
    klaim = kirim_klaim(klien)
    lengkapi_review(klien, klaim)
    klien.post(f"/api/klaim/{klaim['id']}/keputusan", json={"keputusan": "setuju"})
    klien.delete(f"/api/klaim/{klaim['id']}/keputusan")

    assert klien.get(f"/api/klaim/{klaim['id']}/surat.pdf").status_code == 404
    assert klien.get(f"/api/klaim/{klaim['id']}").json()["surat"] is None
