"""Skema database, ditulis sekali dan dipakai sama persis di Supabase maupun Postgres internal.

Semua ambang keputusan (batas total loss, own risk, faktor salvage, ambang confidence)
disimpan sebagai baris tabel `Config`, bukan konstanta di kode, supaya bisa diubah tanpa
deploy ulang dan perubahannya terlihat di audit log.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


# Rupiah disimpan sebagai Numeric, bukan Float, supaya penjumlahan harga tidak kena
# pembulatan biner. Selisih satu rupiah di total klaim sulit dijelaskan ke adjuster.
Rupiah = Numeric(14, 2)


class Config(Base):
    """Ambang dan konstanta bisnis. Satu baris per pengaturan."""

    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)
    keterangan: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class VehicleModel(Base):
    """Master kendaraan. `harga_pasar_bekas` jadi pembagi di perhitungan total loss."""

    __tablename__ = "vehicle_model"
    __table_args__ = (UniqueConstraint("merk", "tipe", "tahun", name="uq_vehicle_model"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    merk: Mapped[str] = mapped_column(String)
    tipe: Mapped[str] = mapped_column(String)
    tahun: Mapped[int] = mapped_column(Integer)
    nama_tampil: Mapped[str] = mapped_column(String)
    # Boleh kosong. Kendaraan yang harganya belum kita punya memicu agent mencari sendiri
    # ke internet, bukan membuat klaimnya gagal.
    harga_pasar_bekas: Mapped[float | None] = mapped_column(Rupiah, nullable=True)

    parts: Mapped[list["PartCatalog"]] = relationship(back_populates="vehicle_model")


class PartCatalog(Base):
    """Harga sparepart per model kendaraan.

    `part_class` memakai nama kelas dari model deteksi (misal `Front-bumper`), supaya
    hasil deteksi bisa langsung jadi kunci pencarian tanpa tabel penerjemah di tengah.
    `terlihat_dari_luar` menandai part yang tidak mungkin dideteksi dari foto (radiator,
    airbag) sehingga harus dimasukkan lewat aturan, bukan lewat deteksi.
    """

    __tablename__ = "part_catalog"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    vehicle_model_id: Mapped[str] = mapped_column(ForeignKey("vehicle_model.id"))
    part_class: Mapped[str] = mapped_column(String, index=True)
    nama_part: Mapped[str] = mapped_column(String)
    nomor_part: Mapped[str] = mapped_column(String)
    asal: Mapped[str] = mapped_column(String, default="OEM")
    harga: Mapped[float] = mapped_column(Rupiah)
    terlihat_dari_luar: Mapped[bool] = mapped_column(Boolean, default=True)

    vehicle_model: Mapped["VehicleModel"] = relationship(back_populates="parts")


class LaborRate(Base):
    """Jam standar dan tarif per operasi bengkel.

    Jam standar bergantung pada bagiannya, bukan cuma pada operasinya. Mengganti headlamp
    dan mengganti panel bodi depan sama-sama operasi ganti part, tapi lamanya jauh berbeda.
    Karena itu `part_class` boleh diisi untuk aturan khusus, dan baris dengan `part_class`
    kosong jadi nilai bawaan kalau tidak ada aturan khususnya.
    """

    __tablename__ = "labor_rate"
    __table_args__ = (UniqueConstraint("operasi", "part_class", name="uq_labor_rate"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    operasi: Mapped[str] = mapped_column(String, index=True)
    part_class: Mapped[str | None] = mapped_column(String, nullable=True)
    jam_standar: Mapped[float] = mapped_column(Float)
    tarif_per_jam: Mapped[float] = mapped_column(Rupiah)


class RepairMatrix(Base):
    """Aturan yang mengubah jenis kerusakan + rasio luas jadi satu operasi bengkel.

    Rentang rasio ditulis sebagai [rasio_min, rasio_max), jadi batas atas tidak ikut.
    Untuk kerusakan yang operasinya tidak bergantung luas (`Broken part`, `Missing part`),
    rentangnya diisi 0 sampai 1 sehingga selalu cocok.
    """

    __tablename__ = "repair_matrix"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    damage_class: Mapped[str] = mapped_column(String, index=True)
    rasio_min: Mapped[float] = mapped_column(Float, default=0.0)
    rasio_max: Mapped[float] = mapped_column(Float, default=1.0)
    operasi: Mapped[str] = mapped_column(String)
    ganti_part: Mapped[bool] = mapped_column(Boolean, default=False)
    keterangan: Mapped[str] = mapped_column(Text, default="")


class Policy(Base):
    """Polis asuransi. Jadi pembanding untuk cek kecocokan STNK."""

    __tablename__ = "policy"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    nomor_polis: Mapped[str] = mapped_column(String, unique=True, index=True)
    nomor_polisi: Mapped[str] = mapped_column(String, index=True)
    nomor_rangka: Mapped[str] = mapped_column(String, index=True)
    nomor_mesin: Mapped[str] = mapped_column(String)
    nama_pemegang: Mapped[str] = mapped_column(String)
    alamat: Mapped[str] = mapped_column(Text, default="")
    vehicle_model_id: Mapped[str] = mapped_column(ForeignKey("vehicle_model.id"))
    jenis_pertanggungan: Mapped[str] = mapped_column(String, default="comprehensive")
    berlaku_sampai: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Role(Base):
    """Satu peran yang bisa diberikan ke pengguna.

    Disimpan sebagai baris, bukan konstanta di kode, supaya peran baru bisa dibuat lewat
    layar Manajemen Akses tanpa deploy ulang. Peran bawaan tidak bisa dihapus karena data
    awal dan uji bergantung padanya.
    """

    __tablename__ = "role"

    kode: Mapped[str] = mapped_column(String, primary_key=True)
    nama: Mapped[str] = mapped_column(String)
    keterangan: Mapped[str] = mapped_column(Text, default="")
    bawaan: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RolePermission(Base):
    """Hak akses yang dimiliki satu peran, satu baris per hak.

    Daftar hak yang tersedia ditulis di kode, karena tiap hak menutup alamat API yang
    memang ada. Yang disimpan di sini cuma pemberiannya ke peran mana.
    """

    __tablename__ = "role_permission"
    __table_args__ = (UniqueConstraint("role_kode", "izin"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    role_kode: Mapped[str] = mapped_column(ForeignKey("role.kode"), index=True)
    izin: Mapped[str] = mapped_column(String, index=True)


class AppUser(Base):
    """Akun yang bisa masuk ke sistem.

    Kata sandi disimpan sebagai turunan PBKDF2 dengan garam berbeda tiap pengguna, jadi
    isi tabel ini tidak bisa dipakai untuk masuk kalau bocor.
    """

    __tablename__ = "app_user"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    nama: Mapped[str] = mapped_column(String, default="")
    sandi_hash: Mapped[str] = mapped_column(String)
    garam: Mapped[str] = mapped_column(String)
    peran: Mapped[str] = mapped_column(String, index=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Claim(Base):
    """Satu pengajuan klaim dari surveyor."""

    __tablename__ = "claim"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    nomor_klaim: Mapped[str] = mapped_column(String, unique=True, index=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policy.id"))
    vehicle_model_id: Mapped[str | None] = mapped_column(
        ForeignKey("vehicle_model.id"), nullable=True
    )
    surveyor: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="diproses", index=True)
    verdict_validitas: Mapped[str | None] = mapped_column(String, nullable=True)
    narasi: Mapped[str] = mapped_column(Text, default="")
    agent_rekomendasi: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_alasan: Mapped[str] = mapped_column(Text, default="")
    agent_jumlah_pass: Mapped[int] = mapped_column(Integer, default=0)
    contoh_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    photos: Mapped[list["ClaimPhoto"]] = relationship(back_populates="claim")
    checks: Mapped[list["ValidityCheck"]] = relationship(back_populates="claim")


class ClaimPhoto(Base):
    """Satu foto milik klaim, entah foto kerusakan atau foto STNK.

    `phash` adalah sidik jari isi gambar, dipakai mendeteksi foto yang dipakai ulang dari
    klaim lain. Berbeda dengan hash file biasa, nilainya nyaris tidak berubah kalau foto
    disimpan ulang dengan kualitas berbeda.
    """

    __tablename__ = "claim_photo"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claim.id"), index=True)
    jenis: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    phash: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    exif: Mapped[dict] = mapped_column(JSON, default=dict)
    urutan: Mapped[int] = mapped_column(Integer, default=0)
    # Garis tepi tiap mask, dipakai layar pratinjau yang menggambar overlaynya sendiri.
    # Kosong untuk foto lama, dan layar itu jatuh ke gambar overlay biasa kalau kosong.
    bentuk: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    claim: Mapped["Claim"] = relationship(back_populates="photos")


class StnkExtraction(Base):
    """Hasil pembacaan foto STNK, satu baris per klaim.

    Confidence disimpan per field, bukan satu angka untuk seluruh STNK, karena dampak
    salah baca berbeda-beda. Nomor rangka yang salah langsung menggagalkan pencocokan ke
    polis, sedangkan nama pemilik yang meleset satu huruf dampaknya kecil.
    """

    __tablename__ = "stnk_extraction"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claim.id"), unique=True, index=True)
    merk: Mapped[str | None] = mapped_column(String, nullable=True)
    tipe: Mapped[str | None] = mapped_column(String, nullable=True)
    tahun: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nomor_polisi: Mapped[str | None] = mapped_column(String, nullable=True)
    nomor_rangka: Mapped[str | None] = mapped_column(String, nullable=True)
    nomor_mesin: Mapped[str | None] = mapped_column(String, nullable=True)
    nama_pemilik: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[dict] = mapped_column(JSON, default=dict)
    teks_mentah: Mapped[str] = mapped_column(Text, default="")
    pakai_llm: Mapped[bool] = mapped_column(Boolean, default=False)


class DetectionResult(Base):
    """Hasil penumpukan mask bagian dan mask kerusakan, satu baris per temuan per foto.

    `rasio_luas` = luas irisan dibagi luas mask bagian. Angka inilah yang dipakai
    cost engine untuk memutuskan ganti atau perbaiki.
    """

    __tablename__ = "detection_result"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    claim_photo_id: Mapped[str] = mapped_column(ForeignKey("claim_photo.id"), index=True)
    part_class: Mapped[str] = mapped_column(String, index=True)
    sisi: Mapped[str | None] = mapped_column(String, nullable=True)
    damage_class: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence_part: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_damage: Mapped[float] = mapped_column(Float, default=0.0)
    luas_part_px: Mapped[int] = mapped_column(Integer, default=0)
    luas_damage_px: Mapped[int] = mapped_column(Integer, default=0)
    luas_irisan_px: Mapped[int] = mapped_column(Integer, default=0)
    rasio_luas: Mapped[float] = mapped_column(Float, default=0.0)
    polygon: Mapped[dict] = mapped_column(JSON, default=dict)
    # Nomor mask asalnya di foto ini. Kosong untuk klaim lama, dan layarnya menomori
    # ulang sendiri kalau kosong.
    part_urutan: Mapped[int | None] = mapped_column(Integer, nullable=True)
    damage_urutan: Mapped[int | None] = mapped_column(Integer, nullable=True)


class DetectionReview(Base):
    """Penilaian adjuster atas satu temuan deteksi: benar, atau salah beserta alasannya.

    Terpisah dari `adjuster_decision` karena menjawab pertanyaan yang berbeda. Tabel ini
    mengukur apakah modelnya benar, tabel itu mencatat apakah klaimnya dibayar. Sebuah
    klaim bisa ditolak meski deteksinya sempurna, dan sebaliknya.

    Baris yang salah adalah label gratis dari ahlinya, dipakai melatih ulang model.
    """

    __tablename__ = "detection_review"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    detection_result_id: Mapped[str] = mapped_column(
        ForeignKey("detection_result.id"), index=True, unique=True
    )
    claim_id: Mapped[str] = mapped_column(ForeignKey("claim.id"), index=True)
    benar: Mapped[bool] = mapped_column(Boolean, default=True)
    alasan: Mapped[str | None] = mapped_column(String, nullable=True)
    oleh: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class StnkReview(Base):
    """Penilaian adjuster atas satu field hasil baca STNK.

    Terpisah dari `stnk_extraction` supaya yang dibaca mesin dan yang dikoreksi manusia
    tidak pernah tertukar. Baris di sini tidak mengubah hasil cek validitas, fungsinya
    mengukur ketelitian pembacaan per field dan menyediakan nilai benar untuk perbaikan.
    """

    __tablename__ = "stnk_review"
    __table_args__ = (UniqueConstraint("claim_id", "field", name="uq_stnk_review"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claim.id"), index=True)
    field: Mapped[str] = mapped_column(String)
    benar: Mapped[bool] = mapped_column(Boolean, default=True)
    nilai_benar: Mapped[str | None] = mapped_column(String, nullable=True)
    oleh: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ValidityCheck(Base):
    """Hasil satu pemeriksaan anti-kecurangan, satu baris per kode cek per klaim.

    Disimpan per cek, bukan sebagai satu skor, supaya adjuster bisa melihat persis
    pemeriksaan mana yang gagal beserta alasannya.
    """

    __tablename__ = "validity_check"
    __table_args__ = (UniqueConstraint("claim_id", "kode", name="uq_validity_check"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claim.id"), index=True)
    kode: Mapped[str] = mapped_column(String)
    nama: Mapped[str] = mapped_column(String)
    lolos: Mapped[bool] = mapped_column(Boolean)
    tingkat: Mapped[str | None] = mapped_column(String, nullable=True)
    alasan: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)

    claim: Mapped["Claim"] = relationship(back_populates="checks")


class CostEstimate(Base):
    """Ringkasan biaya satu klaim beserta keputusan total loss."""

    __tablename__ = "cost_estimate"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claim.id"), unique=True, index=True)
    total_part: Mapped[float] = mapped_column(Rupiah, default=0)
    total_jasa: Mapped[float] = mapped_column(Rupiah, default=0)
    total_biaya: Mapped[float] = mapped_column(Rupiah, default=0)
    harga_pasar_bekas: Mapped[float] = mapped_column(Rupiah, default=0)
    # Asal harga pasar bekas. Harga ini penyebut rasio total loss dan penentu besar
    # penawaran beli kendaraan, jadi asalnya ikut disimpan dan ikut ditampilkan. Nilainya
    # "database", "database_polis", "pencarian_ai", atau "tidak_diketahui".
    harga_pasar_sumber: Mapped[str] = mapped_column(String, default="database")
    harga_pasar_keterangan: Mapped[str] = mapped_column(Text, default="")
    # Diisi adjuster saat dia mengonfirmasi harga hasil pencarian, atau mengoreksinya.
    harga_dikonfirmasi_oleh: Mapped[str | None] = mapped_column(String, nullable=True)
    total_loss_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    ambang_total_loss: Mapped[float] = mapped_column(Float, default=0.75)
    rekomendasi: Mapped[str] = mapped_column(String)
    own_risk: Mapped[float] = mapped_column(Rupiah, default=0)
    ditanggung_penanggung: Mapped[float] = mapped_column(Rupiah, default=0)
    # Harga tawaran kalau klaim ini total loss. Disimpan supaya adjuster tahu angkanya
    # sebelum memutuskan, bukan setelah penawarannya terlanjur terbit.
    harga_tawaran_salvage: Mapped[float | None] = mapped_column(Rupiah, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    lines: Mapped[list["CostEstimateLine"]] = relationship(back_populates="estimate")


class HargaPasarRujukan(Base):
    """Sumber yang dipakai agent saat harga pasar bekas dicari di internet.

    Wajib ada supaya adjuster bisa membuka sendiri halaman yang jadi dasar angkanya. Tanpa
    ini, harga hasil pencarian tidak bisa dibedakan dari harga yang dikarang model, padahal
    angka itu menentukan apakah mobil dinyatakan total loss.
    """

    __tablename__ = "harga_pasar_rujukan"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claim.id"), index=True)
    judul: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    cuplikan: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CostEstimateLine(Base):
    """Satu baris rincian biaya.

    `sumber` membedakan baris yang berasal dari deteksi foto dan baris yang dimasukkan
    aturan karena bagiannya tidak terlihat dari luar (radiator, airbag). Pemisahan ini
    ditampilkan ke adjuster supaya tidak terbaca seolah semuanya hasil deteksi.
    """

    __tablename__ = "cost_estimate_line"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    cost_estimate_id: Mapped[str] = mapped_column(ForeignKey("cost_estimate.id"), index=True)
    part_class: Mapped[str] = mapped_column(String)
    sisi: Mapped[str | None] = mapped_column(String, nullable=True)
    nama_part: Mapped[str] = mapped_column(String)
    # Disalin dari katalog saat estimasi dibuat, bukan dicari lagi saat dokumen dicetak.
    # Harga dan nomor part di katalog bisa berubah, dan estimasi yang sudah diputuskan
    # tidak boleh ikut berubah di belakang layar.
    nomor_part: Mapped[str] = mapped_column(String, default="")
    damage_class: Mapped[str | None] = mapped_column(String, nullable=True)
    # Kerusakan lain di bagian yang sama, dipisah koma. Satu bagian cuma boleh punya satu
    # baris biaya, jadi tanpa kolom ini kerusakan yang kalah operasinya hilang dari layar.
    kerusakan_lain: Mapped[str] = mapped_column(String, default="")
    rasio_luas: Mapped[float] = mapped_column(Float, default=0.0)
    operasi: Mapped[str] = mapped_column(String)
    ganti_part: Mapped[bool] = mapped_column(Boolean, default=False)
    harga_part: Mapped[float] = mapped_column(Rupiah, default=0)
    jam_standar: Mapped[float] = mapped_column(Float, default=0.0)
    biaya_jasa: Mapped[float] = mapped_column(Rupiah, default=0)
    sumber: Mapped[str] = mapped_column(String, default="deteksi")

    estimate: Mapped["CostEstimate"] = relationship(back_populates="lines")


class PhotoRequest(Base):
    """Permintaan foto tambahan ke surveyor.

    Permintaannya disimpan sebagai kalimat spesifik (bagian mana, dari sisi mana, sejauh
    apa), bukan sekadar penanda "butuh foto lagi", supaya surveyor cukup sekali kirim.
    `alasan` melekat pada permintaan ini saja, bukan alasan seluruh klaim, supaya surveyor
    tahu kenapa justru bagian itu yang diminta.
    """

    __tablename__ = "photo_request"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claim.id"), index=True)
    permintaan: Mapped[str] = mapped_column(Text)
    alasan: Mapped[str] = mapped_column(Text, default="")
    # "aturan" kalau lahir dari aturan kode, "agent" kalau dari pertimbangan LLM.
    sumber: Mapped[str] = mapped_column(String, default="aturan")
    dipenuhi: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Spk(Base):
    """Surat Perintah Kerja ke bengkel rekanan, terbit kalau klaim disetujui dan repair."""

    __tablename__ = "spk"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claim.id"), unique=True, index=True)
    nomor_spk: Mapped[str] = mapped_column(String, unique=True)
    bengkel: Mapped[str] = mapped_column(String)
    nilai_disetujui: Mapped[float] = mapped_column(Rupiah, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SalvageOffer(Base):
    """Penawaran beli kendaraan, terbit kalau klaim disetujui dan total loss."""

    __tablename__ = "salvage_offer"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claim.id"), unique=True, index=True)
    harga_pasar_bekas: Mapped[float] = mapped_column(Rupiah, default=0)
    faktor_salvage: Mapped[float] = mapped_column(Float, default=0.30)
    harga_tawaran: Mapped[float] = mapped_column(Rupiah, default=0)
    status: Mapped[str] = mapped_column(String, default="diajukan")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AdjusterDecision(Base):
    """Keputusan akhir manusia. Tidak ada klaim yang selesai tanpa melewati tabel ini."""

    __tablename__ = "adjuster_decision"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claim.id"), index=True)
    keputusan: Mapped[str] = mapped_column(String)
    catatan: Mapped[str] = mapped_column(Text, default="")
    oleh: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    """Catatan permanen tiap tahap. Hak UPDATE dan DELETE dicabut di production."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    claim_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    tahap: Mapped[str] = mapped_column(String)
    aksi: Mapped[str] = mapped_column(String)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LlmUsage(Base):
    """Pemakaian token per klaim per langkah.

    Dicatat supaya angka riil pemakaian token bisa ditunjukkan saat presentasi, bukan
    cuma perkiraan, dan supaya kuota harian yang ketat bisa dipantau.
    """

    __tablename__ = "llm_usage"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    claim_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    langkah: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    token_masuk: Mapped[int] = mapped_column(Integer, default=0)
    token_keluar: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
