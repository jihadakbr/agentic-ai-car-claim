"""Menyimpan dan membaca hasil klaim dari database.

Dipisah dari perakit alur supaya perakitnya tetap bisa diuji tanpa database. Modul ini yang
tahu soal tabel, perakit alur cuma tahu soal dataclass.

Setiap tahap penting meninggalkan baris di audit log, dan pemakaian token dicatat per klaim
sehingga angka riilnya bisa ditunjukkan saat presentasi, bukan cuma perkiraan.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.claim_assessment import KonteksTambahan as Konteks
from app.agents.harga_pasar import (
    SUMBER_PENCARIAN,
    SUMBER_TIDAK_DIKETAHUI,
)
from app.db.models import (
    AdjusterDecision,
    AppUser,
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
    Policy,
    SalvageOffer,
    Spk,
    StnkExtraction,
    StnkReview,
    ValidityCheck,
    VehicleModel,
)
from app.pipeline.cost_engine import BarisBiaya, sebaran, susun_estimasi

# Harga yang sudah disahkan atau dikoreksi adjuster. Dibedakan dari sumber lain supaya
# jelas bahwa angkanya sudah lewat tangan manusia.
SUMBER_ADJUSTER = "adjuster"
from app.db.repository import (
    ambil_config_float,
    ambil_config_rupiah,
    cari_kendaraan,
    muat_katalog,
    muat_matriks,
    muat_tarif,
)
from app.pipeline.orkestrasi import (
    STATUS_MENUNGGU_FOTO,
    STATUS_SIAP_REVIEW,
    HasilKlaim,
    Referensi,
)
from app.pipeline.validity import (
    Ambang,
    DataPolis,
    HasilStnk,
    TemuanKlaim,
    TemuanRiwayat,
    cari_kerusakan_lama,
)

BENGKEL_REKANAN = "Bengkel Rekanan Utama, Jakarta"

_log = logging.getLogger(__name__)


def waktu_iso(nilai: datetime | None) -> str | None:
    """Waktu berpenanda zona, selalu UTC.

    SQLite membuang penanda zona saat menyimpan, jadi nilainya kembali tanpa zona
    meski disimpan sebagai UTC. Tanpa penanda, browser membacanya sebagai jam lokal
    dan tampil tujuh jam meleset di Indonesia.
    """
    if nilai is None:
        return None
    if nilai.tzinfo is None:
        nilai = nilai.replace(tzinfo=UTC)
    return nilai.isoformat()


def nomor_klaim_baru(s: Session) -> str:
    """Nomor berurutan per tahun, gampang disebut saat presentasi.

    Diambil dari nomor tertinggi yang pernah dipakai, bukan dari jumlah baris. Kalau dari
    jumlah baris, menghapus satu klaim membuat nomor berikutnya menabrak nomor yang masih
    terpakai dan penyimpanan gagal.
    """
    tahun = datetime.now(UTC).year
    awalan = f"KLM-{tahun}-"
    tertinggi = s.scalar(
        select(func.max(Claim.nomor_klaim)).where(Claim.nomor_klaim.like(f"{awalan}%"))
    )
    urutan = int(tertinggi[len(awalan):]) if tertinggi else 0
    return f"{awalan}{urutan + 1:04d}"


def catat_audit(s: Session, claim_id: str | None, tahap: str, aksi: str, detail: dict) -> None:
    s.add(AuditLog(claim_id=claim_id, tahap=tahap, aksi=aksi, detail=detail))


def muat_referensi(s: Session, vehicle_model_id: str) -> Referensi:
    """Kumpulkan seluruh data acuan yang dibutuhkan sepanjang alur, sekali jalan."""
    return Referensi(
        katalog=muat_katalog(s, vehicle_model_id),
        matriks=muat_matriks(s),
        tarif=muat_tarif(s),
        ambang_total_loss=ambil_config_float(s, "ambang_total_loss"),
        own_risk=ambil_config_rupiah(s, "own_risk"),
        faktor_salvage=ambil_config_float(s, "faktor_salvage"),
        ambang=Ambang(
            confidence_damage=ambil_config_float(s, "ambang_confidence_damage"),
            phash_identik=int(ambil_config_float(s, "ambang_phash_identik")),
            min_foto_konsisten=int(ambil_config_float(s, "min_foto_konsisten")),
            selisih_rasio_sama=ambil_config_float(s, "ambang_selisih_rasio_sama"),
        ),
        min_foto_bagian_diganti=int(ambil_config_float(s, "min_foto_bagian_diganti")),
        ambang_keyakinan_foto=ambil_config_float(s, "ambang_confidence_kendaraan"),
        ambang_ketajaman_foto=ambil_config_float(s, "ambang_ketajaman_foto"),
    )


def harga_di_katalog(s: Session, merk: str, tipe: str, tahun: int | None) -> float | None:
    """Harga pasar bekas satu kendaraan menurut katalog, None kalau tidak ada.

    Dipakai agent sebagai alat pertama sebelum memutuskan perlu mencari ke internet.
    Kendaraan yang ada barisnya tapi harganya kosong tetap dianggap tidak ada, karena
    yang dibutuhkan angkanya, bukan barisnya.
    """
    kendaraan = cari_kendaraan(s, merk, tipe, tahun)
    if kendaraan is None or not kendaraan.harga_pasar_bekas:
        return None
    return kendaraan.harga_pasar_bekas


def konteks_untuk_agent(s: Session, policy_id: str, kecuali_claim_id: str) -> Konteks:
    """Bahan tambahan yang boleh diminta agent di pass kedua.

    Ditarik hanya kalau agent memintanya, bukan selalu, karena tiap baris di sini ikut
    jadi token di prompt kedua dan kuota gratisnya ketat.
    """
    riwayat = []
    for k in s.scalars(
        select(Claim)
        .where(Claim.policy_id == policy_id, Claim.id != kecuali_claim_id)
        .order_by(Claim.created_at.desc())
        .limit(5)
    ):
        est = s.scalar(select(CostEstimate).where(CostEstimate.claim_id == k.id))
        nilai = f", biaya Rp {est.total_biaya:,.0f}" if est else ""
        riwayat.append(
            f"Klaim {k.nomor_klaim} pada polis yang sama: status {k.status}, "
            f"validitas {k.verdict_validitas or 'belum dinilai'}{nilai}"
        )

    ambang = ambil_config_float(s, "ambang_total_loss")
    own_risk = ambil_config_rupiah(s, "own_risk")
    salvage = ambil_config_float(s, "faktor_salvage")
    panduan = [
        f"Ambang total loss {ambang:.0%} mengikuti definisi Constructive Total Loss PSAKBI",
        f"Own risk yang ditanggung tertanggung Rp {own_risk:,.0f} per kejadian",
        f"Penawaran beli kendaraan dihitung {salvage:.0%} dari harga pasar bekas",
    ]
    return Konteks(panduan_underwriting=panduan, klaim_serupa=riwayat)


def phash_klaim_lain(s: Session, kecuali_claim_id: str | None = None) -> dict[str, str]:
    """Kumpulkan sidik jari seluruh foto klaim lain, untuk cek foto dipakai ulang.

    Foto milik klaim yang sedang diproses dikecualikan, karena kalau ikut dibandingkan,
    klaim akan selalu menuduh dirinya sendiri memakai ulang fotonya sendiri.
    """
    q = (
        select(ClaimPhoto.phash, Claim.nomor_klaim)
        .join(Claim, Claim.id == ClaimPhoto.claim_id)
        .where(ClaimPhoto.phash.is_not(None))
    )
    if kecuali_claim_id:
        q = q.where(ClaimPhoto.claim_id != kecuali_claim_id)
    return {phash: nomor for phash, nomor in s.execute(q) if phash}


def riwayat_temuan_polis(s: Session, klaim: Claim) -> list[TemuanRiwayat]:
    """Kumpulkan kerusakan yang tercatat di klaim sebelumnya pada polis yang sama.

    Dipakai cek C7 untuk mengenali kerusakan yang tidak pernah diperbaiki lalu diajukan
    lagi. Yang diambil cuma klaim yang masuk lebih dulu, karena kerusakan lama menurut
    definisinya sudah ada sebelum klaim ini dibuat. Tanpa batas itu, klaim pertama justru
    dituduh mengulang kerusakan dari klaim yang saat itu belum ada.
    """
    q = (
        select(
            DetectionResult.part_class,
            DetectionResult.sisi,
            DetectionResult.damage_class,
            DetectionResult.rasio_luas,
            Claim.nomor_klaim,
            Claim.status,
        )
        .join(ClaimPhoto, ClaimPhoto.id == DetectionResult.claim_photo_id)
        .join(Claim, Claim.id == ClaimPhoto.claim_id)
        .where(
            Claim.policy_id == klaim.policy_id,
            Claim.id != klaim.id,
            Claim.created_at < klaim.created_at,
        )
    )
    return [
        TemuanRiwayat(
            part_class=part_class,
            sisi=sisi,
            damage_class=damage_class,
            rasio_luas=rasio_luas,
            nomor_klaim=nomor_klaim,
            status=status,
        )
        for part_class, sisi, damage_class, rasio_luas, nomor_klaim, status in s.execute(q)
    ]


def data_polis(polis: Policy) -> DataPolis:
    return DataPolis(
        nomor_polisi=polis.nomor_polisi,
        nomor_rangka=polis.nomor_rangka,
        nomor_mesin=polis.nomor_mesin,
        nama_pemegang=polis.nama_pemegang,
    )


def buat_klaim(
    s: Session, polis: Policy, kendaraan: VehicleModel | None, surveyor: str
) -> Claim:
    klaim = Claim(
        nomor_klaim=nomor_klaim_baru(s),
        policy_id=polis.id,
        vehicle_model_id=kendaraan.id if kendaraan else None,
        surveyor=surveyor,
        status="diproses",
    )
    s.add(klaim)
    s.flush()
    catat_audit(s, klaim.id, "intake", "klaim_dibuat", {"nomor_polis": polis.nomor_polis})
    return klaim


def simpan_stnk(s: Session, claim_id: str, stnk: HasilStnk, teks_mentah: str = "",
                pakai_llm: bool = False) -> None:
    lama = s.scalar(select(StnkExtraction).where(StnkExtraction.claim_id == claim_id))
    if lama is not None:
        return
    s.add(
        StnkExtraction(
            claim_id=claim_id,
            merk=stnk.merk,
            tipe=stnk.tipe,
            tahun=stnk.tahun,
            nomor_polisi=stnk.nomor_polisi,
            nomor_rangka=stnk.nomor_rangka,
            nomor_mesin=stnk.nomor_mesin,
            nama_pemilik=stnk.nama_pemilik,
            teks_mentah=teks_mentah,
            pakai_llm=pakai_llm,
        )
    )
    catat_audit(s, claim_id, "stnk_ocr", "stnk_dibaca",
                {"merk": stnk.merk, "tahun": stnk.tahun, "pakai_llm": pakai_llm})


def simpan_foto(
    s: Session, claim_id: str, jalur: list[str], phash: list[str | None],
    jenis: str = "kerusakan",
    mulai_urutan: int = 0,
    bentuk: list[dict] | None = None,
) -> None:
    for i, (p, h) in enumerate(zip(jalur, phash, strict=True)):
        s.add(
            ClaimPhoto(
                claim_id=claim_id, jenis=jenis, path=p, phash=h, urutan=mulai_urutan + i,
                bentuk=(bentuk[i] if bentuk and i < len(bentuk) else {}),
            )
        )
    catat_audit(s, claim_id, "intake", "foto_disimpan", {"jumlah": len(jalur), "jenis": jenis})


def perbarui_phash(s: Session, claim_id: str, phash: list[str | None]) -> None:
    """Isi sidik jari foto kerusakan setelah pipeline selesai menghitungnya.

    Barisnya ditulis lebih dulu saat klaim diterima, supaya surveyor tidak perlu menunggu
    pipeline. Sidik jarinya menyusul karena dihitung di dalam pipeline.
    """
    foto = list(
        s.scalars(
            select(ClaimPhoto)
            .where(ClaimPhoto.claim_id == claim_id, ClaimPhoto.jenis == "kerusakan")
            .order_by(ClaimPhoto.urutan)
        )
    )
    for baris, nilai in zip(foto, phash, strict=False):
        baris.phash = nilai


def hapus_foto_jenis(s: Session, claim_id: str, jenis: str) -> None:
    """Buang baris foto satu jenis, dipakai sebelum menulis ulang overlay."""
    s.query(ClaimPhoto).filter(
        ClaimPhoto.claim_id == claim_id, ClaimPhoto.jenis == jenis
    ).delete()
    s.flush()


def hapus_klaim(s: Session, klaim: Claim, lemari=None) -> dict:
    """Hapus satu klaim beserta seluruh jejaknya.

    Urutannya dari anak ke induk supaya tidak ada baris yang menggantung tanpa induknya.
    Berkas fotonya ikut dihapus kalau lemari penyimpanan diberikan.

    Jejak auditnya ikut hilang, dan itu memang konsekuensi menghapus. Karena itu satu baris
    audit baru ditulis berisi nomor klaim yang dihapus dan siapa yang menghapus.
    """
    # Penilaian adjuster menunjuk ke baris deteksi, jadi harus lepas lebih dulu.
    # Postgres menolak menghapus baris yang masih ditunjuk, SQLite membiarkannya.
    s.query(DetectionReview).filter(DetectionReview.claim_id == klaim.id).delete()

    foto = list(s.scalars(select(ClaimPhoto).where(ClaimPhoto.claim_id == klaim.id)))
    for f in foto:
        s.query(DetectionResult).filter(DetectionResult.claim_photo_id == f.id).delete()
        if lemari is not None and f.path:
            try:
                lemari.hapus(f.path)
            except Exception:  # noqa: BLE001
                # Berkasnya boleh gagal dihapus, barisnya tetap harus hilang. Foto
                # tertinggal jauh lebih ringan akibatnya daripada klaim setengah terhapus.
                _log.warning("foto klaim gagal dihapus: %s", f.path, exc_info=True)

    estimasi = list(s.scalars(select(CostEstimate).where(CostEstimate.claim_id == klaim.id)))
    for e in estimasi:
        s.query(CostEstimateLine).filter(CostEstimateLine.cost_estimate_id == e.id).delete()

    for tabel in (
        ClaimPhoto, StnkExtraction, StnkReview, ValidityCheck,
        CostEstimate, PhotoRequest, Spk, SalvageOffer, AdjusterDecision, AuditLog,
        LlmUsage, HargaPasarRujukan,
    ):
        s.query(tabel).filter(tabel.claim_id == klaim.id).delete()

    nomor = klaim.nomor_klaim
    s.delete(klaim)
    s.flush()
    return {"nomor_klaim": nomor, "foto_dihapus": len(foto)}


def simpan_temuan_foto(s: Session, claim_id: str, temuan_per_foto: list) -> int:
    """Simpan temuan per foto, supaya adjuster bisa menelusuri angka biaya kembali ke fotonya.

    Hasil lama dihapus lebih dulu, karena klaim yang diproses ulang setelah foto tambahan
    masuk harus menampilkan temuan terbaru saja. Pipeline menilai seluruh foto kerusakan
    berurutan, jadi pasangannya dicari lewat posisi, bukan lewat nilai urutan.
    """
    foto = list(
        s.scalars(
            select(ClaimPhoto)
            .where(ClaimPhoto.claim_id == claim_id, ClaimPhoto.jenis == "kerusakan")
            .order_by(ClaimPhoto.urutan)
        )
    )
    for f in foto:
        s.query(DetectionResult).filter(DetectionResult.claim_photo_id == f.id).delete()

    jumlah = 0
    for cocok, temuan in zip(foto, temuan_per_foto, strict=False):
        for t in temuan:
            s.add(
                DetectionResult(
                    claim_photo_id=cocok.id,
                    part_class=t.part_class,
                    sisi=t.sisi,
                    damage_class=t.damage_class,
                    confidence_part=t.confidence_part,
                    confidence_damage=t.confidence_damage,
                    luas_part_px=t.luas_part_px,
                    luas_damage_px=t.luas_damage_px,
                    luas_irisan_px=t.luas_irisan_px,
                    rasio_luas=t.rasio_luas,
                    part_urutan=t.part_urutan,
                    damage_urutan=t.damage_urutan,
                )
            )
            jumlah += 1
    return jumlah


def jalur_foto_kerusakan(s: Session, claim_id: str) -> list[str]:
    """Jalur seluruh foto kerusakan milik satu klaim, urut sesuai pengirimannya."""
    return list(
        s.scalars(
            select(ClaimPhoto.path)
            .where(ClaimPhoto.claim_id == claim_id, ClaimPhoto.jenis == "kerusakan")
            .order_by(ClaimPhoto.urutan)
        )
    )


def stnk_tersimpan(s: Session, claim_id: str) -> HasilStnk:
    """Ambil hasil pembacaan STNK yang sudah tersimpan.

    Dipakai saat klaim diproses ulang setelah foto tambahan masuk. STNK-nya tidak dibaca
    ulang karena lembarnya sama, dan membacanya lagi cuma menambah waktu tanpa hasil baru.
    """
    baris = s.scalar(select(StnkExtraction).where(StnkExtraction.claim_id == claim_id))
    if baris is None:
        return HasilStnk()
    return HasilStnk(
        merk=baris.merk, tipe=baris.tipe, tahun=baris.tahun,
        nomor_polisi=baris.nomor_polisi, nomor_rangka=baris.nomor_rangka,
        nomor_mesin=baris.nomor_mesin, nama_pemilik=baris.nama_pemilik,
    )


def siapkan_kirim_ulang(s: Session, claim_id: str, oleh: str) -> list[str]:
    """Kosongkan kiriman lama supaya foto yang baru masuk sebagai kiriman yang utuh.

    Foto lamanya memang diminta diganti, jadi barisnya dihapus sekalian dengan temuan dan
    penilaian di atasnya. Menyisakannya cuma membuat foto yang sudah dinyatakan tidak layak
    tetap ikut menghitung biaya.

    Berkas gambarnya tidak dihapus di sini, jalurnya dikembalikan supaya pemanggil yang
    menghapus lewat penyimpanannya sendiri. Penyimpanannya bisa folder atau cloud, dan
    fungsi ini cuma mengurus database.
    """
    jenis_dibuang = ["kerusakan", "overlay", "stnk"]
    lama = list(
        s.scalars(
            select(ClaimPhoto).where(
                ClaimPhoto.claim_id == claim_id, ClaimPhoto.jenis.in_(jenis_dibuang)
            )
        )
    )
    jalur = [f.path for f in lama]
    # Penilaian adjuster menunjuk ke baris deteksi, jadi harus lepas lebih dulu.
    # Postgres menolak menghapus baris yang masih ditunjuk, SQLite membiarkannya.
    s.query(DetectionReview).filter(DetectionReview.claim_id == claim_id).delete()
    for f in lama:
        s.query(DetectionResult).filter(DetectionResult.claim_photo_id == f.id).delete()
        s.delete(f)

    s.query(StnkReview).filter(StnkReview.claim_id == claim_id).delete()
    s.query(StnkExtraction).filter(StnkExtraction.claim_id == claim_id).delete()

    # Keputusan revisinya ikut ditarik. Kalau dibiarkan, klaim membawa dua keputusan yang
    # saling bertentangan begitu adjuster memutuskan lagi setelah foto barunya masuk.
    s.query(AdjusterDecision).filter(AdjusterDecision.claim_id == claim_id).delete()

    s.flush()
    catat_audit(s, claim_id, "intake", "kiriman_lama_dihapus",
                {"jumlah": len(lama), "oleh": oleh})
    return jalur


def tandai_permintaan_dipenuhi(s: Session, claim_id: str, jumlah_foto_baru: int) -> None:
    for p in s.scalars(
        select(PhotoRequest).where(
            PhotoRequest.claim_id == claim_id, PhotoRequest.dipenuhi.is_(False)
        )
    ):
        p.dipenuhi = True
    catat_audit(s, claim_id, "intake", "foto_tambahan_diterima", {"jumlah": jumlah_foto_baru})


def simpan_hasil(s: Session, klaim: Claim, hasil: HasilKlaim) -> None:
    """Simpan seluruh keluaran satu putaran pemrosesan.

    Hasil lama dihapus lebih dulu, karena klaim yang diproses ulang setelah foto tambahan
    masuk harus menampilkan hasil terbaru saja. Menumpuk dua putaran membuat layar adjuster
    memuat baris biaya ganda.
    """
    s.query(ValidityCheck).filter(ValidityCheck.claim_id == klaim.id).delete()
    s.query(HargaPasarRujukan).filter(HargaPasarRujukan.claim_id == klaim.id).delete()
    lama = s.scalar(select(CostEstimate).where(CostEstimate.claim_id == klaim.id))
    if lama is not None:
        s.query(CostEstimateLine).filter(
            CostEstimateLine.cost_estimate_id == lama.id
        ).delete()
        s.delete(lama)
    s.flush()

    for c in hasil.cek:
        s.add(
            ValidityCheck(
                claim_id=klaim.id, kode=c.kode, nama=c.nama, lolos=c.lolos,
                tingkat=c.tingkat, alasan=c.alasan, detail=c.detail,
            )
        )

    est = hasil.estimasi
    baris_est = CostEstimate(
        claim_id=klaim.id,
        total_part=est.total_part,
        total_jasa=est.total_jasa,
        total_biaya=est.total_biaya,
        harga_pasar_bekas=est.harga_pasar_bekas,
        harga_pasar_sumber=hasil.harga_pasar.sumber,
        harga_pasar_keterangan=hasil.harga_pasar.keterangan,
        total_loss_ratio=est.total_loss_ratio,
        ambang_total_loss=est.ambang_total_loss,
        rekomendasi=est.rekomendasi,
        own_risk=est.own_risk,
        ditanggung_penanggung=est.ditanggung_penanggung,
        harga_tawaran_salvage=est.harga_tawaran_salvage,
    )
    s.add(baris_est)
    s.flush()

    for r in hasil.harga_pasar.rujukan:
        s.add(
            HargaPasarRujukan(
                claim_id=klaim.id, judul=r.judul, url=r.url, cuplikan=r.cuplikan
            )
        )

    for b in hasil.baris_biaya:
        s.add(
            CostEstimateLine(
                cost_estimate_id=baris_est.id,
                part_class=b.part_class, sisi=b.sisi, nama_part=b.nama_part,
                nomor_part=b.nomor_part,
                damage_class=b.damage_class, kerusakan_lain=", ".join(b.kerusakan_lain),
                rasio_luas=b.rasio_luas, operasi=b.operasi,
                ganti_part=b.ganti_part, harga_part=b.harga_part,
                jam_standar=b.jam_standar, biaya_jasa=b.biaya_jasa, sumber=b.sumber,
            )
        )

    for permintaan in hasil.permintaan_foto:
        s.add(
            PhotoRequest(
                claim_id=klaim.id,
                permintaan=permintaan.permintaan,
                alasan=permintaan.alasan,
                sumber=permintaan.sumber,
            )
        )

    for p in hasil.penggunaan_token:
        s.add(
            LlmUsage(
                claim_id=klaim.id, langkah="pemrosesan", provider=p.provider,
                model=p.model, token_masuk=p.token_masuk, token_keluar=p.token_keluar,
            )
        )

    klaim.status = hasil.status
    klaim.verdict_validitas = hasil.verdict_validitas
    klaim.narasi = hasil.narasi
    if hasil.penilaian:
        klaim.agent_rekomendasi = hasil.penilaian.rekomendasi
        klaim.agent_alasan = hasil.penilaian.alasan
        klaim.agent_jumlah_pass = hasil.penilaian.jumlah_pass

    catat_audit(s, klaim.id, "cost_engine", "biaya_dihitung", {
        "total_biaya": str(est.total_biaya),
        "rasio": round(est.total_loss_ratio, 4),
        "rekomendasi": est.rekomendasi,
    })
    catat_audit(s, klaim.id, "validitas", "cek_dijalankan", {
        "verdict": hasil.verdict_validitas,
        "gagal": [c.kode for c in hasil.cek if not c.lolos],
    })


class HargaBelumDikonfirmasi(ValueError):
    """Klaim disetujui padahal harga pasarnya belum disahkan manusia."""


class KeputusanBelumAda(ValueError):
    """Pembatalan diminta untuk klaim yang belum pernah diputuskan."""


class ReviewBelumLengkap(ValueError):
    """Klaim diputuskan padahal hasil bacanya belum diperiksa adjuster."""


class ReviewBelumAda(ValueError):
    """Pembatalan diminta untuk penilaian yang belum pernah disimpan."""


class CatatanWajib(ValueError):
    """Klaim dikembalikan untuk revisi tanpa menyebut apa yang harus diperbaiki."""


class PengesahanBelumAda(ValueError):
    """Pembatalan pengesahan diminta untuk harga yang belum pernah disahkan."""


def review_belum_lengkap(s: Session, claim_id: str) -> str | None:
    """Alasan kenapa klaim ini belum boleh diputuskan, atau None kalau sudah boleh.

    Dua hal harus sudah dinilai adjuster: temuan deteksi dan hasil baca STNK. Keduanya
    adalah tempat model bisa keliru, dan keputusan yang diambil tanpa memeriksanya berarti
    menandatangani angka yang belum pernah dilihat orang.

    Klaim yang memang tidak punya temuan tidak ikut ditahan, karena tidak ada yang bisa
    dinilai di situ. Begitu juga STNK yang gagal dibaca seluruhnya.
    """
    temuan = set(
        s.scalars(
            select(DetectionResult.id)
            .join(ClaimPhoto, ClaimPhoto.id == DetectionResult.claim_photo_id)
            .where(ClaimPhoto.claim_id == claim_id)
        )
    )
    if temuan:
        dinilai = set(
            s.scalars(
                select(DetectionReview.detection_result_id).where(
                    DetectionReview.claim_id == claim_id
                )
            )
        )
        kurang = len(temuan - dinilai)
        if kurang:
            return (
                f"{kurang} temuan deteksi belum dinilai. Periksa tabel hasil deteksi lalu "
                "simpan penilaiannya sebelum memutuskan klaim ini."
            )

    stnk = s.scalar(select(StnkExtraction).where(StnkExtraction.claim_id == claim_id))
    terbaca = {f for f in FIELD_STNK if getattr(stnk, f, None)} if stnk else set()
    if terbaca:
        sudah = set(
            s.scalars(select(StnkReview.field).where(StnkReview.claim_id == claim_id))
        )
        if terbaca - sudah:
            return (
                "Hasil baca STNK belum dinilai. Periksa tiap field lalu simpan "
                "penilaiannya sebelum memutuskan klaim ini."
            )
    return None


def batalkan_review_temuan(s: Session, claim_id: str, oleh: str) -> int:
    """Hapus penilaian temuan supaya bisa diisi ulang.

    Dihapus, bukan ditandai batal, mengikuti cara pembatalan keputusan. Angka akurasi model
    dihitung dari baris yang ada, jadi baris yang ditarik tidak boleh ikut terhitung.
    """
    jumlah = (
        s.query(DetectionReview).filter(DetectionReview.claim_id == claim_id).delete()
    )
    if not jumlah:
        raise ReviewBelumAda("Klaim ini belum punya penilaian deteksi yang bisa dibatalkan")
    catat_audit(s, claim_id, "adjuster", "review_deteksi_dibatalkan",
                {"jumlah": jumlah, "oleh": oleh})
    return jumlah


def batalkan_review_stnk(s: Session, claim_id: str, oleh: str) -> int:
    """Hapus penilaian STNK supaya bisa diisi ulang."""
    jumlah = s.query(StnkReview).filter(StnkReview.claim_id == claim_id).delete()
    if not jumlah:
        raise ReviewBelumAda("Klaim ini belum punya penilaian STNK yang bisa dibatalkan")
    catat_audit(s, claim_id, "adjuster", "review_stnk_dibatalkan",
                {"jumlah": jumlah, "oleh": oleh})
    return jumlah


def butuh_konfirmasi_harga(est: CostEstimate | None) -> bool:
    """Apakah harga estimasi ini perlu disahkan adjuster sebelum klaim boleh disetujui.

    Berlaku untuk harga hasil pencarian internet dan harga yang belum diketahui. Keduanya
    menentukan rasio total loss dan besar penawaran beli kendaraan, dan tidak boleh melewati
    titik keputusan tanpa ada nama yang bertanggung jawab.
    """
    if est is None:
        return False
    return est.harga_pasar_sumber in (SUMBER_PENCARIAN, SUMBER_TIDAK_DIKETAHUI)


def batalkan_konfirmasi_harga(s: Session, klaim: Claim, oleh: str) -> None:
    """Tarik tanda tangan atas harga pasar, supaya harganya bisa diperiksa ulang.

    Yang ditarik cuma tanda tangannya. Angka hasil koreksi tetap dipakai, karena nilai
    sebelum dikoreksi tidak disimpan dan menebaknya kembali lebih berbahaya daripada
    membiarkan adjuster mengoreksinya sekali lagi.
    """
    est = s.scalar(select(CostEstimate).where(CostEstimate.claim_id == klaim.id))
    if est is None or not est.harga_dikonfirmasi_oleh:
        raise PengesahanBelumAda("Harga klaim ini belum disahkan, jadi tidak ada yang dibatalkan")

    lama = est.harga_dikonfirmasi_oleh
    est.harga_dikonfirmasi_oleh = None
    catat_audit(s, klaim.id, "adjuster", "pengesahan_harga_dibatalkan",
                {"harga": str(est.harga_pasar_bekas), "disahkan_sebelumnya_oleh": lama,
                 "oleh": oleh})


def koreksi_harga_pasar(
    s: Session, klaim: Claim, harga_baru: Decimal | None, oleh: str
) -> None:
    """Sahkan harga pasar, boleh sekalian menggantinya, lalu hitung ulang estimasinya.

    Perhitungan ulang memakai `susun_estimasi` yang sama persis dengan jalur pemrosesan,
    bukan rumus kedua yang ditulis di sini. Dua rumus untuk satu angka akan berbeda hasilnya
    cepat atau lambat, dan bedanya baru ketahuan saat ada yang protes.
    """
    est = s.scalar(select(CostEstimate).where(CostEstimate.claim_id == klaim.id))
    if est is None:
        return

    est.harga_dikonfirmasi_oleh = oleh
    if harga_baru is None:
        catat_audit(s, klaim.id, "adjuster", "harga_pasar_dikonfirmasi",
                    {"harga": str(est.harga_pasar_bekas), "sumber": est.harga_pasar_sumber,
                     "oleh": oleh})
        return

    baris = list(
        s.scalars(select(CostEstimateLine).where(CostEstimateLine.cost_estimate_id == est.id))
    )
    hitung = susun_estimasi(
        [
            BarisBiaya(
                part_class=b.part_class, nama_part=b.nama_part, nomor_part=b.nomor_part,
                sisi=b.sisi, damage_class=b.damage_class, rasio_luas=b.rasio_luas,
                operasi=b.operasi, ganti_part=b.ganti_part,
                harga_part=Decimal(b.harga_part), jam_standar=b.jam_standar,
                biaya_jasa=Decimal(b.biaya_jasa), sumber=b.sumber, alasan_aturan="",
            )
            for b in baris
        ],
        harga_pasar_bekas=harga_baru,
        ambang_total_loss=est.ambang_total_loss,
        own_risk=ambil_config_rupiah(s, "own_risk"),
        faktor_salvage=ambil_config_float(s, "faktor_salvage"),
    )

    lama = str(est.harga_pasar_bekas)
    est.harga_pasar_bekas = hitung.harga_pasar_bekas
    est.total_loss_ratio = hitung.total_loss_ratio
    est.rekomendasi = hitung.rekomendasi
    est.own_risk = hitung.own_risk
    est.ditanggung_penanggung = hitung.ditanggung_penanggung
    est.harga_tawaran_salvage = hitung.harga_tawaran_salvage
    est.harga_pasar_sumber = SUMBER_ADJUSTER
    est.harga_pasar_keterangan = f"Dikoreksi adjuster dari {lama}"

    catat_audit(s, klaim.id, "adjuster", "harga_pasar_dikoreksi",
                {"lama": lama, "baru": str(hitung.harga_pasar_bekas),
                 "rekomendasi_baru": hitung.rekomendasi, "oleh": oleh})


def catat_keputusan(
    s: Session, klaim: Claim, keputusan: str, catatan: str, oleh: str
) -> dict:
    """Catat keputusan adjuster, lalu terbitkan surat yang sesuai.

    Surat perintah kerja dan penawaran beli baru terbit di sini, bukan saat pemrosesan.
    Sistem merekomendasikan, manusia yang memutuskan, dan surat resmi hanya keluar setelah
    ada nama yang bertanggung jawab atas keputusannya.
    """
    # Penjagaan ini di server, bukan cuma tombol yang dimatikan di layar, dan berlaku untuk
    # semua keputusan termasuk menolak. Menolak klaim orang juga keputusan yang harus
    # berdiri di atas hasil baca yang sudah diperiksa.
    kurang = review_belum_lengkap(s, klaim.id)
    if kurang:
        raise ReviewBelumLengkap(kurang)

    # Cuma revisi yang mewajibkan catatan. Setuju dan tolak menutup klaim, sedangkan revisi
    # mengembalikannya ke surveyor, dan surveyor tidak bisa menebak apa yang harus diperbaiki.
    if keputusan == "revisi" and not catatan.strip():
        raise CatatanWajib(
            "Tulis apa yang harus diperbaiki surveyor. Catatan ini yang dia baca saat "
            "mengirim ulang klaimnya."
        )

    s.add(
        AdjusterDecision(claim_id=klaim.id, keputusan=keputusan, catatan=catatan, oleh=oleh)
    )
    catat_audit(s, klaim.id, "adjuster", "keputusan_dicatat",
                {"keputusan": keputusan, "oleh": oleh})

    if keputusan == "revisi":
        # Catatannya jadi permintaan foto biasa, supaya revisi memakai jalur yang sudah ada
        # di layar surveyor dan bukan jalur kedua yang harus dirawat terpisah.
        s.add(
            PhotoRequest(
                claim_id=klaim.id, permintaan=catatan, sumber=SUMBER_ADJUSTER,
            )
        )
        klaim.status = STATUS_MENUNGGU_FOTO
        return {"status": klaim.status, "surat": None}

    if keputusan != "setuju":
        klaim.status = "ditolak"
        return {"status": klaim.status, "surat": None}

    est = s.scalar(select(CostEstimate).where(CostEstimate.claim_id == klaim.id))
    if est is None:
        klaim.status = "disetujui"
        return {"status": klaim.status, "surat": None}

    # Penjagaan ini di server, bukan cuma tombol yang dimatikan di layar. Tombol yang
    # dimatikan bisa dilewati dengan memanggil alamatnya langsung.
    if butuh_konfirmasi_harga(est) and not est.harga_dikonfirmasi_oleh:
        raise HargaBelumDikonfirmasi(
            "Harga pasar bekas klaim ini belum disahkan. Periksa sumbernya, lalu "
            "konfirmasi atau koreksi harganya sebelum menyetujui."
        )

    klaim.status = "disetujui"

    if est.rekomendasi == "total_loss":
        faktor = ambil_config_float(s, "faktor_salvage")
        # Harga yang terbit wajib sama persis dengan yang dilihat adjuster sebelum menekan
        # tombol. Menghitung ulang di sini membuka celah angka berubah kalau faktor salvage
        # sempat diubah di antara pemrosesan dan keputusan.
        harga = (
            Decimal(est.harga_tawaran_salvage)
            if est.harga_tawaran_salvage is not None
            else (Decimal(est.harga_pasar_bekas) * Decimal(str(faktor))).quantize(Decimal(1))
        )
        tawaran = SalvageOffer(
            claim_id=klaim.id,
            harga_pasar_bekas=est.harga_pasar_bekas,
            faktor_salvage=faktor,
            harga_tawaran=harga,
        )
        s.add(tawaran)
        catat_audit(s, klaim.id, "adjuster", "penawaran_beli_terbit",
                    {"harga_tawaran": str(tawaran.harga_tawaran)})
        return {"status": klaim.status, "surat": "penawaran_beli",
                "harga_tawaran": str(tawaran.harga_tawaran)}

    spk = Spk(
        claim_id=klaim.id,
        nomor_spk=klaim.nomor_klaim.replace("KLM", "SPK"),
        bengkel=BENGKEL_REKANAN,
        nilai_disetujui=est.ditanggung_penanggung,
    )
    s.add(spk)
    catat_audit(s, klaim.id, "adjuster", "spk_terbit",
                {"nomor_spk": spk.nomor_spk, "nilai": str(spk.nilai_disetujui)})
    return {"status": klaim.status, "surat": "spk", "nomor_spk": spk.nomor_spk}


def batalkan_keputusan(s: Session, klaim: Claim, oleh: str) -> dict:
    """Tarik kembali keputusan adjuster, beserta surat yang sudah terbit karenanya.

    Barisnya benar-benar dihapus, bukan ditandai batal, karena SPK dan penawaran beli
    dikunci satu per klaim sehingga keputusan berikutnya tidak akan bisa menerbitkan
    suratnya. Jejaknya tetap ada di audit log yang tidak pernah dihapus.
    """
    keputusan = list(
        s.scalars(select(AdjusterDecision).where(AdjusterDecision.claim_id == klaim.id))
    )
    if not keputusan:
        raise KeputusanBelumAda("Klaim ini belum punya keputusan yang bisa dibatalkan")

    spk = s.scalar(select(Spk).where(Spk.claim_id == klaim.id))
    tawaran = s.scalar(select(SalvageOffer).where(SalvageOffer.claim_id == klaim.id))

    for k in keputusan:
        s.delete(k)
    if spk is not None:
        s.delete(spk)
    if tawaran is not None:
        s.delete(tawaran)

    # Klaim kembali ke antrean adjuster, kecuali masih ada foto tambahan yang diminta dan
    # belum dikirim surveyor.
    tertunda = s.scalar(
        select(func.count())
        .select_from(PhotoRequest)
        .where(PhotoRequest.claim_id == klaim.id, PhotoRequest.dipenuhi.is_(False))
    )
    status_lama = klaim.status
    klaim.status = STATUS_MENUNGGU_FOTO if tertunda else STATUS_SIAP_REVIEW

    catat_audit(s, klaim.id, "adjuster", "keputusan_dibatalkan",
                {"keputusan": keputusan[-1].keputusan, "status_lama": status_lama,
                 "nomor_spk": spk.nomor_spk if spk else None,
                 "penawaran_beli_ditarik": tawaran is not None, "oleh": oleh})
    return {"status": klaim.status, "surat_ditarik": bool(spk or tawaran)}


def ringkasan_semua_klaim(s: Session) -> dict:
    """Angka gabungan seluruh klaim untuk halaman ringkasan.

    Dihitung dengan agregat SQL, bukan dengan menarik semua klaim ke memori, supaya tetap
    ringan saat jumlah klaimnya bertambah.
    """

    def hitung_per(kolom) -> dict[str, int]:
        return {
            (nilai or "tidak diketahui"): jumlah
            for nilai, jumlah in s.execute(
                select(kolom, func.count()).group_by(kolom)
            )
        }

    total = s.scalar(select(func.count()).select_from(Claim)) or 0

    angka = s.execute(
        select(
            func.coalesce(func.sum(CostEstimate.total_biaya), 0),
            func.coalesce(func.avg(CostEstimate.total_loss_ratio), 0.0),
            func.count(),
        )
    ).one()

    # Pemeriksaan yang gagal dihitung per kode, karena inilah yang menunjukkan jenis
    # masalah apa yang paling sering muncul, bukan sekadar berapa klaim yang bermasalah.
    gagal_cek = {
        kode: jumlah
        for kode, jumlah in s.execute(
            select(ValidityCheck.kode, func.count())
            .where(ValidityCheck.lolos.is_(False))
            .group_by(ValidityCheck.kode)
            .order_by(ValidityCheck.kode)
        )
    }

    token = s.execute(
        select(
            func.coalesce(func.sum(LlmUsage.token_masuk), 0),
            func.coalesce(func.sum(LlmUsage.token_keluar), 0),
        )
    ).one()

    # Akurasi diukur dari temuan yang sudah dinilai adjuster saja. Temuan yang belum
    # dinilai tidak boleh dianggap benar, karena itu akan menaikkan angkanya sendiri.
    dinilai = s.scalar(select(func.count()).select_from(DetectionReview)) or 0
    benar = (
        s.scalar(
            select(func.count()).select_from(DetectionReview).where(DetectionReview.benar)
        )
        or 0
    )
    total_temuan = s.scalar(select(func.count()).select_from(DetectionResult)) or 0
    alasan_salah = {
        alasan: jumlah
        for alasan, jumlah in s.execute(
            select(DetectionReview.alasan, func.count())
            .where(DetectionReview.benar.is_(False))
            .group_by(DetectionReview.alasan)
        )
        if alasan
    }

    # Ketepatan baca STNK dihitung terpisah dari ketepatan deteksi kerusakan. Keduanya
    # kemampuan yang berbeda: satu membaca tulisan, satu mengenali bentuk. Menggabungnya
    # jadi satu angka menyembunyikan mana yang sebenarnya bermasalah.
    stnk_dinilai = s.scalar(select(func.count()).select_from(StnkReview)) or 0
    stnk_benar = (
        s.scalar(select(func.count()).select_from(StnkReview).where(StnkReview.benar)) or 0
    )
    stnk_salah_per_field = {
        field: jumlah
        for field, jumlah in s.execute(
            select(StnkReview.field, func.count())
            .where(StnkReview.benar.is_(False))
            .group_by(StnkReview.field)
        )
    }

    nama_pengguna = peta_nama_pengguna(s)
    return {
        "deteksi": {
            "total_temuan": total_temuan,
            "dinilai": dinilai,
            "benar": benar,
            "akurasi": (benar / dinilai) if dinilai else None,
            "alasan_salah": alasan_salah,
        },
        "stnk": {
            "dinilai": stnk_dinilai,
            "benar": stnk_benar,
            "akurasi": (stnk_benar / stnk_dinilai) if stnk_dinilai else None,
            "salah_per_field": stnk_salah_per_field,
        },
        "total_klaim": total,
        "per_status": hitung_per(Claim.status),
        "per_verdict": hitung_per(Claim.verdict_validitas),
        "per_rekomendasi": hitung_per(CostEstimate.rekomendasi),
        "total_nilai_klaim": str(angka[0]),
        "rata_rasio": float(angka[1] or 0.0),
        "klaim_dinilai": int(angka[2]),
        "gagal_cek": gagal_cek,
        "token": {"masuk": int(token[0]), "keluar": int(token[1])},
        "terbaru": [
            ringkasan_klaim(s, k, nama_pengguna)
            for k in s.scalars(select(Claim).order_by(Claim.created_at.desc()).limit(5))
        ],
    }


def peta_nama_pengguna(s: Session) -> dict[str, str]:
    """Username ke nama tampilan, untuk daftar yang menyebut pengirimnya.

    Ditarik sekali lalu dipakai ulang, supaya daftar panjang tidak berubah jadi satu
    query per baris.
    """
    return dict(s.execute(select(AppUser.username, AppUser.nama)).all())


def ringkasan_klaim(
    s: Session, klaim: Claim, nama_pengguna: dict[str, str] | None = None
) -> dict:
    """Bentuk ringkas untuk daftar klaim di layar adjuster."""
    if nama_pengguna is None:
        nama_pengguna = peta_nama_pengguna(s)
    est = s.scalar(select(CostEstimate).where(CostEstimate.claim_id == klaim.id))
    polis = s.get(Policy, klaim.policy_id)
    kendaraan = s.get(VehicleModel, klaim.vehicle_model_id) if klaim.vehicle_model_id else None
    return {
        "id": klaim.id,
        "nomor_klaim": klaim.nomor_klaim,
        "nomor_polis": polis.nomor_polis if polis else None,
        "pemegang_polis": polis.nama_pemegang if polis else None,
        "kendaraan": kendaraan.nama_tampil if kendaraan else None,
        "tahun_kendaraan": kendaraan.tahun if kendaraan else None,
        "status": klaim.status,
        "surveyor": klaim.surveyor,
        "nama_surveyor": nama_pengguna.get(klaim.surveyor or "") or None,
        "verdict_validitas": klaim.verdict_validitas,
        "rekomendasi": est.rekomendasi if est else None,
        "total_biaya": str(est.total_biaya) if est else None,
        "harga_pasar_bekas": str(est.harga_pasar_bekas) if est else None,
        "total_loss_ratio": est.total_loss_ratio if est else None,
        "dibuat": waktu_iso(klaim.created_at),
        "contoh_demo": klaim.contoh_demo,
    }


def _usulan_kerusakan_lama(
    t: DetectionResult, riwayat: list[TemuanRiwayat], selisih_maks: float
) -> dict | None:
    """Usulkan penilaian "kerusakan lama" kalau temuan ini pernah muncul di klaim lain.

    Cuma usulan yang mengisi pilihan awal di layar. Yang tersimpan tetap penilaian adjuster,
    dan dia bebas mengubahnya.
    """
    cocok = cari_kerusakan_lama(
        TemuanKlaim(t.part_class, t.sisi, t.damage_class, t.rasio_luas),
        riwayat,
        selisih_maks,
    )
    if cocok is None:
        return None
    return {
        "alasan": "kerusakan_lama",
        "klaim_lama": cocok.nomor_klaim,
        "status_klaim_lama": cocok.status,
        "rasio_dulu": round(cocok.rasio_luas, 4),
    }


def daftar_foto(s: Session, claim_id: str) -> list[dict]:
    """Foto kerusakan beserta temuan yang menempel di masing-masing.

    Yang dikirim cuma keterangannya, bukan gambarnya. Gambar diambil terpisah lewat
    alamatnya sendiri supaya jawaban rincian klaim tidak membengkak.
    """
    foto = list(
        s.scalars(
            select(ClaimPhoto)
            .where(ClaimPhoto.claim_id == claim_id, ClaimPhoto.jenis == "kerusakan")
            .order_by(ClaimPhoto.urutan)
        )
    )
    # Overlay ditulis ulang seluruhnya tiap kali klaim diproses, satu untuk tiap foto
    # kerusakan menurut urutannya, jadi pasangannya dicocokkan lewat posisi.
    overlay = list(
        s.scalars(
            select(ClaimPhoto)
            .where(ClaimPhoto.claim_id == claim_id, ClaimPhoto.jenis == "overlay")
            .order_by(ClaimPhoto.urutan)
        )
    )

    nilai = {
        r.detection_result_id: r
        for r in s.scalars(select(DetectionReview).where(DetectionReview.claim_id == claim_id))
    }

    # Usulan penilaian dihitung di sini, bukan disimpan sebagai kolom, supaya klaim lama
    # ikut mendapat usulan begitu riwayat polisnya bertambah.
    klaim = s.get(Claim, claim_id)
    riwayat = (
        riwayat_temuan_polis(s, klaim) if klaim else []
    )
    selisih_maks = ambil_config_float(s, "ambang_selisih_rasio_sama")

    hasil = []
    for i, f in enumerate(foto):
        pasangan = overlay[i] if i < len(overlay) else None
        temuan = s.scalars(
            select(DetectionResult).where(DetectionResult.claim_photo_id == f.id)
        )
        hasil.append(
            {
                "urutan": f.urutan,
                "ada_overlay": pasangan is not None,
                "urutan_overlay": pasangan.urutan if pasangan else None,
                # Kosong untuk klaim lama yang diproses sebelum bentuknya ikut disimpan.
                # Layar pratinjau jatuh ke gambar overlay biasa kalau kosong.
                "bentuk": (pasangan.bentuk or {}) if pasangan else {},
                "temuan": [
                    {
                        "id": t.id,
                        "part_class": t.part_class,
                        "sisi": t.sisi,
                        "damage_class": t.damage_class,
                        "rasio_luas": t.rasio_luas,
                        "sebaran": sebaran(t.rasio_luas),
                        "confidence_part": t.confidence_part,
                        "confidence_damage": t.confidence_damage,
                        "part_urutan": t.part_urutan,
                        "damage_urutan": t.damage_urutan,
                        "review": _bentuk_review(nilai.get(t.id)),
                        "usulan": _usulan_kerusakan_lama(t, riwayat, selisih_maks),
                    }
                    for t in temuan
                ],
            }
        )
    return hasil


def urutan_foto_stnk(s: Session, claim_id: str) -> int | None:
    """Urutan berkas foto STNK, dipakai layar menyusun alamat gambarnya.

    Bukan selalu nol: urutannya melanjutkan nomor foto kerusakan, jadi layar tidak bisa
    menebaknya sendiri.
    """
    return s.scalar(
        select(ClaimPhoto.urutan)
        .where(ClaimPhoto.claim_id == claim_id, ClaimPhoto.jenis == "stnk")
        .order_by(ClaimPhoto.urutan)
    )


def daftar_pelengkap(s: Session, claim_id: str) -> list[int]:
    """Urutan tiap foto pelengkap, dipakai frontend menyusun alamat gambarnya.

    Tidak ada temuan yang menempel, karena foto pelengkap memang tidak pernah dideteksi.
    """
    return _urutan_jenis(s, claim_id, "pelengkap")


def _urutan_jenis(s: Session, claim_id: str, jenis: str) -> list[int]:
    return [
        f.urutan
        for f in s.scalars(
            select(ClaimPhoto)
            .where(ClaimPhoto.claim_id == claim_id, ClaimPhoto.jenis == jenis)
            .order_by(ClaimPhoto.urutan)
        )
    ]


def _bentuk_review(r: DetectionReview | None) -> dict | None:
    if r is None:
        return None
    return {"benar": r.benar, "alasan": r.alasan, "oleh": r.oleh}


# Alasan dibatasi pilihan tetap, bukan teks bebas, supaya bisa dihitung dan dijadikan
# label saat model dilatih ulang. Teks bebas hanya menghasilkan angka yang tidak terbaca.
ALASAN_SALAH = {
    "bagian_salah",
    "jenis_kerusakan_salah",
    "kerusakan_tidak_ada",
    "luas_terlalu_besar",
    "luas_terlalu_kecil",
    "kerusakan_lama",
}


def catat_review_temuan(
    s: Session, claim_id: str, penilaian: list[dict], oleh: str
) -> int:
    """Simpan penilaian adjuster atas temuan deteksi, satu baris per temuan.

    Menilai ulang temuan yang sama menimpa penilaian sebelumnya, bukan menumpuk baris,
    supaya angka akurasi tidak terhitung ganda.
    """
    milik_klaim = {
        t.id
        for t in s.scalars(
            select(DetectionResult)
            .join(ClaimPhoto, ClaimPhoto.id == DetectionResult.claim_photo_id)
            .where(ClaimPhoto.claim_id == claim_id)
        )
    }

    jumlah = 0
    for p in penilaian:
        temuan_id = p.get("temuan_id")
        if temuan_id not in milik_klaim:
            raise ValueError(f"temuan {temuan_id} bukan milik klaim ini")

        benar = bool(p.get("benar"))
        alasan = None if benar else p.get("alasan")
        if not benar and alasan not in ALASAN_SALAH:
            raise ValueError(f"alasan tidak dikenal: {alasan}")

        lama = s.scalar(
            select(DetectionReview).where(DetectionReview.detection_result_id == temuan_id)
        )
        if lama:
            lama.benar, lama.alasan, lama.oleh = benar, alasan, oleh
        else:
            s.add(
                DetectionReview(
                    detection_result_id=temuan_id,
                    claim_id=claim_id,
                    benar=benar,
                    alasan=alasan,
                    oleh=oleh,
                )
            )
        jumlah += 1

    catat_audit(s, claim_id, "review_deteksi", "adjuster menilai temuan",
                {"jumlah": jumlah, "oleh": oleh})
    s.commit()
    return jumlah


# Field STNK yang boleh dinilai, sekaligus urutan tampilnya di layar. Nomor mesin tidak
# ikut karena tidak dipakai satu pun cek validitas dan tidak pernah ditampilkan.
FIELD_STNK = ("merk", "tipe", "tahun", "nomor_polisi", "nomor_rangka", "nama_pemilik")


def catat_review_stnk(
    s: Session, claim_id: str, penilaian: list[dict], oleh: str
) -> int:
    """Simpan penilaian adjuster atas hasil baca STNK, satu baris per field.

    Menilai ulang field yang sama menimpa penilaian sebelumnya, bukan menumpuk baris,
    supaya angka ketelitian tidak terhitung ganda. Nilai koreksinya tidak dipakai
    menghitung ulang cek validitas: verdict yang sudah dilihat orang tidak boleh berubah
    karena isian yang datang belakangan.
    """
    jumlah = 0
    for p in penilaian:
        field = p.get("field")
        if field not in FIELD_STNK:
            raise ValueError(f"field tidak dikenal: {field}")

        benar = bool(p.get("benar"))
        nilai = (p.get("nilai_benar") or "").strip() or None
        if not benar and not nilai:
            raise ValueError(f"field {field} ditandai salah tapi nilai benarnya kosong")
        if benar:
            nilai = None

        lama = s.scalar(
            select(StnkReview).where(
                StnkReview.claim_id == claim_id, StnkReview.field == field
            )
        )
        if lama:
            lama.benar, lama.nilai_benar, lama.oleh = benar, nilai, oleh
        else:
            s.add(
                StnkReview(
                    claim_id=claim_id, field=field, benar=benar,
                    nilai_benar=nilai, oleh=oleh,
                )
            )
        jumlah += 1

    salah = [p.get("field") for p in penilaian if not p.get("benar")]
    catat_audit(s, claim_id, "review_stnk", "adjuster memeriksa hasil baca stnk",
                {"jumlah": jumlah, "salah": salah, "oleh": oleh})
    s.commit()
    return jumlah


def review_stnk(s: Session, claim_id: str) -> list[dict]:
    """Penilaian yang sudah tersimpan, dipakai layar untuk mengisi ulang pilihannya."""
    return [
        {"field": r.field, "benar": r.benar, "nilai_benar": r.nilai_benar,
         "oleh": r.oleh, "waktu": waktu_iso(r.created_at)}
        for r in s.scalars(select(StnkReview).where(StnkReview.claim_id == claim_id))
    ]


def permintaan_foto(s: Session, claim_id: str) -> list[dict]:
    """Foto yang diminta beserta alasannya, dipakai layar surveyor dan adjuster."""
    return [
        {"permintaan": p.permintaan, "alasan": p.alasan, "sumber": p.sumber,
         "dipenuhi": p.dipenuhi}
        for p in s.scalars(select(PhotoRequest).where(PhotoRequest.claim_id == claim_id))
    ]


def ringkasan_kiriman(s: Session, klaim: Claim, nama_pengguna: dict[str, str]) -> dict:
    """Bentuk untuk layar Klaim Saya milik surveyor.

    Sengaja tidak memakai `ringkasan_klaim`, yang membawa biaya, verdict, dan rekomendasi.
    Ketiganya bahan keputusan adjuster, dan surveyor tidak boleh melihatnya. Menyaringnya
    di frontend tidak cukup: datanya tetap terkirim dan tinggal dibuka di tab jaringan.
    """
    polis = s.get(Policy, klaim.policy_id)
    kendaraan = s.get(VehicleModel, klaim.vehicle_model_id) if klaim.vehicle_model_id else None
    return {
        "id": klaim.id,
        "nomor_klaim": klaim.nomor_klaim,
        "nomor_polis": polis.nomor_polis if polis else None,
        "kendaraan": kendaraan.nama_tampil if kendaraan else None,
        "status": klaim.status,
        "surveyor": klaim.surveyor,
        "nama_surveyor": nama_pengguna.get(klaim.surveyor or "") or None,
        "dibuat": waktu_iso(klaim.created_at),
        "permintaan_foto": permintaan_foto(s, klaim.id),
    }


def kiriman_saya(s: Session, username: str, semua: bool = False) -> list[dict]:
    """Klaim untuk layar Klaim Saya, terbaru dulu.

    `semua` dinyalakan untuk pemanggil yang memang berhak melihat seluruh klaim, sehingga
    admin bisa memantau kiriman siapa pun dari satu layar. Bentuk jawabannya tetap tipis:
    biaya dan penilaian dibuka lewat halaman Daftar Klaim, bukan di sini.
    """
    q = select(Claim).order_by(Claim.created_at.desc())
    if not semua:
        q = q.where(Claim.surveyor == username)
    nama = peta_nama_pengguna(s)
    return [ringkasan_kiriman(s, k, nama) for k in s.scalars(q)]


def surat_klaim(s: Session, klaim: Claim) -> dict | None:
    """Surat yang sudah terbit untuk klaim ini, kalau ada.

    Dibaca dari tabel suratnya sendiri, bukan dari status klaim, supaya keterangan di layar
    dan dokumen yang bisa dicetak selalu bersumber dari baris yang sama.
    """
    spk = s.scalar(select(Spk).where(Spk.claim_id == klaim.id))
    if spk is not None:
        return {
            "jenis": "spk",
            "nomor": spk.nomor_spk,
            "tujuan": spk.bengkel,
            "nilai": str(spk.nilai_disetujui),
            "waktu": waktu_iso(spk.created_at),
        }

    tawaran = s.scalar(select(SalvageOffer).where(SalvageOffer.claim_id == klaim.id))
    if tawaran is None:
        return None

    polis = s.get(Policy, klaim.policy_id)
    return {
        "jenis": "penawaran_beli",
        "nomor": None,
        "tujuan": polis.nama_pemegang if polis else "",
        "nilai": str(tawaran.harga_tawaran),
        "harga_pasar_bekas": str(tawaran.harga_pasar_bekas),
        "faktor_salvage": tawaran.faktor_salvage,
        "waktu": waktu_iso(tawaran.created_at),
    }


def detail_klaim(s: Session, klaim: Claim) -> dict:
    """Bentuk lengkap untuk layar rincian, termasuk jejak tiap pemeriksaan."""
    dasar = ringkasan_klaim(s, klaim)
    est = s.scalar(select(CostEstimate).where(CostEstimate.claim_id == klaim.id))
    stnk = s.scalar(select(StnkExtraction).where(StnkExtraction.claim_id == klaim.id))

    baris = []
    if est:
        baris = [
            {
                "part_class": b.part_class, "sisi": b.sisi, "nama_part": b.nama_part,
                "nomor_part": b.nomor_part,
                "damage_class": b.damage_class, "kerusakan_lain": b.kerusakan_lain,
                "rasio_luas": b.rasio_luas,
                "operasi": b.operasi, "ganti_part": b.ganti_part,
                "harga_part": str(b.harga_part), "jam_standar": b.jam_standar,
                "biaya_jasa": str(b.biaya_jasa), "sumber": b.sumber,
            }
            for b in s.scalars(
                select(CostEstimateLine)
                .where(CostEstimateLine.cost_estimate_id == est.id)
                .order_by(CostEstimateLine.part_class)
            )
        ]

    token = s.execute(
        select(
            func.coalesce(func.sum(LlmUsage.token_masuk), 0),
            func.coalesce(func.sum(LlmUsage.token_keluar), 0),
        ).where(LlmUsage.claim_id == klaim.id)
    ).one()

    return {
        **dasar,
        "foto": daftar_foto(s, klaim.id),
        "pelengkap": daftar_pelengkap(s, klaim.id),
        # Alasan kenapa klaim ini belum boleh diputuskan, kosong kalau sudah boleh. Layar
        # memakainya mematikan tombol keputusan beserta menampilkan sebabnya.
        "review_kurang": review_belum_lengkap(s, klaim.id),
        "narasi": klaim.narasi,
        "penilaian_agent": None if not klaim.agent_rekomendasi else {
            "rekomendasi": klaim.agent_rekomendasi,
            "alasan": klaim.agent_alasan,
            "jumlah_pass": klaim.agent_jumlah_pass,
        },
        "stnk": None if stnk is None else {
            "merk": stnk.merk, "tipe": stnk.tipe, "tahun": stnk.tahun,
            "nomor_polisi": stnk.nomor_polisi, "nomor_rangka": stnk.nomor_rangka,
            "nama_pemilik": stnk.nama_pemilik, "pakai_llm": stnk.pakai_llm,
            "urutan_foto": urutan_foto_stnk(s, klaim.id),
        },
        "cek": [
            {"kode": c.kode, "nama": c.nama, "lolos": c.lolos,
             "tingkat": c.tingkat, "alasan": c.alasan}
            for c in s.scalars(
                select(ValidityCheck)
                .where(ValidityCheck.claim_id == klaim.id)
                .order_by(ValidityCheck.kode)
            )
        ],
        "biaya": None if est is None else {
            "total_part": str(est.total_part),
            "total_jasa": str(est.total_jasa),
            "total_biaya": str(est.total_biaya),
            "harga_pasar_bekas": str(est.harga_pasar_bekas),
            "total_loss_ratio": est.total_loss_ratio,
            "ambang_total_loss": est.ambang_total_loss,
            "own_risk": str(est.own_risk),
            "ditanggung_penanggung": str(est.ditanggung_penanggung),
            "harga_tawaran_salvage": (
                None if est.harga_tawaran_salvage is None else str(est.harga_tawaran_salvage)
            ),
            "rekomendasi": est.rekomendasi,
            "harga_pasar_sumber": est.harga_pasar_sumber,
            "harga_pasar_keterangan": est.harga_pasar_keterangan,
            "harga_dikonfirmasi_oleh": est.harga_dikonfirmasi_oleh,
            "harga_rujukan": [
                {"judul": r.judul, "url": r.url, "cuplikan": r.cuplikan}
                for r in s.scalars(
                    select(HargaPasarRujukan).where(HargaPasarRujukan.claim_id == klaim.id)
                )
            ],
        },
        "baris_biaya": baris,
        "review_stnk": review_stnk(s, klaim.id),
        "permintaan_foto": permintaan_foto(s, klaim.id),
        "keputusan": [
            {"keputusan": d.keputusan, "catatan": d.catatan, "oleh": d.oleh,
             "waktu": waktu_iso(d.created_at)}
            for d in s.scalars(
                select(AdjusterDecision).where(AdjusterDecision.claim_id == klaim.id)
            )
        ],
        "surat": surat_klaim(s, klaim),
        "token": {"masuk": int(token[0]), "keluar": int(token[1])},
    }
