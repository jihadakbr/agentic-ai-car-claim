"""Membaca field dari foto STNK.

Pembacaan huruf dikerjakan model OCR yang sudah terlatih, bukan model bahasa. Yang ditulis
di sini adalah pemasangan teks hasil OCR ke field yang benar, karena tata letak STNK relatif
tetap sehingga pencocokan label jauh lebih murah dan lebih bisa diuji daripada memanggil LLM.

Dua bentuk keluaran OCR sama-sama muncul di lembar yang sama dan dua-duanya harus ditangani:

- label dan nilai menyatu dalam satu kotak, "No. Registrasi : B 1234 ABC"
- label dan nilai jadi dua kotak terpisah pada baris yang sama, "Merk" lalu "TOYOTA"

Pencocokan label dibuat toleran karena OCR sering menggeser tanda baca. Yang tidak toleran
adalah nilainya: nilai dipakai apa adanya, tidak pernah ditebak atau diperbaiki, supaya
ketidakcocokan dengan data polis benar-benar terlihat oleh pemeriksaan validitas.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image

from app.pipeline.validity import HasilStnk

# Label pada lembar STNK, dipetakan ke nama field. Ditulis dalam bentuk yang sudah
# dinormalkan supaya perbandingannya tidak terganggu titik dan spasi.
_LABEL = {
    "noregistrasi": "nomor_polisi",
    "nrkb": "nomor_polisi",
    "namapemilik": "nama_pemilik",
    "alamat": "alamat",
    "merk": "merk",
    "merek": "merk",
    "type": "tipe",
    "tipe": "tipe",
    "tipetipedagang": "tipe",
    "jenis": "jenis",
    "model": "model",
    "tahunpembuatan": "tahun",
    "isisilinder": "isi_silinder",
    "isisilinderdayalistrik": "isi_silinder",
    "norangka": "nomor_rangka",
    "nomorrangkanikvin": "nomor_rangka",
    "nomesin": "nomor_mesin",
    "nomormesinmotorpenggerak": "nomor_mesin",
    "warna": "warna",
    "bahanbakar": "bahan_bakar",
    "bahanbakarsumberenergi": "bahan_bakar",
    "warnatnkb": "warna_tnkb",
    "berlakusampai": "berlaku_sampai",
    # Label berikut isinya tidak dipakai pemeriksaan mana pun. Tetap didaftarkan supaya
    # dikenali sebagai label, sebab kalau tidak, teksnya ikut jadi calon nilai untuk field
    # di sebelahnya. "Tahun Registrasi" paling berbahaya: tanpa baris ini, ekornya mirip
    # "No. Registrasi" sehingga tahun perpanjangan terbaca sebagai nomor polisi.
    "tahunregistrasi": "tahun_registrasi",
    "nomorbpkb": "nomor_bpkb",
    "nomorpendaftaran": "nomor_pendaftaran",
    "niknpwpnibkitaskitap": "nik",
    "kodelokasi": "kode_lokasi",
}

# Kemiripan minimum sebuah teks terhadap label yang dikenal. Di bawah ini teksnya dianggap
# nilai, bukan label, supaya baris isian tidak salah dibaca sebagai judul kolom.
KEMIRIPAN_LABEL = 0.82

# Label yang menempel di ekor kotak dinilai lebih ketat. Potongan satu kata gampang mirip
# label lain secara kebetulan, dan salah kenal di sini langsung memasangkan nilai ke field
# yang salah, bukan sekadar gagal membaca.
KEMIRIPAN_EKOR = 0.92

# Selisih tinggi yang masih dianggap satu baris, sebagai pecahan tinggi gambar. Pada lembar
# sungguhan tiap label punya terjemahan Inggris di bawahnya, sehingga nilainya rata tengah
# terhadap dua baris label dan titik atasnya bergeser belasan piksel.
TOLERANSI_BARIS = 0.035

# Sejauh mana nilai boleh berada di kanan labelnya, sebagai pecahan lebar gambar. Tanpa batas
# ini, label di kolom kiri yang nilainya gagal terbaca akan mengambil isi kolom kanan.
JANGKAUAN_NILAI = 0.30

# Nilai dicari mulai dari tepi kanan labelnya, bukan tepi kiri, supaya terjemahan Inggris
# yang tercetak persis di bawah label tidak ikut terjaring. Kelonggaran kecil diberikan
# karena kotak label hasil OCR kadang melar sedikit melewati teksnya.
SLACK_LABEL = 0.02

WAJIB = ("merk", "tahun", "nomor_polisi", "nomor_rangka")


@dataclass
class KotakTeks:
    """Satu potongan teks hasil OCR beserta posisinya di gambar."""

    teks: str
    x: float
    y: float
    keyakinan: float = 1.0
    lebar: float = 0.0

    @property
    def tepi_kanan(self) -> float:
        return self.x + self.lebar


@dataclass
class HasilBaca:
    stnk: HasilStnk
    keyakinan: dict[str, float] = field(default_factory=dict)
    teks_mentah: str = ""
    field_hilang: list[str] = field(default_factory=list)


class PembacaOcr(Protocol):
    """Antarmuka pembaca huruf, dipisah supaya parser bisa diuji tanpa memuat model."""

    def baca(self, gambar: Image.Image) -> list[KotakTeks]: ...


def normalkan_label(teks: str) -> str:
    return re.sub(r"[^a-z0-9]", "", teks.lower())


def cocokkan_label(teks: str) -> str | None:
    """Kembalikan nama field kalau teksnya cukup mirip salah satu label yang dikenal."""
    kunci = normalkan_label(teks)
    if not kunci:
        return None
    if kunci in _LABEL:
        return _LABEL[kunci]
    mirip = difflib.get_close_matches(kunci, _LABEL, n=1, cutoff=KEMIRIPAN_LABEL)
    return _LABEL[mirip[0]] if mirip else None


def _pisah_di_titik_dua(teks: str) -> tuple[str, str] | None:
    """Pecah "No. Rangka : MHKM..." jadi label dan nilai."""
    if ":" not in teks:
        return None
    kiri, kanan = teks.split(":", 1)
    return kiri.strip(), kanan.strip()


def label_di_ekor(teks: str) -> str | None:
    """Kenali label yang menempel di ujung kanan sebuah kotak.

    Pendeteksi teks kadang menyatukan nilai kolom kiri dengan label kolom kanan jadi satu
    kotak, misalnya "JL KEBON JERUK NO 27 No. Rangka". Tanpa penanganan ini, label yang
    tertelan itu hilang dan field di sebelahnya ikut gagal terbaca.
    """
    kata = teks.split()
    if len(kata) < 2:
        return None
    for jumlah in (3, 2, 1):
        if jumlah >= len(kata):
            continue
        kunci = normalkan_label(" ".join(kata[-jumlah:]))
        if not kunci:
            continue
        if kunci in _LABEL:
            return _LABEL[kunci]
        mirip = difflib.get_close_matches(kunci, _LABEL, n=1, cutoff=KEMIRIPAN_EKOR)
        if mirip:
            return _LABEL[mirip[0]]
    return None


def _nilai_di_kanan(
    label: KotakTeks, kotak: list[KotakTeks], lebar: int, tinggi: int, mulai: float
) -> KotakTeks | None:
    """Cari kotak nilai pada baris yang sama, paling dekat di sebelah kanan label."""
    sebaris = [
        k
        for k in kotak
        if k is not label
        and abs(k.y - label.y) <= tinggi * TOLERANSI_BARIS
        and mulai < k.x <= mulai + lebar * JANGKAUAN_NILAI
        and cocokkan_label(k.teks) is None
        and label_di_ekor(k.teks) is None
    ]
    if not sebaris:
        return None
    return min(sebaris, key=lambda k: k.x)


def _bersihkan(nilai: str) -> str:
    # Titik dua pemisah label tercetak di lembar, dan OCR sering menempelkannya di depan
    # nilai sebagai petik atau koma.
    return nilai.strip(" :;,.'\"`").strip()


def baca_field(kotak: list[KotakTeks], lebar: int, tinggi: int) -> dict[str, tuple[str, float]]:
    """Pasangkan tiap kotak teks ke field yang sesuai."""
    hasil: dict[str, tuple[str, float]] = {}

    for k in kotak:
        pecah = _pisah_di_titik_dua(k.teks)
        if pecah:
            nama = cocokkan_label(pecah[0])
            if nama and pecah[1]:
                hasil.setdefault(nama, (_bersihkan(pecah[1]), k.keyakinan))
                continue

        nama = cocokkan_label(k.teks)
        mulai = (k.tepi_kanan or k.x) - lebar * SLACK_LABEL
        if nama is None:
            # Label yang tertelan kotak sebelahnya dicari mulai dari tepi kanan kotak itu,
            # bukan dari tepi kirinya, karena labelnya ada di ujung kanan.
            nama = label_di_ekor(k.teks)
        if not nama or nama in hasil:
            continue
        nilai = _nilai_di_kanan(k, kotak, lebar, tinggi, mulai)
        if nilai is not None and _bersihkan(nilai.teks):
            hasil[nama] = (_bersihkan(nilai.teks), min(k.keyakinan, nilai.keyakinan))

    return hasil


def _tahun(nilai: str) -> int | None:
    angka = re.search(r"(19|20)\d{2}", nilai)
    return int(angka.group()) if angka else None


def susun(kotak: list[KotakTeks], lebar: int, tinggi: int) -> HasilBaca:
    """Susun hasil pembacaan jadi bentuk yang dipakai pemeriksaan validitas."""
    terbaca = baca_field(kotak, lebar, tinggi)

    def ambil(nama: str) -> str | None:
        pasangan = terbaca.get(nama)
        return pasangan[0] if pasangan else None

    tahun_teks = ambil("tahun")
    stnk = HasilStnk(
        merk=ambil("merk"),
        tipe=ambil("tipe"),
        tahun=_tahun(tahun_teks) if tahun_teks else None,
        nomor_polisi=ambil("nomor_polisi"),
        nomor_rangka=ambil("nomor_rangka"),
        nomor_mesin=ambil("nomor_mesin"),
        nama_pemilik=ambil("nama_pemilik"),
    )

    return HasilBaca(
        stnk=stnk,
        keyakinan={n: k for n, (_, k) in terbaca.items()},
        teks_mentah="\n".join(k.teks for k in kotak),
        field_hilang=[n for n in WAJIB if getattr(stnk, n) is None],
    )


def baca_stnk(gambar: Image.Image, pembaca: PembacaOcr) -> HasilBaca:
    return susun(pembaca.baca(gambar), gambar.width, gambar.height)


class PembacaRapidOcr:
    """Pembaca sungguhan, memakai RapidOCR di atas ONNX Runtime.

    Model dimuat sekali saat objek dibuat. Jalannya di CPU dan sengaja di luar fungsi yang
    meminta GPU, karena kuota GPU dihitung dari lama fungsi berjalan.
    """

    def __init__(self) -> None:
        from rapidocr import RapidOCR

        self._mesin = RapidOCR()

    def baca(self, gambar: Image.Image) -> list[KotakTeks]:
        import numpy as np

        # Pengklasifikasi arah teks dimatikan. Tugasnya membalik teks yang terbaca terbalik
        # 180 derajat, dan STNK yang difoto surveyor tidak pernah begitu. Menyalakannya
        # membuat pembacaan sepuluh kali lebih lama tanpa menaikkan akurasi sama sekali,
        # terukur 97.1% pada dua-duanya.
        hasil = self._mesin(np.array(gambar.convert("RGB")), use_cls=False)
        if hasil is None or hasil.boxes is None or hasil.txts is None:
            return []
        return [
            KotakTeks(teks=teks, x=float(kotak[0][0]), y=float(kotak[0][1]),
                      keyakinan=float(skor),
                      lebar=float(kotak[1][0]) - float(kotak[0][0]))
            for teks, skor, kotak in zip(hasil.txts, hasil.scores, hasil.boxes, strict=True)
        ]
