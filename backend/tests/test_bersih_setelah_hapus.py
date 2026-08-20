"""Bukti bahwa menghapus seluruh klaim lewat UI benar-benar mengosongkan jejaknya.

Tabel master sengaja tidak ikut diperiksa, karena isinya memang harus tetap ada. Begitu juga
`audit_log`, yang justru mencatat penghapusannya dan tidak boleh ikut hilang.
"""

import pytest
from sqlalchemy import func, select

from app.db import session as sesi_modul
from app.db.models import (
    AdjusterDecision,
    AuditLog,
    Claim,
    ClaimPhoto,
    CostEstimate,
    CostEstimateLine,
    DetectionResult,
    DetectionReview,
    HargaPasarRujukan,
    LlmUsage,
    PhotoRequest,
    SalvageOffer,
    Spk,
    StnkExtraction,
    StnkReview,
    ValidityCheck,
)

from .test_api import kirim_klaim, lengkapi_review, server_uji

TABEL_JEJAK = (
    Claim, ClaimPhoto, DetectionResult, DetectionReview, StnkExtraction, StnkReview,
    ValidityCheck, CostEstimate, CostEstimateLine, PhotoRequest, Spk, SalvageOffer,
    AdjusterDecision, HargaPasarRujukan, LlmUsage,
)


def _sisa() -> dict[str, int]:
    with sesi_modul.sesi() as s:
        return {
            t.__tablename__: s.scalar(select(func.count()).select_from(t)) or 0
            for t in TABEL_JEJAK
        }


@pytest.fixture
def klien_bersih(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, "bersih.db") as c:
        yield c


def test_hapus_semua_klaim_mengosongkan_seluruh_jejak(klien_bersih, tmp_path):
    folder = tmp_path / "foto"
    for _ in range(2):
        klaim = kirim_klaim(klien_bersih)
        lengkapi_review(klien_bersih, klaim)
        klien_bersih.post(
            f"/api/klaim/{klaim['id']}/keputusan",
            json={"keputusan": "setuju", "catatan": "oke"},
        )

    daftar = klien_bersih.get("/api/klaim").json()
    for k in daftar:
        assert klien_bersih.delete(f"/api/klaim/{k['id']}").status_code == 200

    sisa = _sisa()
    assert sisa == dict.fromkeys(sisa, 0), f"masih ada baris tertinggal: {sisa}"
    assert not list(folder.rglob("*.jpg")), "masih ada berkas foto tertinggal"

    # Baris audit yang tersisa harus lepas dari klaim mana pun. Baris yang masih menempel
    # ke klaim yang sudah hilang berarti ada jejak yang lolos dari penghapusan.
    with sesi_modul.sesi() as s:
        menempel = s.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.claim_id.isnot(None))
        )
    assert menempel == 0, "ada baris audit yang masih menunjuk klaim yang sudah dihapus"


def test_nomor_klaim_mulai_dari_satu_lagi_setelah_semua_dihapus(klien_bersih):
    lama = kirim_klaim(klien_bersih)
    assert klien_bersih.delete(f"/api/klaim/{lama['id']}").status_code == 200

    baru = kirim_klaim(klien_bersih)
    assert baru["nomor_klaim"].endswith("-0001")
