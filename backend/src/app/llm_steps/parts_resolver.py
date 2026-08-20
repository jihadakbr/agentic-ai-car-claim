"""Mencari padanan sparepart yang tidak ada di katalog.

LLM step kondisional. Untuk klaim normal fungsi ini **tidak pernah dipanggil**, karena
seluruh bagian hasil deteksi biasanya sudah punya barisnya sendiri di katalog. Dia baru
jalan kalau model mendeteksi bagian yang katalog kendaraan itu tidak punya.

Yang dikirim ke LLM cuma daftar pendek kandidat hasil saringan database, maksimal sepuluh
baris, bukan seluruh katalog. Katalog satu kendaraan berisi dua puluhan baris dan seluruh
katalog ratusan, jadi mengirim semuanya boros tanpa menambah ketepatan.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.llm import KlienLLM, Penggunaan, PenjagaAnggaran, ambil_json, teks_bersih

MAX_TOKEN_KELUAR = 200
MAX_KANDIDAT = 10


@dataclass
class Kandidat:
    part_class: str
    nama_part: str


@dataclass
class HasilPadanan:
    part_class_asal: str
    padanan: str | None
    alasan: str
    penggunaan: Penggunaan | None


def susun_prompt(part_asal: str, kandidat: list[Kandidat]) -> str:
    baris = [f"- {k.part_class} ({k.nama_part})" for k in kandidat[:MAX_KANDIDAT]]
    return "\n".join([
        "Model deteksi menemukan bagian mobil bernama:",
        f"  {part_asal}",
        "",
        "Bagian itu tidak ada di katalog sparepart kendaraan ini. Kandidat terdekat:",
        *baris,
        "",
        "Pilih satu yang paling masuk akal sebagai padanannya, atau jawab null kalau",
        "tidak ada yang cocok. Lebih baik menjawab null daripada memaksakan padanan,",
        "karena padanan yang salah membuat biaya klaim ikut salah.",
        "",
        'Jawab JSON saja: {"padanan": string|null, "alasan": string}',
    ])


def cari(
    klien: KlienLLM | None,
    part_asal: str,
    kandidat: list[Kandidat],
    penjaga: PenjagaAnggaran,
) -> HasilPadanan:
    """Cari padanan. Tanpa kandidat atau tanpa klien, hasilnya None, bukan tebakan."""
    if not kandidat:
        return HasilPadanan(part_asal, None, "Tidak ada kandidat di katalog kendaraan ini", None)
    if klien is None:
        return HasilPadanan(part_asal, None, "Pencari padanan tidak tersedia", None)

    prompt = susun_prompt(part_asal, kandidat)
    try:
        penjaga.periksa(prompt, MAX_TOKEN_KELUAR)
        jawaban = klien.jawab(prompt, MAX_TOKEN_KELUAR)
    except Exception as e:  # noqa: BLE001 - kegagalan LLM tidak boleh menghentikan klaim
        return HasilPadanan(part_asal, None, f"Pencarian padanan gagal: {e}", None)

    penjaga.catat(jawaban.penggunaan)

    try:
        data = ambil_json(jawaban.teks)
    except Exception as e:  # noqa: BLE001 - kegagalan LLM tidak boleh menghentikan klaim
        return HasilPadanan(part_asal, None, f"Jawaban tidak terbaca: {e}", jawaban.penggunaan)

    padanan = teks_bersih(data.get("padanan"))
    alasan = teks_bersih(data.get("alasan"), "Tidak ada alasan yang diberikan")

    # Padanan yang tidak ada di daftar kandidat ditolak. LLM kadang mengarang nama bagian
    # yang terdengar masuk akal tapi tidak ada di katalog, dan itu langsung membuat
    # pencarian harganya gagal di langkah berikutnya.
    sah = {k.part_class for k in kandidat[:MAX_KANDIDAT]}
    if padanan and padanan not in sah:
        return HasilPadanan(
            part_asal, None,
            f"Padanan '{padanan}' tidak ada di daftar kandidat, jadi ditolak",
            jawaban.penggunaan,
        )

    return HasilPadanan(part_asal, padanan or None, alasan, jawaban.penggunaan)
