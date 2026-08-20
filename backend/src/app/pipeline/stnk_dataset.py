"""Susun kumpulan STNK buatan dari data polis yang sudah ada di database.

Data STNK tidak dikarang lepas dari sistem. Merk, tipe, tahun, nomor polisi, nomor rangka,
dan nama pemilik semuanya diambil dari tabel `policy` dan `vehicle_model`. Dengan begitu
STNK buatan otomatis konsisten dengan isi database, sehingga pemeriksaan kecocokan STNK ke
polis (cek C6) benar-benar bisa diuji, termasuk kasus yang sengaja dibuat tidak cocok.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.vin import buat_vin
from app.db.models import Policy, VehicleModel
from app.pipeline.stnk_generator import DataStnk, buat_stnk

WARNA = ["HITAM", "PUTIH", "SILVER", "ABU-ABU METALIK", "MERAH", "BIRU TUA"]
JENIS = "MOBIL PENUMPANG"
MODEL = "MINIBUS"

# Ketujuh kendaraan di data awal semuanya bermesin bensin. Bahan bakar tidak diacak, karena
# STNK Avanza yang tertulis SOLAR akan langsung terlihat janggal oleh siapa pun yang paham
# mobil, dan variasi untuk menguji pembacaan sebaiknya datang dari kualitas gambarnya, bukan
# dari isi yang keliru.
BAHAN_BAKAR_BENSIN = "BENSIN"


@dataclass
class ContohStnk:
    """Satu berkas STNK buatan beserta jawaban benarnya."""

    data: DataStnk
    jawaban_benar: dict
    nomor_polis: str | None
    sengaja_salah: str | None = None


def _isi_silinder(merk: str) -> str:
    return "1329 CC" if merk in {"TOYOTA", "DAIHATSU"} else "1197 CC"


def tahun_registrasi_terakhir(tahun_pembuatan: int, tahun_acuan: int) -> int:
    """Cari tahun perpanjangan STNK terakhir sebelum tahun acuan.

    STNK diperpanjang tiap 5 tahun terhitung dari tahun pembuatan, jadi masa berlakunya
    tidak boleh berupa tahun yang sudah lewat. Avanza 2013 yang polisnya masih hidup
    seharusnya STNK-nya sudah diperpanjang, bukan masih memuat masa berlaku 2018.
    """
    tahun = tahun_pembuatan
    while tahun + 5 < tahun_acuan:
        tahun += 5
    return tahun


def dari_polis(
    polis: Policy, kendaraan: VehicleModel, rng: random.Random
) -> ContohStnk:
    """Susun STNK yang isinya cocok sepenuhnya dengan polis."""
    data = DataStnk(
        nomor_registrasi=polis.nomor_polisi,
        nama_pemilik=polis.nama_pemegang,
        alamat=polis.alamat.split(",")[0],
        merk=kendaraan.merk,
        tipe=kendaraan.tipe,
        jenis=JENIS,
        model=MODEL,
        tahun_pembuatan=kendaraan.tahun,
        isi_silinder=_isi_silinder(kendaraan.merk),
        nomor_rangka=polis.nomor_rangka,
        nomor_mesin=polis.nomor_mesin,
        warna=rng.choice(WARNA),
        bahan_bakar=BAHAN_BAKAR_BENSIN,
        warna_tnkb="HITAM",
        tahun_registrasi=tahun_registrasi_terakhir(kendaraan.tahun, polis.berlaku_sampai.year),
    )
    return ContohStnk(data=data, jawaban_benar=data.sebagai_jawaban_benar(),
                      nomor_polis=polis.nomor_polis)


def dengan_kesalahan(contoh: ContohStnk, jenis_kesalahan: str, rng: random.Random) -> ContohStnk:
    """Buat versi STNK yang sengaja tidak cocok, untuk menguji cek validitas.

    Tanpa contoh yang sengaja salah, pemeriksaan kecurangan tidak pernah terbukti bekerja,
    cuma terbukti tidak pernah menolak apa pun.
    """
    data = DataStnk(**contoh.data.sebagai_jawaban_benar())

    if jenis_kesalahan == "nomor_rangka_beda":
        data.nomor_rangka = buat_vin("MHK", data.tahun_pembuatan, rng.randint(1, 999999), rng=rng)
    elif jenis_kesalahan == "nomor_polisi_beda":
        data.nomor_registrasi = f"B {rng.randint(1000, 9999)} {''.join(rng.choices('ABCDEFGHJKLMNPRSTUVWXYZ', k=3))}"
    elif jenis_kesalahan == "tahun_tidak_cocok_vin":
        # Nomor rangka tetap, tapi tahun pembuatannya digeser sehingga kode tahun di
        # karakter ke-10 tidak lagi cocok.
        data.tahun_pembuatan = data.tahun_pembuatan + 3
    elif jenis_kesalahan == "nomor_rangka_pendek":
        data.nomor_rangka = data.nomor_rangka[:11]
    else:
        raise ValueError(f"Jenis kesalahan tidak dikenal: {jenis_kesalahan}")

    return ContohStnk(
        data=data,
        jawaban_benar=data.sebagai_jawaban_benar(),
        nomor_polis=contoh.nomor_polis,
        sengaja_salah=jenis_kesalahan,
    )


def kumpulkan_dari_database(s: Session, rng: random.Random) -> list[ContohStnk]:
    """Ambil semua polis lalu susun STNK yang cocok untuk masing-masing."""
    hasil = []
    for polis in s.scalars(select(Policy).order_by(Policy.nomor_polis)):
        kendaraan = s.get(VehicleModel, polis.vehicle_model_id)
        hasil.append(dari_polis(polis, kendaraan, rng))
    return hasil


def tulis_berkas(
    contoh: list[ContohStnk],
    folder: Path,
    rng: random.Random,
    tingkat_kerusakan: float | Sequence[float] = 1.0,
    gaya: str = "acuan",
) -> list[Path]:
    """Render dan simpan seluruh contoh jadi berkas gambar.

    `tingkat_kerusakan` boleh satu angka untuk semua, atau satu daftar sepanjang `contoh`
    kalau tiap berkas mau dibuat dengan tingkat berbeda. Nama berkas memakai nomor urut,
    jadi seluruh contoh harus dikirim dalam satu panggilan. Memanggil fungsi ini berkali-kali
    dengan satu contoh akan membuat nomor urutnya selalu nol dan berkasnya saling menimpa.
    """
    folder.mkdir(parents=True, exist_ok=True)

    if isinstance(tingkat_kerusakan, (int, float)):
        tingkat = [float(tingkat_kerusakan)] * len(contoh)
    else:
        tingkat = list(tingkat_kerusakan)
        if len(tingkat) != len(contoh):
            raise ValueError(
                f"Jumlah tingkat kerusakan ({len(tingkat)}) tidak sama dengan "
                f"jumlah contoh ({len(contoh)})"
            )

    jalur = []
    for i, (c, t) in enumerate(zip(contoh, tingkat, strict=True)):
        gambar = buat_stnk(c.data, rng=rng, tingkat_kerusakan=t, gaya=gaya)
        akhiran = f"-{c.sengaja_salah}" if c.sengaja_salah else ""
        berkas = folder / f"stnk-{i:03d}-{c.data.nomor_registrasi.replace(' ', '')}{akhiran}.jpg"
        gambar.save(berkas, quality=88)
        jalur.append(berkas)
    return jalur
