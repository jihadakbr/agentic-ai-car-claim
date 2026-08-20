"""Claim assessment agent, satu-satunya komponen yang benar-benar agentic di sistem ini.

Bedanya dengan LLM step biasa ada di titik keputusan. Report generator selalu mengerjakan
hal yang sama: baca hasil, tulis narasi, selesai. Agent ini bisa berhenti di tengah dan
meminta sesuatu, dan untuk dua klaim berbeda jalurnya bisa berbeda.

Dua tahap, tahap keduanya kondisional:

- **Pass 1 selalu jalan.** Agent menilai dari ringkasan deteksi, hasil pemeriksaan validitas, dan
  hitungan biaya, sambil menandai sendiri apakah buktinya kurang atau kasusnya di batas.
- **Pass 2 cuma jalan kalau pass 1 menandai kasusnya di batas.** Baru di situ panduan
  underwriting dan riwayat klaim serupa ditarik dari database.

Kalau pass 1 tidak menandai apa pun, pass 2 dilewati sepenuhnya. Untuk klaim normal,
agent ini cuma menghabiskan satu panggilan LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.core.llm import (
    KlienLLM,
    Penggunaan,
    PenjagaAnggaran,
    ambil_json,
    teks_bersih,
)
from app.pipeline.cost_engine import sebaran

MAX_TOKEN_KELUAR = 400

# Selisih rasio terhadap ambang yang masih dianggap "di batas". Klaim dengan rasio 78.2%
# terhadap ambang 75% cuma berjarak 3.2 poin, dan satu part yang salah nilai bisa
# membalikkan keputusannya. Kasus seperti itu layak ditimbang lebih dalam.
JARAK_BATAS = 0.05


@dataclass
class RingkasanTemuan:
    """Satu baris ringkasan per bagian. Sengaja sudah diringkas sebelum masuk prompt.

    Yang dikirim ke LLM satu baris per bagian, bukan puluhan baris hasil mentah per foto.
    Ini penghematan token terbesar kedua setelah tidak mengirim gambar sama sekali.
    """

    part_class: str
    sisi: str | None
    damage_class: str
    rasio_luas: float
    operasi: str
    jumlah_foto: int
    sumber: str


@dataclass
class RingkasanCek:
    kode: str
    nama: str
    lolos: bool
    tingkat: str | None
    alasan: str


@dataclass
class RingkasanBiaya:
    total_part: Decimal
    total_jasa: Decimal
    total_biaya: Decimal
    harga_pasar_bekas: Decimal
    total_loss_ratio: float
    ambang_total_loss: float
    rekomendasi_mesin: str


@dataclass
class KonteksTambahan:
    """Bahan yang cuma ditarik kalau agent memintanya di pass 1."""

    panduan_underwriting: list[str] = field(default_factory=list)
    klaim_serupa: list[str] = field(default_factory=list)


@dataclass
class PermintaanAgent:
    """Satu foto yang diminta agent, beserta alasan khusus foto itu."""

    foto: str
    alasan: str


@dataclass
class HasilPenilaian:
    cukup_bukti: bool
    rekomendasi: str
    alasan: str
    permintaan_foto: list[PermintaanAgent] = field(default_factory=list)
    perlu_konteks_tambahan: bool = False
    jumlah_pass: int = 1
    penggunaan: list[Penggunaan] = field(default_factory=list)


def _baris_temuan(t: RingkasanTemuan) -> str:
    sisi = f" sisi {t.sisi}" if t.sisi else ""
    if t.sumber != "deteksi":
        # Bagian ini tertutup bodi dan tidak akan pernah muncul di foto. Kalau tidak
        # dinyatakan tegas, agent meminta foto radiator atau airbag dan klaim macet
        # menunggu foto yang mustahil diambil.
        return (
            f"- {t.part_class}{sisi}: dimasukkan lewat aturan karena tertutup bodi, "
            f"operasi {t.operasi}. Tidak terlihat dari luar, foto tambahan tidak mungkin"
        )
    # Sebaran dikirim sebagai kata, bukan persen. Rasio luas dihitung di bidang foto dan
    # ikut berubah mengikuti sudut pemotretan, jadi angkanya tidak layak jadi bahan nalar.
    return (
        f"- {t.part_class}{sisi}: {t.damage_class}, kerusakan {sebaran(t.rasio_luas)}, "
        f"terlihat di {t.jumlah_foto} foto, operasi {t.operasi}"
    )


def _baris_cek(c: RingkasanCek) -> str:
    if c.lolos:
        return f"- {c.kode} {c.nama}: lolos"
    return f"- {c.kode} {c.nama}: {c.tingkat or 'gagal'}, {c.alasan}"


def _blok_biaya(b: RingkasanBiaya) -> str:
    return (
        f"Total biaya Rp {b.total_biaya:,.0f} "
        f"(part Rp {b.total_part:,.0f} + jasa Rp {b.total_jasa:,.0f})\n"
        f"Harga pasar kendaraan bekas Rp {b.harga_pasar_bekas:,.0f}\n"
        f"Rasio {b.total_loss_ratio:.1%} terhadap ambang total loss {b.ambang_total_loss:.0%}\n"
        f"Hitungan mesin menyimpulkan: {b.rekomendasi_mesin}"
    )


def dekat_batas(biaya: RingkasanBiaya) -> bool:
    """Apakah rasionya cukup dekat dengan ambang sehingga layak ditimbang lebih dalam."""
    return abs(biaya.total_loss_ratio - biaya.ambang_total_loss) <= JARAK_BATAS


def susun_prompt(
    temuan: list[RingkasanTemuan],
    cek: list[RingkasanCek],
    biaya: RingkasanBiaya,
    konteks: KonteksTambahan | None = None,
    catatan_foto: list[str] | None = None,
) -> str:
    """Susun prompt. Sengaja pendek, tanpa contoh panjang, tanpa riwayat percakapan."""
    bagian = [
        "Kamu adjuster asuransi mobil di Indonesia. Nilai kelayakan klaim berikut.",
        "",
        "KERUSAKAN TERDETEKSI:",
        *[_baris_temuan(t) for t in temuan],
        "",
        "HASIL PEMERIKSAAN VALIDITAS:",
        *[_baris_cek(c) for c in cek],
        "",
        "PERHITUNGAN BIAYA:",
        _blok_biaya(biaya),
    ]

    # Foto bermasalah sudah ditentukan aturan, bukan oleh agent. Yang diminta dari agent
    # cuma menyebut bagian mobil mana yang harus terlihat jelas di foto ulangnya.
    if catatan_foto:
        bagian += [
            "",
            "FOTO YANG SUDAH DITANDAI PERLU DIULANG:",
            *[f"- {c}" for c in catatan_foto],
        ]

    if konteks and (konteks.panduan_underwriting or konteks.klaim_serupa):
        bagian += ["", "KONTEKS TAMBAHAN:"]
        bagian += [f"- {p}" for p in konteks.panduan_underwriting]
        bagian += [f"- {k}" for k in konteks.klaim_serupa]

    bagian += [
        "",
        "Angka biaya sudah dihitung mesin dan tidak boleh kamu ubah.",
        "Tugasmu menilai apakah buktinya cukup untuk mengambil keputusan.",
        "",
        "ATURAN MEMINTA FOTO TAMBAHAN:",
        "Bawaannya JANGAN meminta foto. Klaim satu foto adalah kiriman yang sah, dan",
        "bagian yang cuma terlihat di satu foto itu wajar, bukan alasan meminta foto.",
        "Foto yang memang tidak layak dibaca sudah ditandai sistem di daftar di atas.",
        "Minta foto hanya kalau ada alasan yang bisa kamu sebut dari data di atas, misalnya",
        "fotonya sudah ditandai perlu diulang, atau hasil pemeriksaan menyebut bagian",
        "tertentu meragukan.",
        "Jangan pernah meminta foto bagian yang ditandai tertutup bodi. Bagian itu baru",
        "bisa dipastikan saat pembongkaran di bengkel, bukan dari foto.",
        "",
        'Isi "foto" harus berupa perintah untuk surveyor yang diawali kata kerja, misalnya',
        '"Foto fender kanan dari jarak 2 meter". Jangan menulis nama field seperti',
        '"fender_sisi_kanan". Tiap permintaan punya alasannya sendiri yang menyebut',
        "bagian itu.",
        "Surveyor mengirim ulang seluruh fotonya sekaligus, beserta satu lembar STNK.",
        "Jadi jangan meminta beberapa sisi STNK sekaligus, dan jangan menyusun permintaan",
        "yang mengandaikan foto lama masih terpakai. Sebutkan apa yang harus terlihat jelas",
        "di kiriman berikutnya.",
        "",
        "Jawab JSON saja dengan bentuk:",
        '{"cukup_bukti": bool, "perlu_konteks_tambahan": bool,',
        ' "permintaan_foto": [{"foto": string, "alasan": string}],',
        ' "rekomendasi": "repair"|"total_loss"|"tolak", "alasan": string}',
    ]
    return "\n".join(bagian)


ALASAN_AGENT_KOSONG = "Agent menilai bukti untuk bagian ini belum cukup"


def _baca_permintaan(nilai) -> list[PermintaanAgent]:
    """Baca permintaan foto, terima bentuk objek maupun daftar teks biasa.

    Model gratis sering tidak patuh bentuk yang diminta. Menolak jawabannya berarti membuang
    penilaian yang bagian lainnya masih berguna, jadi daftar teks polos tetap diterima dan
    alasannya diisi kalimat umum, bukan dicap alasan tingkat klaim yang tidak ada hubungannya
    dengan foto itu.
    """
    if not isinstance(nilai, list):
        return []

    hasil = []
    for isi in nilai:
        if isinstance(isi, dict):
            foto = teks_bersih(isi.get("foto") or isi.get("permintaan"), "")
            alasan = teks_bersih(isi.get("alasan"), ALASAN_AGENT_KOSONG)
        else:
            foto = teks_bersih(isi, "")
            alasan = ALASAN_AGENT_KOSONG
        if foto:
            hasil.append(PermintaanAgent(foto=foto, alasan=alasan))
    return hasil


def _baca_jawaban(teks: str, rekomendasi_mesin: str) -> dict:
    data = ambil_json(teks)
    return {
        "cukup_bukti": bool(data.get("cukup_bukti", True)),
        "permintaan_foto": _baca_permintaan(data.get("permintaan_foto")),
        "perlu_konteks_tambahan": bool(data.get("perlu_konteks_tambahan", False)),
        "rekomendasi": teks_bersih(data.get("rekomendasi"), rekomendasi_mesin),
        "alasan": teks_bersih(data.get("alasan"), "Tidak ada alasan yang diberikan"),
    }


def nilai(
    klien: KlienLLM,
    temuan: list[RingkasanTemuan],
    cek: list[RingkasanCek],
    biaya: RingkasanBiaya,
    penjaga: PenjagaAnggaran,
    ambil_konteks=None,
    catatan_foto: list[str] | None = None,
) -> HasilPenilaian:
    """Jalankan penilaian. `ambil_konteks` dipanggil hanya kalau pass 2 benar-benar terjadi.

    Bentuknya fungsi, bukan data yang langsung dikirim, supaya penarikan panduan underwriting
    dan riwayat klaim serupa dari database tidak pernah terjadi untuk klaim yang tidak
    membutuhkannya.
    """
    penggunaan: list[Penggunaan] = []

    prompt = susun_prompt(temuan, cek, biaya, catatan_foto=catatan_foto)
    penjaga.periksa(prompt, MAX_TOKEN_KELUAR)
    jawaban = klien.jawab(prompt, MAX_TOKEN_KELUAR)
    penjaga.catat(jawaban.penggunaan)
    penggunaan.append(jawaban.penggunaan)

    hasil = _baca_jawaban(jawaban.teks, biaya.rekomendasi_mesin)

    # Bukti kurang berarti berhenti di sini. Menarik konteks tambahan untuk klaim yang
    # fotonya saja belum lengkap cuma membuang token, karena penilaiannya akan diulang
    # setelah foto tambahannya masuk.
    if not hasil["cukup_bukti"] or hasil["permintaan_foto"]:
        return HasilPenilaian(
            cukup_bukti=False,
            rekomendasi=hasil["rekomendasi"],
            alasan=hasil["alasan"],
            permintaan_foto=hasil["permintaan_foto"],
            perlu_konteks_tambahan=hasil["perlu_konteks_tambahan"],
            jumlah_pass=1,
            penggunaan=penggunaan,
        )

    perlu_pass_dua = hasil["perlu_konteks_tambahan"] and ambil_konteks is not None
    if not perlu_pass_dua:
        return HasilPenilaian(
            cukup_bukti=True,
            rekomendasi=hasil["rekomendasi"],
            alasan=hasil["alasan"],
            perlu_konteks_tambahan=hasil["perlu_konteks_tambahan"],
            jumlah_pass=1,
            penggunaan=penggunaan,
        )

    konteks = ambil_konteks()
    prompt2 = susun_prompt(temuan, cek, biaya, konteks, catatan_foto)
    penjaga.periksa(prompt2, MAX_TOKEN_KELUAR)
    jawaban2 = klien.jawab(prompt2, MAX_TOKEN_KELUAR)
    penjaga.catat(jawaban2.penggunaan)
    penggunaan.append(jawaban2.penggunaan)

    hasil2 = _baca_jawaban(jawaban2.teks, biaya.rekomendasi_mesin)
    return HasilPenilaian(
        cukup_bukti=hasil2["cukup_bukti"],
        rekomendasi=hasil2["rekomendasi"],
        alasan=hasil2["alasan"],
        permintaan_foto=hasil2["permintaan_foto"],
        perlu_konteks_tambahan=True,
        jumlah_pass=2,
        penggunaan=penggunaan,
    )
