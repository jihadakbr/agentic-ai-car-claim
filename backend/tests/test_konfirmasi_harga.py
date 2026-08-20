"""Uji penjagaan harga pasar bekas di titik keputusan.

Harga bekas menentukan apakah mobil dinyatakan total loss dan berapa besar penawaran
belinya. Angka yang tidak berasal dari katalog tidak boleh melewati titik keputusan tanpa
ada nama manusia yang bertanggung jawab, dan penjagaannya harus ada di server, bukan cuma
berupa tombol yang dimatikan di layar.
"""

from decimal import Decimal

import pytest

from app.agents.harga_pasar import SUMBER_PENCARIAN, SUMBER_TIDAK_DIKETAHUI

gradio = pytest.importorskip("gradio", reason="butuh dependensi opsional serve")

from tests.test_api import kirim_klaim, lengkapi_review, server_uji

# Polis untuk kendaraan yang harga pasar bekasnya sengaja dikosongkan di data awal.
POLIS_TANPA_HARGA = "POL-2025-0141"


@pytest.fixture
def klien(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, nama_db="harga.db") as c:
        yield c


def test_tipe_stnk_yang_cocok_katalog_memakai_harga_database(tmp_path, monkeypatch):
    from tests.test_api import PembacaPalsu

    with server_uji(
        tmp_path, monkeypatch, nama_db="harga-cocok.db",
        pembaca=PembacaPalsu(Type="F601RM GMMFJJ"),
    ) as c:
        biaya = kirim_klaim(c)["biaya"]

    assert biaya["harga_pasar_sumber"] == "database"
    assert biaya["harga_rujukan"] == []


def test_tipe_stnk_yang_meleset_jatuh_ke_harga_polis_bukan_mencari(klien):
    """Tipe kendaraan di STNK berupa kode, dan salah baca satu huruf tidak boleh langsung
    memicu pencarian internet lalu menghasilkan harga mobil yang salah."""
    biaya = kirim_klaim(klien)["biaya"]

    assert biaya["harga_pasar_sumber"] == "database_polis"
    assert "tidak ketemu di katalog" in biaya["harga_pasar_keterangan"]
    assert biaya["harga_rujukan"] == []


def test_kendaraan_berharga_tidak_perlu_dikonfirmasi(klien):
    klaim = kirim_klaim(klien)
    lengkapi_review(klien, klaim)

    r = klien.post(f"/api/klaim/{klaim['id']}/keputusan",
                   json={"keputusan": "setuju", "catatan": ""})
    assert r.status_code == 200, r.text


def test_kendaraan_tanpa_harga_tidak_diam_diam_jadi_perbaikan(klien):
    """Sebelumnya harga kosong menghasilkan rasio nol yang lolos jadi rekomendasi repair."""
    klaim = kirim_klaim(klien, nomor_polis=POLIS_TANPA_HARGA)
    biaya = klaim["biaya"]

    assert biaya["harga_pasar_sumber"] == SUMBER_TIDAK_DIKETAHUI
    assert biaya["rekomendasi"] == "harga_belum_ada"
    assert Decimal(biaya["total_biaya"]) > 0


def test_setuju_ditolak_selama_harga_belum_disahkan(klien):
    klaim = kirim_klaim(klien, nomor_polis=POLIS_TANPA_HARGA)
    lengkapi_review(klien, klaim)

    r = klien.post(f"/api/klaim/{klaim['id']}/keputusan",
                   json={"keputusan": "setuju", "catatan": ""})

    assert r.status_code == 400
    assert "belum disahkan" in r.json()["detail"]


def test_tolak_dan_revisi_tetap_boleh_tanpa_konfirmasi(klien):
    """Menolak klaim tidak menerbitkan uang, jadi tidak perlu menunggu harga disahkan."""
    klaim = kirim_klaim(klien, nomor_polis=POLIS_TANPA_HARGA)
    lengkapi_review(klien, klaim)

    r = klien.post(f"/api/klaim/{klaim['id']}/keputusan",
                   json={"keputusan": "tolak", "catatan": "bukti kurang"})

    assert r.status_code == 200
    assert r.json()["status"] == "ditolak"


def test_konfirmasi_tanpa_koreksi_membuka_tombol_setuju(klien):
    klaim = kirim_klaim(klien, nomor_polis=POLIS_TANPA_HARGA)
    lengkapi_review(klien, klaim)

    konfirmasi = klien.post(f"/api/klaim/{klaim['id']}/konfirmasi-harga", json={})
    assert konfirmasi.status_code == 200
    assert konfirmasi.json()["harga_dikonfirmasi_oleh"] == "admin"

    r = klien.post(f"/api/klaim/{klaim['id']}/keputusan",
                   json={"keputusan": "setuju", "catatan": ""})
    assert r.status_code == 200, r.text


def test_pengesahan_bisa_dibatalkan_lalu_tombol_setuju_terkunci_lagi(klien):
    """Membatalkan pengesahan harus mengembalikan penjagaannya, bukan cuma mengubah layar."""
    klaim = kirim_klaim(klien, nomor_polis=POLIS_TANPA_HARGA)
    lengkapi_review(klien, klaim)
    klien.post(f"/api/klaim/{klaim['id']}/konfirmasi-harga", json={})

    batal = klien.delete(f"/api/klaim/{klaim['id']}/konfirmasi-harga")
    assert batal.status_code == 200, batal.text
    assert batal.json()["harga_dikonfirmasi_oleh"] is None

    r = klien.post(f"/api/klaim/{klaim['id']}/keputusan", json={"keputusan": "setuju"})
    assert r.status_code == 400


def test_batal_ditolak_kalau_harganya_belum_pernah_disahkan(klien):
    klaim = kirim_klaim(klien, nomor_polis=POLIS_TANPA_HARGA)

    assert klien.delete(f"/api/klaim/{klaim['id']}/konfirmasi-harga").status_code == 400


def test_batal_ditolak_kalau_klaimnya_sudah_diputuskan(klien):
    """Harga itu sudah jadi dasar surat yang terbit, jadi keputusannya dibatalkan lebih dulu."""
    klaim = kirim_klaim(klien, nomor_polis=POLIS_TANPA_HARGA)
    lengkapi_review(klien, klaim)
    klien.post(f"/api/klaim/{klaim['id']}/konfirmasi-harga", json={})
    klien.post(f"/api/klaim/{klaim['id']}/keputusan", json={"keputusan": "setuju"})

    assert klien.delete(f"/api/klaim/{klaim['id']}/konfirmasi-harga").status_code == 400

    klien.delete(f"/api/klaim/{klaim['id']}/keputusan")
    assert klien.delete(f"/api/klaim/{klaim['id']}/konfirmasi-harga").status_code == 200


def test_koreksi_harga_menghitung_ulang_rasio_dan_rekomendasi(klien):
    """Harga yang dikoreksi harus mengubah kesimpulan, bukan cuma tersimpan sebagai angka."""
    klaim = kirim_klaim(klien, nomor_polis=POLIS_TANPA_HARGA)
    total = Decimal(klaim["biaya"]["total_biaya"])

    # Harga pasar tepat di bawah dua kali biaya perbaikan, jadi rasionya lewat ambang 75%.
    murah = klien.post(
        f"/api/klaim/{klaim['id']}/konfirmasi-harga",
        json={"harga_dikoreksi": str((total / Decimal("0.9")).quantize(Decimal(1)))},
    ).json()

    assert murah["rekomendasi"] == "total_loss"
    assert murah["total_loss_ratio"] >= murah["ambang_total_loss"]
    assert murah["harga_tawaran_salvage"] is not None
    assert murah["harga_pasar_sumber"] == "adjuster"


def test_koreksi_harga_mahal_menghasilkan_perbaikan(klien):
    klaim = kirim_klaim(klien, nomor_polis=POLIS_TANPA_HARGA)
    total = Decimal(klaim["biaya"]["total_biaya"])

    mahal = klien.post(
        f"/api/klaim/{klaim['id']}/konfirmasi-harga",
        json={"harga_dikoreksi": str((total * 10).quantize(Decimal(1)))},
    ).json()

    assert mahal["rekomendasi"] == "repair"
    assert Decimal(mahal["ditanggung_penanggung"]) > 0


def test_harga_koreksi_nol_ditolak(klien):
    klaim = kirim_klaim(klien, nomor_polis=POLIS_TANPA_HARGA)

    r = klien.post(f"/api/klaim/{klaim['id']}/konfirmasi-harga",
                   json={"harga_dikoreksi": "0"})

    assert r.status_code == 400


def test_koreksi_harga_tercatat_di_jejak_audit(klien):
    klaim = kirim_klaim(klien, nomor_polis=POLIS_TANPA_HARGA)
    klien.post(f"/api/klaim/{klaim['id']}/konfirmasi-harga",
               json={"harga_dikoreksi": "200000000"})

    from sqlalchemy import select

    from app.db.models import AuditLog
    from app.db.session import sesi

    with sesi() as s:
        aksi = [
            a.aksi
            for a in s.scalars(select(AuditLog).where(AuditLog.claim_id == klaim["id"]))
        ]

    assert "harga_pasar_dikoreksi" in aksi


def test_peran_tanpa_hak_putuskan_tidak_boleh_mengesahkan_harga(tmp_path, monkeypatch):
    """Pengesahan harga adalah tanda tangan atas angka, bukan sekadar mengisi formulir."""
    with server_uji(tmp_path, monkeypatch, nama_db="harga-peran.db") as admin:
        klaim = kirim_klaim(admin, nomor_polis=POLIS_TANPA_HARGA)

    with server_uji(
        tmp_path, monkeypatch, nama_db="harga-peran.db", masuk_sebagai="surveyor"
    ) as surveyor:
        r = surveyor.post(f"/api/klaim/{klaim['id']}/konfirmasi-harga", json={})
        assert r.status_code == 403


def test_harga_hasil_pencarian_disimpan_beserta_sumbernya(tmp_path, monkeypatch):
    """Jalur pencarian sungguhan, dengan pencari tiruan supaya tidak menyentuh internet."""
    from app.agents.pencari_web import HasilCari

    class PencariTiruan:
        def cari(self, kueri, maksimal=5):
            return [HasilCari("Harga Almaz bekas", "https://contoh.test/almaz",
                              "Wuling Almaz RS 2022 dijual Rp 235.000.000")]

    class KlienTiruan:
        nama = "tiruan"

        def jawab(self, prompt, max_tokens):
            from app.core.llm import Jawaban, Penggunaan

            return Jawaban(
                '{"harga": 235000000, "alasan": "Dari iklan bekas", "sumber_dipakai": [0]}',
                Penggunaan("tiruan", "m", 80, 20),
            )

    with server_uji(
        tmp_path, monkeypatch, nama_db="harga-cari.db",
        pencari=PencariTiruan(), klien_llm=KlienTiruan(),
    ) as c:
        klaim = kirim_klaim(c, nomor_polis=POLIS_TANPA_HARGA)
        biaya = klaim["biaya"]

        assert biaya["harga_pasar_sumber"] == SUMBER_PENCARIAN
        assert Decimal(biaya["harga_pasar_bekas"]) == Decimal(235_000_000)
        assert [r["url"] for r in biaya["harga_rujukan"]] == ["https://contoh.test/almaz"]

        # Harga dari internet tetap harus disahkan sebelum klaim boleh disetujui.
        lengkapi_review(c, klaim)
        r = c.post(f"/api/klaim/{klaim['id']}/keputusan",
                   json={"keputusan": "setuju", "catatan": ""})
        assert r.status_code == 400
