"""Jembatan antara tabel database dan dataclass yang dipakai cost engine.

Cost engine sengaja tidak tahu apa-apa soal database. Semua isinya fungsi murni di atas
dataclass, sehingga bisa diuji tanpa menyalakan database sama sekali. Modul inilah yang
membaca baris tabel lalu mengubahnya jadi bentuk yang dimengerti cost engine.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Config, LaborRate, PartCatalog, RepairMatrix, VehicleModel
from app.pipeline.cost_engine import AturanPerbaikan, Part, Tarif


class KonfigurasiTidakAda(Exception):
    """Kunci konfigurasi tidak ditemukan di tabel `config`.

    Dilempar, bukan diganti nilai bawaan diam-diam. Ambang total loss yang tiba-tiba
    memakai angka bawaan tanpa ada yang tahu jauh lebih berbahaya daripada proses berhenti.
    """


def ambil_config(s: Session, key: str) -> str:
    baris = s.get(Config, key)
    if baris is None:
        raise KonfigurasiTidakAda(f"Kunci konfigurasi '{key}' tidak ada di tabel config")
    return baris.value


def ambil_config_float(s: Session, key: str) -> float:
    return float(ambil_config(s, key))


def ambil_config_int(s: Session, key: str) -> int:
    return int(ambil_config(s, key))


def ambil_config_rupiah(s: Session, key: str) -> Decimal:
    return Decimal(ambil_config(s, key))


def muat_matriks(s: Session) -> list[AturanPerbaikan]:
    """Urutkan dari rentang tersempit lebih dulu.

    Aturan dengan rentang sempit (`Dent` 0 sampai 0.25) harus diperiksa sebelum aturan
    yang rentangnya penuh, supaya yang lebih spesifik menang kalau keduanya cocok.
    """
    baris = list(s.scalars(select(RepairMatrix)))
    baris.sort(key=lambda r: (r.damage_class, r.rasio_max - r.rasio_min, r.rasio_min))
    return [
        AturanPerbaikan(
            damage_class=r.damage_class,
            rasio_min=r.rasio_min,
            rasio_max=r.rasio_max,
            operasi=r.operasi,
            ganti_part=r.ganti_part,
        )
        for r in baris
    ]


def muat_tarif(s: Session) -> list[Tarif]:
    return [
        Tarif(
            operasi=r.operasi,
            part_class=r.part_class,
            jam_standar=r.jam_standar,
            tarif_per_jam=Decimal(r.tarif_per_jam),
        )
        for r in s.scalars(select(LaborRate))
    ]


def muat_katalog(s: Session, vehicle_model_id: str) -> dict[str, Part]:
    """Ambil katalog sparepart untuk satu model kendaraan, dikunci per `part_class`."""
    baris = s.scalars(
        select(PartCatalog).where(PartCatalog.vehicle_model_id == vehicle_model_id)
    )
    return {
        r.part_class: Part(
            part_class=r.part_class,
            nama_part=r.nama_part,
            harga=Decimal(r.harga),
            terlihat_dari_luar=r.terlihat_dari_luar,
            nomor_part=r.nomor_part,
        )
        for r in baris
    }


def cari_kendaraan(s: Session, merk: str, tipe: str, tahun: int) -> VehicleModel | None:
    """Cari kendaraan dari hasil pembacaan STNK.

    Pencocokan dibuat tidak peka huruf besar kecil dan mengabaikan spasi berlebih, karena
    hasil pembacaan tulisan sering berbeda tipis dari yang tersimpan di database.
    """
    merk_bersih = " ".join(merk.upper().split())
    tipe_bersih = " ".join(tipe.upper().split())
    for k in s.scalars(select(VehicleModel).where(VehicleModel.tahun == tahun)):
        if " ".join(k.merk.upper().split()) != merk_bersih:
            continue
        if " ".join(k.tipe.upper().split()) == tipe_bersih:
            return k
    return None
