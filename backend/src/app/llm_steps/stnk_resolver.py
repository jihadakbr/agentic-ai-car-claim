"""Menyusun teks hasil pembacaan STNK jadi field terstruktur.

LLM step kondisional, dan ini yang paling jarang jalan dari ketiganya. Tata letak STNK
baku, jadi pencarian kata kunci label sudah cukup untuk hampir semua foto. Fungsi ini baru
dipanggil kalau pencarian label gagal menemukan field wajib, misalnya STNK-nya terlipat
sehingga baris Merk dan Type menyatu jadi satu potongan teks berantakan.

Pencarian berbasis label dikerjakan lebih dulu karena hasilnya selalu sama untuk masukan
yang sama, dan tidak memakan token sama sekali.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.llm import KlienLLM, Penggunaan, PenjagaAnggaran, ambil_json, teks_bersih

MAX_TOKEN_KELUAR = 250

FIELD = ("merk", "tipe", "tahun", "nomor_polisi", "nomor_rangka", "nomor_mesin", "nama_pemilik")


@dataclass
class HasilResolver:
    field: dict[str, str | int | None]
    penggunaan: Penggunaan | None
    dipakai: bool


def susun_prompt(teks_ocr: str, sudah_terbaca: dict[str, object]) -> str:
    terbaca = [f"  {k}: {v}" for k, v in sudah_terbaca.items() if v]
    return "\n".join([
        "Teks berikut hasil pembacaan otomatis dari foto STNK Indonesia, dan sebagian",
        "barisnya menyatu atau berantakan.",
        "",
        teks_ocr[:1500],
        "",
        *(["Yang sudah berhasil dibaca dengan cara lain:"] + terbaca if terbaca else []),
        "",
        "Pisahkan jadi field berikut. Isi null untuk yang benar-benar tidak ada di teks,",
        "jangan menebak. Field yang ditebak jauh lebih berbahaya daripada field kosong,",
        "karena nomor rangka yang salah membuat klaim ditolak tanpa alasan yang benar.",
        "",
        'Jawab JSON saja: {"merk": string|null, "tipe": string|null, "tahun": number|null,',
        ' "nomor_polisi": string|null, "nomor_rangka": string|null, "nomor_mesin": string|null,',
        ' "nama_pemilik": string|null}',
    ])


def _tahun(nilai) -> int | None:
    try:
        tahun = int(str(nilai).strip())
    except (TypeError, ValueError):
        return None
    # Mobil pertama dibuat jauh sebelum ini, tapi STNK Indonesia tidak akan memuat tahun
    # di luar rentang wajar. Nilai di luar itu tanda salah baca, bukan mobil antik.
    return tahun if 1950 <= tahun <= 2100 else None


def susun(
    klien: KlienLLM | None,
    teks_ocr: str,
    sudah_terbaca: dict[str, object],
    penjaga: PenjagaAnggaran,
) -> HasilResolver:
    """Susun field dari teks berantakan. Field yang sudah terbaca tidak ditimpa.

    Hasil pencarian label lebih bisa dipercaya daripada hasil LLM, karena berasal dari
    posisi tulisan yang sebenarnya di gambar, bukan dari penalaran atas teks yang sudah
    terlanjur berantakan.
    """
    kosong = {k: sudah_terbaca.get(k) for k in FIELD}

    if klien is None or not teks_ocr.strip():
        return HasilResolver(field=kosong, penggunaan=None, dipakai=False)

    prompt = susun_prompt(teks_ocr, sudah_terbaca)
    try:
        penjaga.periksa(prompt, MAX_TOKEN_KELUAR)
        jawaban = klien.jawab(prompt, MAX_TOKEN_KELUAR)
    except Exception:  # noqa: BLE001 - kegagalan LLM tidak boleh menghentikan klaim
        return HasilResolver(field=kosong, penggunaan=None, dipakai=False)

    penjaga.catat(jawaban.penggunaan)

    try:
        data = ambil_json(jawaban.teks)
    except Exception:  # noqa: BLE001 - kegagalan LLM tidak boleh menghentikan klaim
        return HasilResolver(field=kosong, penggunaan=jawaban.penggunaan, dipakai=False)

    hasil: dict[str, str | int | None] = {}
    for k in FIELD:
        if sudah_terbaca.get(k):
            hasil[k] = sudah_terbaca[k]
            continue
        hasil[k] = _tahun(data.get(k)) if k == "tahun" else (teks_bersih(data.get(k)) or None)

    return HasilResolver(field=hasil, penggunaan=jawaban.penggunaan, dipakai=True)
