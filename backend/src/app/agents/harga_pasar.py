"""Cari harga pasar bekas satu kendaraan, dari katalog atau dari internet.

Ini alat milik agent, dan tempat sifat agentic sistem ini paling terlihat: bukan sekadar
menjawab dari data yang sudah disodorkan, tapi memutuskan bahwa datanya kurang, mengambil
sendiri dari luar, lalu menyebut dari mana angkanya.

Harga pasar bekas adalah **penyebut** rasio total loss. Salah di sini bukan salah kecil:
mobil yang seharusnya dinyatakan total loss bisa lolos jadi perbaikan biasa, dan besar
penawaran pembelian kendaraan ikut meleset. Karena itu tiga hal dipegang ketat:

1. Angka hasil pencarian selalu membawa tautan sumbernya, dan cuma sumber yang benar-benar
   dipakai agent yang disimpan.
2. Angka di luar batas wajar ditolak, diperlakukan sama seperti tidak ketemu.
3. Kalau tidak ketemu, hasilnya dinyatakan tidak diketahui. Tidak pernah nol, tidak pernah
   ditebak.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal

from app.agents.pencari_web import HasilCari, PencariWeb
from app.core.llm import (
    KlienLLM,
    Penggunaan,
    PenjagaAnggaran,
    ambil_json,
    teks_bersih,
)

_log = logging.getLogger(__name__)

SUMBER_DATABASE = "database"
SUMBER_POLIS = "database_polis"
SUMBER_PENCARIAN = "pencarian_ai"
SUMBER_TIDAK_DIKETAHUI = "tidak_diketahui"

MAX_TOKEN_KELUAR = 250

# Batas kewajaran harga mobil bekas di Indonesia. Model yang salah membaca cuplikan bisa
# mengembalikan harga sepeda motor, harga cicilan bulanan, atau nomor telepon, dan angka itu
# langsung menentukan besar penawaran pembelian kendaraan.
HARGA_MINIMUM = Decimal(15_000_000)
HARGA_MAKSIMUM = Decimal(2_000_000_000)


@dataclass(frozen=True)
class Rujukan:
    judul: str
    url: str
    cuplikan: str


@dataclass
class HargaPasar:
    nilai: Decimal | None
    sumber: str
    keterangan: str
    rujukan: list[Rujukan] = field(default_factory=list)
    penggunaan: list[Penggunaan] = field(default_factory=list)

    @property
    def dari_pencarian(self) -> bool:
        return self.sumber == SUMBER_PENCARIAN

    @property
    def diketahui(self) -> bool:
        return self.nilai is not None and self.nilai > 0


def nama_kendaraan(merk: str, tipe: str, tahun: int | None, nama_pasar: str = "") -> str:
    """Sebut kendaraan dengan nama yang dikenal pasar, bukan kode tipe di STNK.

    Tipe di STNK berupa kode pabrik seperti `AF12 LUX CVT` yang tidak pernah muncul di iklan
    mobil bekas, jadi memakainya sebagai kunci pencarian selalu berujung nihil.
    """
    dasar = nama_pasar.strip() or " ".join(b for b in (merk, tipe) if b)
    return " ".join(b for b in (dasar, str(tahun) if tahun else "") if b)


def kueri_pencarian(merk: str, tipe: str, tahun: int | None, nama_pasar: str = "") -> str:
    """Kata "mulai dari Rp" sengaja ikut dicari.

    Yang dibaca agent cuma cuplikan singkat di daftar hasil, bukan isi halamannya, karena
    situs mobil bekas menolak diambil otomatis. Kueri yang menyebut bentuk kalimatnya
    membuat mesin pencari memilih cuplikan yang memang memuat angka. Terukur: kueri lama
    memberi 3 dari 5 cuplikan berharga, kueri ini 5 dari 5.
    """
    return f"harga bekas {nama_kendaraan(merk, tipe, tahun, nama_pasar)} mulai dari Rp"


def kueri_cadangan(merk: str, tipe: str, tahun: int | None, nama_pasar: str = "") -> str:
    """Dipakai kalau kueri utama tidak menghasilkan satu pun cuplikan berharga."""
    return f"harga mobil bekas {nama_kendaraan(merk, tipe, tahun, nama_pasar)} Indonesia"


_HARGA_DI_TEKS = re.compile(r"Rp\s?[\d.,]{2,}", re.IGNORECASE)


def ada_harga(hasil: list[HasilCari]) -> bool:
    return any(_HARGA_DI_TEKS.search(h.cuplikan) for h in hasil)


def _gabung(utama: list[HasilCari], tambahan: list[HasilCari]) -> list[HasilCari]:
    sudah = {h.url for h in utama}
    return utama + [h for h in tambahan if h.url not in sudah]


def susun_prompt(
    merk: str, tipe: str, tahun: int | None, hasil: list[HasilCari], nama_pasar: str = ""
) -> str:
    """Prompt sengaja pendek dan menuntut nomor sumber, bukan cuma angka.

    Tanpa nomor sumber, tidak ada cara memeriksa apakah angkanya benar-benar berasal dari
    hasil pencarian atau dikarang model.
    """
    kendaraan = nama_kendaraan(merk, tipe, tahun, nama_pasar)
    baris = [f"[{i}] {h.judul}\n{h.cuplikan}" for i, h in enumerate(hasil)]
    return "\n".join([
        f"Perkirakan harga pasar mobil bekas {kendaraan} di Indonesia dalam rupiah,",
        "berdasarkan hasil pencarian di bawah ini saja.",
        "",
        "HASIL PENCARIAN:",
        *baris,
        "",
        "Aturan:",
        "- Ambil angka dari cuplikan, jangan dari pengetahuanmu sendiri.",
        "- Kalau tidak ada cuplikan yang menyebut harga mobil ini, jawab harga null.",
        "- sumber_dipakai berisi nomor kurung siku cuplikan yang benar-benar kamu pakai.",
        "",
        "Jawab JSON saja dengan bentuk:",
        '{"harga": angka bulat rupiah atau null, "alasan": string, "sumber_dipakai": [angka]}',
    ])


def _baca_harga(nilai) -> Decimal | None:
    """Terima angka maupun teks berformat rupiah, tolak yang di luar batas wajar."""
    if nilai is None:
        return None
    teks = str(nilai)
    bersih = "".join(c for c in teks if c.isdigit())
    if not bersih:
        return None
    harga = Decimal(bersih)
    if harga < HARGA_MINIMUM or harga > HARGA_MAKSIMUM:
        _log.warning("harga hasil pencarian di luar batas wajar, ditolak: %s", harga)
        return None
    return harga


def _rujukan_dipakai(hasil: list[HasilCari], nomor) -> list[Rujukan]:
    """Ambil hasil yang ditunjuk agent saja.

    Menyimpan seluruh hasil pencarian akan menampilkan tautan yang tidak ada hubungannya
    dengan angka yang dipakai, dan adjuster yang membukanya justru jadi salah paham.
    """
    if not isinstance(nomor, list):
        return []
    dipakai = []
    for n in nomor:
        try:
            i = int(n)
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(hasil):
            h = hasil[i]
            dipakai.append(Rujukan(judul=h.judul, url=h.url, cuplikan=h.cuplikan))
    return dipakai


def dari_katalog(harga, sumber: str = SUMBER_DATABASE, keterangan: str = "") -> HargaPasar:
    return HargaPasar(
        nilai=Decimal(str(harga)),
        sumber=sumber,
        keterangan=keterangan or "Diambil dari katalog harga kendaraan di database",
    )


def tidak_diketahui(keterangan: str) -> HargaPasar:
    return HargaPasar(nilai=None, sumber=SUMBER_TIDAK_DIKETAHUI, keterangan=keterangan)


def cari(
    merk: str,
    tipe: str,
    tahun: int | None,
    pencari: PencariWeb,
    klien: KlienLLM,
    penjaga: PenjagaAnggaran,
    maksimal: int = 8,
    nama_pasar: str = "",
) -> HargaPasar:
    """Cari harga di internet lalu baca angkanya, lengkap dengan sumbernya."""
    kueri = kueri_pencarian(merk, tipe, tahun, nama_pasar)
    hasil = pencari.cari(kueri, maksimal=maksimal)

    # Hasil pencarian berbeda-beda tergantung dari mana permintaannya datang, jadi kueri
    # utama bisa saja mengembalikan cuplikan tanpa satu pun angka. Kueri kedua memakai
    # susunan kata yang lain supaya peluangnya tidak bergantung pada satu percobaan.
    if not ada_harga(hasil):
        lain = kueri_cadangan(merk, tipe, tahun, nama_pasar)
        hasil = _gabung(hasil, pencari.cari(lain, maksimal=maksimal))
        kueri = f"{kueri}' dan '{lain}"

    if not hasil:
        return tidak_diketahui(
            f"Pencarian '{kueri}' tidak menghasilkan apa pun. Harga harus diisi manual."
        )

    prompt = susun_prompt(merk, tipe, tahun, hasil, nama_pasar)
    # LLM yang mati tidak boleh menggagalkan klaim. Harga yang tidak diketahui masih bisa
    # diisi adjuster, sedangkan klaim yang gagal diproses menghentikan semuanya.
    try:
        penjaga.periksa(prompt, MAX_TOKEN_KELUAR)
        jawaban = klien.jawab(prompt, MAX_TOKEN_KELUAR)
        penjaga.catat(jawaban.penggunaan)
        data = ambil_json(jawaban.teks)
    except Exception as e:  # noqa: BLE001
        return tidak_diketahui(f"Pembacaan hasil pencarian gagal: {e}")

    harga = _baca_harga(data.get("harga"))
    alasan = teks_bersih(data.get("alasan"), "")

    if harga is None:
        return HargaPasar(
            nilai=None,
            sumber=SUMBER_TIDAK_DIKETAHUI,
            keterangan=(
                "Hasil pencarian tidak memuat harga yang bisa dipakai. "
                + (alasan or "Harga harus diisi manual.")
            ),
            penggunaan=[jawaban.penggunaan],
        )

    return HargaPasar(
        nilai=harga,
        sumber=SUMBER_PENCARIAN,
        keterangan=alasan or f"Hasil pencarian internet untuk '{kueri}'",
        rujukan=_rujukan_dipakai(hasil, data.get("sumber_dipakai")),
        penggunaan=[jawaban.penggunaan],
    )
