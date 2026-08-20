"""Menyusun narasi ringkas Bahasa Indonesia untuk adjuster.

Ini LLM step biasa, bukan agent: satu panggilan, bentuk keluarannya selalu sama, tidak ada
titik keputusan.

**LLM tidak menghitung apa pun di sini.** Tabel rincian biaya di layar adjuster disusun
langsung oleh kode dari database. LLM cuma menulis tiga sampai empat kalimat ringkasan.
Mengirim seluruh tabel lalu meminta LLM menyusunnya ulang jadi tabel memakan banyak token
untuk pekerjaan yang tidak butuh penalaran, sekaligus membuka peluang angkanya berubah.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.llm import Jawaban, KlienLLM, Penggunaan, PenjagaAnggaran

MAX_TOKEN_KELUAR = 350


@dataclass
class BahanLaporan:
    nama_kendaraan: str
    jumlah_part_diganti: int
    jumlah_part_diperbaiki: int
    part_termahal: list[str]
    total_biaya: Decimal
    harga_pasar_bekas: Decimal
    total_loss_ratio: float
    ambang_total_loss: float
    rekomendasi: str
    catatan_validitas: list[str]
    permintaan_foto_sebelumnya: list[str]
    # Bagian yang masuk lewat aturan, bukan karena terlihat di foto. Dipisah supaya narasi
    # tidak menyatakan seluruh bagian benar-benar terpantau kamera.
    jumlah_part_dari_aturan: int = 0


@dataclass
class HasilLaporan:
    narasi: str
    penggunaan: Penggunaan | None


def susun_prompt(b: BahanLaporan) -> str:
    bagian = [
        "Tulis ringkasan hasil penilaian klaim asuransi mobil untuk dibaca adjuster.",
        "",
        f"Kendaraan: {b.nama_kendaraan}",
        f"Part diganti: {b.jumlah_part_diganti}, part diperbaiki: {b.jumlah_part_diperbaiki}",
        (
            f"Dari yang diganti, {b.jumlah_part_dari_aturan} bagian tidak terlihat di foto dan "
            "dimasukkan lewat aturan, jadi masih perlu dipastikan saat pembongkaran"
            if b.jumlah_part_dari_aturan
            else "Semua bagian berasal dari yang terlihat di foto"
        ),
        f"Penyumbang biaya terbesar: {', '.join(b.part_termahal) or 'tidak ada'}",
        f"Total biaya Rp {b.total_biaya:,.0f} dari harga pasar Rp {b.harga_pasar_bekas:,.0f}",
        f"Rasio {b.total_loss_ratio:.1%}, ambang total loss {b.ambang_total_loss:.0%}",
        f"Rekomendasi: {b.rekomendasi}",
    ]

    if b.catatan_validitas:
        bagian += ["Catatan pemeriksaan: " + "; ".join(b.catatan_validitas)]
    if b.permintaan_foto_sebelumnya:
        bagian += ["Sempat meminta foto tambahan: " + "; ".join(b.permintaan_foto_sebelumnya)]

    bagian += [
        "",
        "Aturan menulis:",
        "- 3 sampai 4 kalimat saja, Bahasa Indonesia, tanpa daftar berpoin",
        "- jangan mengulang seluruh angka, cukup yang menentukan keputusan",
        "- jangan mengubah angka apa pun",
        "- sebutkan kalau ada pemeriksaan yang bermasalah, jangan cuma yang bagus",
        "- jawab teks biasa, tanpa judul dan tanpa pembuka",
    ]
    return "\n".join(bagian)


def narasi_cadangan(b: BahanLaporan) -> str:
    """Narasi yang disusun kode, dipakai kalau LLM tidak bisa dipanggil.

    Adjuster tetap mendapat ringkasan yang bisa dibaca meski kuota LLM habis atau semua
    penyedia sedang bermasalah. Kalimatnya memang kaku, tapi angkanya benar, dan layar
    adjuster tidak pernah kosong hanya karena satu layanan pihak ketiga sedang mati.
    """
    kalimat = [
        (
            f"{b.nama_kendaraan} mengalami kerusakan pada {b.jumlah_part_diganti} bagian "
            f"yang perlu diganti dan {b.jumlah_part_diperbaiki} bagian yang masih bisa "
            f"diperbaiki."
        )
    ]
    if b.jumlah_part_dari_aturan:
        kalimat.append(
            f"Dari jumlah itu, {b.jumlah_part_dari_aturan} bagian tidak terlihat di foto dan "
            f"dimasukkan lewat aturan karena letaknya di balik bagian yang rusak, jadi perlu "
            f"dipastikan saat pembongkaran di bengkel."
        )
    kalimat.append(
        f"Total estimasi biaya Rp {b.total_biaya:,.0f}, atau {b.total_loss_ratio:.1%} dari "
        f"harga pasar kendaraan, dengan ambang total loss {b.ambang_total_loss:.0%}."
    )
    if b.rekomendasi == "total_loss":
        kalimat.append("Rasio melewati ambang, sehingga direkomendasikan sebagai total loss.")
    else:
        kalimat.append("Rasio masih di bawah ambang, sehingga direkomendasikan perbaikan.")
    if b.catatan_validitas:
        kalimat.append("Catatan pemeriksaan: " + "; ".join(b.catatan_validitas) + ".")
    return " ".join(kalimat)


def susun(klien: KlienLLM | None, bahan: BahanLaporan, penjaga: PenjagaAnggaran) -> HasilLaporan:
    """Susun narasi. Kalau LLM tidak tersedia atau gagal, pakai narasi susunan kode."""
    if klien is None:
        return HasilLaporan(narasi=narasi_cadangan(bahan), penggunaan=None)

    prompt = susun_prompt(bahan)
    try:
        penjaga.periksa(prompt, MAX_TOKEN_KELUAR)
        jawaban: Jawaban = klien.jawab(prompt, MAX_TOKEN_KELUAR)
    except Exception:  # noqa: BLE001 - kegagalan LLM tidak boleh menghentikan klaim
        return HasilLaporan(narasi=narasi_cadangan(bahan), penggunaan=None)

    penjaga.catat(jawaban.penggunaan)
    teks = jawaban.teks.strip()
    if not teks:
        return HasilLaporan(narasi=narasi_cadangan(bahan), penggunaan=jawaban.penggunaan)
    return HasilLaporan(narasi=teks, penggunaan=jawaban.penggunaan)
