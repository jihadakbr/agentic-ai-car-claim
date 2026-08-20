"""Merangkai seluruh tahap jadi satu alur pemrosesan klaim.

Urutannya: pra-proses foto, baca STNK, cari kendaraan dan polis, deteksi, tumpuk mask,
enam cek validitas, hitung biaya, penilaian agent, susun narasi.

Dua aturan yang dipegang di sini dan tidak boleh dilanggar:

1. **Klaim yang gagal cek validitas tetap dihitung biayanya.** Adjuster butuh tahu nilai
   kerusakannya meski validitasnya bermasalah, misalnya kalau ternyata platnya cuma
   tertutup lumpur dan setelah dicek manual mobilnya memang benar.
2. **Tidak ada jalur yang menutup klaim tanpa keputusan manusia.** Fungsi ini berhenti
   setelah menghasilkan rekomendasi. Menerbitkan surat perintah kerja atau penawaran beli
   dikerjakan setelah adjuster menekan tombolnya.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal

from PIL import Image

from app.agents import claim_assessment as agent
from app.agents import harga_pasar as harga_pasar_modul
from app.agents.pencari_web import PencariWeb
from app.core.aturan import BAGIAN_BUKAN_KLAIM
from app.core.llm import KlienLLM, Penggunaan, PenjagaAnggaran
from app.llm_steps import report_generator
from app.pipeline import kelayakan_foto, overlay_visual, pra_proses
from app.pipeline.cost_engine import (
    AturanPerbaikan,
    BarisBiaya,
    Estimasi,
    Part,
    Tarif,
    hitung_biaya,
    susun_estimasi,
)
from app.pipeline.detektor import Detektor
from app.pipeline.overlay import (
    TemuanGabungan,
    bentuk_json,
    ke_temuan_biaya,
    ringkas_antar_foto,
    tumpuk,
)
from app.pipeline.validity import (
    HARD,
    Ambang,
    DataPolis,
    FotoKerusakan,
    HasilCek,
    HasilStnk,
    TemuanFoto,
    TemuanKlaim,
    TemuanRiwayat,
    jalankan_semua,
)

STATUS_MENUNGGU_FOTO = "menunggu_foto_tambahan"
STATUS_SIAP_REVIEW = "siap_review"

SUMBER_ATURAN = "aturan"
SUMBER_AGENT = "agent"


@dataclass
class PermintaanFoto:
    """Satu foto yang diminta ulang, beserta alasan khusus foto itu.

    `sumber` membedakan permintaan yang lahir dari aturan kode dan yang datang dari
    pertimbangan agent, mengikuti pembedaan yang sudah dipakai baris biaya.
    """

    permintaan: str
    alasan: str
    sumber: str


@dataclass
class MasukanKlaim:
    """Bahan mentah satu klaim. Foto sudah berupa objek gambar, bukan jalur berkas."""

    foto_kerusakan: list[Image.Image]
    nomor_polis: str
    stnk: HasilStnk
    polis: DataPolis
    nama_kendaraan: str
    harga_pasar_bekas: Decimal


@dataclass
class Referensi:
    """Data acuan dari database yang dibutuhkan sepanjang alur."""

    katalog: dict[str, Part]
    matriks: list[AturanPerbaikan]
    tarif: list[Tarif]
    ambang_total_loss: float
    own_risk: Decimal
    faktor_salvage: float
    ambang: Ambang = field(default_factory=Ambang)
    # Jumlah foto minimum sebagai bukti sebelum sebuah part boleh diganti.
    min_foto_bagian_diganti: int = 2
    # Ambang gerbang kelayakan foto. Di bawahnya, fotonya diminta ulang.
    ambang_keyakinan_foto: float = kelayakan_foto.AMBANG_KEYAKINAN
    ambang_ketajaman_foto: float = kelayakan_foto.AMBANG_KETAJAMAN


@dataclass
class HasilKlaim:
    status: str
    verdict_validitas: str
    cek: list[HasilCek]
    baris_biaya: list[BarisBiaya]
    estimasi: Estimasi
    penilaian: agent.HasilPenilaian | None
    harga_pasar: harga_pasar_modul.HargaPasar
    permintaan_foto: list[PermintaanFoto]
    narasi: str
    phash: list[str]
    part_tidak_ditemukan: list[str]
    penggunaan_token: list[Penggunaan] = field(default_factory=list)
    waktu_tahap: dict[str, float] = field(default_factory=dict)
    # Temuan dan gambar berlapis per foto. Dua-duanya sudah dihitung sepanjang alur, dan
    # dikembalikan supaya adjuster bisa memeriksa apakah model menandai bagian yang benar.
    temuan_per_foto: list[list[TemuanGabungan]] = field(default_factory=list)
    overlay: list[Image.Image] = field(default_factory=list)
    # Bentuk mask per foto, dipakai layar pratinjau yang menggambar overlaynya sendiri.
    bentuk: list[dict] = field(default_factory=list)


@contextmanager
def _ukur(catatan: dict[str, float], tahap: str) -> Iterator[None]:
    """Catat lama satu tahap dalam milidetik.

    Angkanya ditampilkan di layar surveyor supaya progres yang muncul memang hasil ukuran,
    bukan animasi yang jalan sendiri tanpa hubungan dengan pekerjaan di server.
    """
    mulai = time.perf_counter()
    try:
        yield
    finally:
        catatan[tahap] = round((time.perf_counter() - mulai) * 1000, 1)


def _sebut_bagian(baris: BarisBiaya) -> str:
    return f"{baris.nama_part} {baris.sisi}" if baris.sisi else baris.nama_part


def permintaan_dari_aturan(
    baris: list[BarisBiaya],
    jumlah_foto: dict[tuple[str, str | None], int],
    minimum: int,
) -> list[PermintaanFoto]:
    """Minta foto ulang untuk bagian yang akan diganti tapi buktinya cuma satu foto.

    Mengganti part adalah baris termahal di estimasi, dan satu foto tidak cukup jadi dasar
    keputusan sebesar itu: sudut yang tidak menguntungkan bisa membuat lecet terlihat seperti
    penyok. Bagian yang cuma diperbaiki tidak diminta ulang, karena selisih biayanya kecil
    dan menahan klaim untuk itu lebih merugikan daripada salahnya.

    Bagian yang dimasukkan aturan karena tertutup bodi juga dilewati. Radiator dan airbag
    tidak pernah muncul di foto mana pun, jadi memintanya berarti menahan klaim menunggu
    foto yang mustahil diambil.

    Aturannya di kode, bukan di agent, supaya jalur ini tetap ada tanpa kunci LLM dan
    hasilnya bisa diulang persis saat diuji maupun didemokan.
    """
    hasil: list[PermintaanFoto] = []
    sudah: set[tuple[str, str | None]] = set()

    for b in baris:
        kunci = (b.part_class, b.sisi)
        if not b.ganti_part or b.sumber != "deteksi" or kunci in sudah:
            continue
        terlihat = jumlah_foto.get(kunci, 1)
        if terlihat >= minimum:
            continue
        sudah.add(kunci)
        bagian = _sebut_bagian(b)
        hasil.append(
            PermintaanFoto(
                permintaan=f"Foto {bagian} dari sudut berbeda",
                alasan=(
                    f"{bagian} akan diganti, tapi cuma terlihat di {terlihat} foto. "
                    f"Penggantian part butuh minimal {minimum} foto sebagai bukti"
                ),
                sumber=SUMBER_ATURAN,
            )
        )
    return hasil


def permintaan_dari_foto_ganda(cek: list[HasilCek]) -> list[PermintaanFoto]:
    """Minta foto baru kalau ada foto yang identik dengan foto klaim lain.

    Kalimatnya disusun di kode, bukan diserahkan ke agent. Agent sempat membalik arahnya,
    menulis seolah klaim pembanding yang ditandai, padahal yang ditandai klaim ini. Kalimat
    yang salah arah terbaca seperti menuduh klaim orang lain, dan itu tampil di layar
    surveyor.

    Yang diminta bukan sudut tertentu, melainkan foto yang keasliannya bisa dipastikan.
    Foto yang terbukti dipakai ulang tidak jadi benar hanya karena ditambah satu sudut.
    """
    c2 = next((c for c in cek if c.kode == "C2"), None)
    if c2 is None or c2.tingkat != HARD:
        return []

    lain = sorted({k["klaim_lain"] for k in c2.detail.get("kembar", []) if k["jarak"] == 0})
    sebut = f"klaim {', '.join(lain)}" if lain else "klaim lain"
    return [
        PermintaanFoto(
            permintaan=(
                f"Foto klaim ini ditandai identik dengan foto {sebut}, sehingga perlu "
                "verifikasi ulang untuk memastikan keaslian dan keunikan gambar."
            ),
            alasan="",
            sumber=SUMBER_ATURAN,
        )
    ]


def _gabung_permintaan(
    aturan: list[PermintaanFoto], dari_agent: list[agent.PermintaanAgent]
) -> list[PermintaanFoto]:
    """Tambahkan permintaan agent di belakang, buang yang menyebut bagian yang sudah diminta.

    Pencocokannya lewat kata, bukan kelas, karena agent menulis kalimat bebas. Kasar tapi
    memadai: yang dicegah cuma dua baris yang menyuruh memotret bagian yang sama.
    """
    hasil = list(aturan)
    sudah = {k.lower() for p in aturan for k in p.permintaan.split() if len(k) > 4}

    for p in dari_agent:
        kata = {k.lower() for k in p.foto.split() if len(k) > 4}
        if kata & sudah:
            continue
        hasil.append(
            PermintaanFoto(permintaan=p.foto, alasan=p.alasan, sumber=SUMBER_AGENT)
        )
        sudah |= kata
    return hasil


def _ringkas_untuk_agent(
    baris: list[BarisBiaya], jumlah_foto: dict[tuple[str, str | None], int]
) -> list[agent.RingkasanTemuan]:
    """Ringkas jadi satu baris per bagian sebelum masuk prompt.

    Ini penghematan token terbesar kedua setelah tidak pernah mengirim gambar.
    """
    return [
        agent.RingkasanTemuan(
            part_class=b.part_class,
            sisi=b.sisi,
            damage_class=b.damage_class or "",
            rasio_luas=b.rasio_luas,
            operasi=b.operasi,
            jumlah_foto=jumlah_foto.get((b.part_class, b.sisi), 1),
            sumber=b.sumber,
        )
        for b in baris
    ]


def _bahan_laporan(
    masukan: MasukanKlaim,
    baris: list[BarisBiaya],
    est: Estimasi,
    cek: list[HasilCek],
    permintaan_foto: list[str],
) -> report_generator.BahanLaporan:
    termahal = sorted(baris, key=lambda b: b.harga_part + b.biaya_jasa, reverse=True)[:3]
    return report_generator.BahanLaporan(
        nama_kendaraan=masukan.nama_kendaraan,
        jumlah_part_diganti=sum(1 for b in baris if b.ganti_part),
        jumlah_part_diperbaiki=sum(1 for b in baris if not b.ganti_part),
        jumlah_part_dari_aturan=sum(1 for b in baris if b.sumber == "aturan"),
        part_termahal=[b.nama_part for b in termahal],
        total_biaya=est.total_biaya,
        harga_pasar_bekas=est.harga_pasar_bekas,
        total_loss_ratio=est.total_loss_ratio,
        ambang_total_loss=est.ambang_total_loss,
        rekomendasi=est.rekomendasi,
        catatan_validitas=[f"{c.kode} {c.alasan}" for c in cek if not c.lolos],
        permintaan_foto_sebelumnya=permintaan_foto,
    )


def tentukan_harga_pasar(
    masukan: MasukanKlaim,
    cari_di_katalog,
    pencari: PencariWeb | None,
    klien_llm: KlienLLM | None,
    anggaran: PenjagaAnggaran,
) -> harga_pasar_modul.HargaPasar:
    """Tentukan harga pasar bekas beserta asalnya, sebelum rasio total loss dihitung.

    Urutannya: katalog menurut kendaraan di STNK, lalu katalog menurut kendaraan di polis,
    baru pencarian internet. Langkah kedua bukan basa-basi. Tipe kendaraan di STNK berupa
    kode seperti `F601RM GMMFJJ`, dan salah baca satu huruf saja membuat pencarian katalog
    meleset. Tanpa langkah itu, salah baca OCR langsung memicu pencarian internet dan
    menghasilkan harga mobil yang salah.
    """
    stnk = masukan.stnk
    if stnk.merk and stnk.tipe:
        harga = cari_di_katalog(stnk.merk, stnk.tipe, stnk.tahun)
        if harga:
            return harga_pasar_modul.dari_katalog(harga)

    if masukan.harga_pasar_bekas:
        return harga_pasar_modul.dari_katalog(
            masukan.harga_pasar_bekas,
            sumber=harga_pasar_modul.SUMBER_POLIS,
            keterangan=(
                "Kendaraan di STNK tidak ketemu di katalog harga, jadi dipakai harga "
                "kendaraan yang tercatat di polis"
            ),
        )

    kendaraan = harga_pasar_modul.nama_kendaraan(
        stnk.merk or "", stnk.tipe or "", stnk.tahun, masukan.nama_kendaraan
    )
    if pencari is None or klien_llm is None:
        return harga_pasar_modul.tidak_diketahui(
            f"Harga {kendaraan or 'kendaraan ini'} tidak ada di database, dan pencarian "
            "tidak tersedia. Harga harus diisi manual sebelum klaim bisa diputuskan."
        )

    return harga_pasar_modul.cari(
        stnk.merk or "", stnk.tipe or "", stnk.tahun, pencari, klien_llm, anggaran,
        nama_pasar=masukan.nama_kendaraan,
    )


def proses(
    masukan: MasukanKlaim,
    referensi: Referensi,
    detektor: Detektor,
    phash_klaim_lain: dict[str, str],
    klien_llm: KlienLLM | None = None,
    penjaga: PenjagaAnggaran | None = None,
    ambil_konteks=None,
    pencari: PencariWeb | None = None,
    cari_di_katalog=None,
    foto_sudah_diperiksa: int = 0,
    riwayat_polis: list[TemuanRiwayat] | None = None,
) -> HasilKlaim:
    """Jalankan satu klaim dari foto sampai rekomendasi."""
    anggaran = penjaga or PenjagaAnggaran()
    penggunaan: list[Penggunaan] = []
    waktu: dict[str, float] = {}

    with _ukur(waktu, "pra_proses"):
        siap = [pra_proses.siapkan(f) for f in masukan.foto_kerusakan]

    per_foto = []
    gambar_overlay: list[Image.Image] = []
    bentuk_overlay: list[dict] = []
    foto_cek: list[FotoKerusakan] = []
    with _ukur(waktu, "deteksi"):
        # Seluruh foto satu klaim dijalankan sekali panggil. Di Hugging Face ZeroGPU biaya
        # tetap pengalokasian GPU dibayar tiap panggilan, jadi memanggilnya per foto membayar
        # biaya itu berulang untuk pekerjaan yang sama.
        semua = detektor.deteksi_banyak([s.gambar for s in siap])
        for i, (s, hasil) in enumerate(zip(siap, semua, strict=True)):
            gabung = tumpuk(
                hasil.part,
                hasil.damage,
                ambang_irisan=0.30,
                bagian_diabaikan=frozenset(BAGIAN_BUKAN_KLAIM),
            )
            per_foto.append(gabung)
            gambar_overlay.append(
                overlay_visual.gambar(
                    s.gambar, hasil.part, hasil.damage, frozenset(BAGIAN_BUKAN_KLAIM),
                    contoh=type(detektor).__name__ == "DetektorContoh",
                )
            )
            bentuk_overlay.append({
                "part": bentuk_json(hasil.part),
                "damage": bentuk_json(hasil.damage),
            })
            foto_cek.append(
                FotoKerusakan(
                    id=f"foto-{i}",
                    phash=s.phash,
                    confidence_kendaraan=hasil.confidence_kendaraan,
                    plat_terbaca=masukan.stnk.nomor_polisi,
                    temuan=[
                        TemuanFoto(t.part_class, t.damage_class, t.confidence_damage, t.sisi)
                        for t in gabung
                    ],
                )
            )

        ringkas, jumlah_foto = ringkas_antar_foto(per_foto)

    # Kelayakan foto diperiksa sebelum penilaian agent, supaya agent sudah tahu foto mana
    # yang lemah saat menyusun permintaannya.
    #
    # Foto yang kelayakannya sudah pernah dinilai di putaran sebelumnya dilewati. Tanpa itu,
    # foto buram yang sudah dijawab surveyor dengan foto pengganti tetap ditandai tiap
    # penilaian ulang, dan klaimnya tidak akan pernah keluar dari status menunggu foto.
    foto_bermasalah = kelayakan_foto.periksa(
        [
            kelayakan_foto.FotoDinilai(
                urutan=i,
                keyakinan_kendaraan=f.confidence_kendaraan,
                ketajaman=s.ketajaman,
            )
            for i, (f, s) in enumerate(zip(foto_cek, siap, strict=True))
            if i >= foto_sudah_diperiksa
        ],
        ambang_ketajaman=referensi.ambang_ketajaman_foto,
        ambang_keyakinan=referensi.ambang_keyakinan_foto,
    )

    with _ukur(waktu, "validitas"):
        # C7 memakai temuan yang sudah digabung antar foto, bukan per foto, karena di situlah
        # rasio luas tiap bagian sudah dipilih dari sudut yang paling jelas.
        cek, verdict = jalankan_semua(
            foto_cek,
            masukan.stnk,
            masukan.polis,
            phash_klaim_lain,
            referensi.ambang,
            temuan_klaim=[
                TemuanKlaim(t.part_class, t.sisi, t.damage_class, t.rasio_luas)
                for t in ringkas
            ],
            riwayat_polis=riwayat_polis or [],
            foto_belum_diperiksa=foto_cek[foto_sudah_diperiksa:],
        )

    # Harga pasar bekas dicari lebih dulu, karena dia penyebut rasio total loss. Kalau
    # dicari setelah rasio dihitung, keputusannya sudah terlanjur diambil di atas angka
    # yang belum ada.
    with _ukur(waktu, "harga_pasar"):
        harga = tentukan_harga_pasar(
            masukan,
            cari_di_katalog or (lambda *_: None),
            pencari,
            klien_llm,
            anggaran,
        )
        penggunaan += harga.penggunaan

    # Biaya tetap dihitung meski validitasnya gagal. Adjuster yang menerima klaim bermasalah
    # tetap butuh tahu nilai kerusakannya.
    with _ukur(waktu, "biaya"):
        baris, tidak_ketemu = hitung_biaya(
            ke_temuan_biaya(ringkas, jumlah_foto),
            referensi.katalog,
            referensi.matriks,
            referensi.tarif,
        )
        est = susun_estimasi(
            baris,
            harga_pasar_bekas=harga.nilai,
            ambang_total_loss=referensi.ambang_total_loss,
            own_risk=referensi.own_risk,
            faktor_salvage=referensi.faktor_salvage,
            part_tidak_ditemukan=tidak_ketemu,
        )

    penilaian = None
    if klien_llm is not None and baris:
        with _ukur(waktu, "penilaian_agent"):
            try:
                penilaian = agent.nilai(
                    klien_llm,
                    _ringkas_untuk_agent(baris, jumlah_foto),
                    [
                        agent.RingkasanCek(c.kode, c.nama, c.lolos, c.tingkat, c.alasan)
                        for c in cek
                    ],
                    agent.RingkasanBiaya(
                        total_part=est.total_part,
                        total_jasa=est.total_jasa,
                        total_biaya=est.total_biaya,
                        harga_pasar_bekas=est.harga_pasar_bekas,
                        total_loss_ratio=est.total_loss_ratio,
                        ambang_total_loss=est.ambang_total_loss,
                        rekomendasi_mesin=est.rekomendasi,
                    ),
                    anggaran,
                    ambil_konteks=ambil_konteks,
                    catatan_foto=kelayakan_foto.ringkas_untuk_agent(
                        foto_bermasalah, len(foto_cek)
                    ),
                )
            except Exception:  # noqa: BLE001 - kegagalan LLM tidak boleh menghentikan klaim
                # Kuota habis atau penyedia mati membuat penilaian agent hilang, tapi biaya
                # dan hasil pemeriksaan sudah selesai dihitung tanpa LLM sama sekali, jadi
                # adjuster tetap punya bahan lengkap untuk memutuskan.
                penilaian = None
        if penilaian is not None:
            penggunaan += penilaian.penggunaan

    # Aturan lebih dulu, agent menyusul. Urutan ini disengaja: permintaan yang lahir dari
    # aturan selalu ada dan selalu sama, sedangkan agent bisa mati karena kuota habis.
    dari_aturan = [
        PermintaanFoto(m.permintaan, m.alasan, SUMBER_ATURAN) for m in foto_bermasalah
    ]
    dari_aturan += permintaan_dari_aturan(
        baris, jumlah_foto, referensi.min_foto_bagian_diganti
    )
    foto_ganda = permintaan_dari_foto_ganda(cek)
    dari_aturan += foto_ganda
    # Foto yang tidak terpakai diganti, bukan ditambah sudut baru. Foto yang dipakai ulang
    # dan foto yang buram sudah punya permintaan sendiri dari aturan, jadi usulan agent di
    # atasnya cuma mengulang hal yang sama dengan kalimat yang berbeda.
    ada_foto_diulang = bool(foto_ganda or foto_bermasalah)
    usul_agent = (
        [] if ada_foto_diulang else (penilaian.permintaan_foto if penilaian else [])
    )
    permintaan = _gabung_permintaan(dari_aturan, usul_agent)
    status = STATUS_MENUNGGU_FOTO if permintaan else STATUS_SIAP_REVIEW

    # Narasi tidak disusun untuk klaim yang masih menunggu foto tambahan, karena penilaiannya
    # akan diulang setelah fotonya masuk dan narasi yang sekarang langsung tidak berlaku.
    narasi = ""
    if status == STATUS_SIAP_REVIEW:
        with _ukur(waktu, "narasi"):
            laporan = report_generator.susun(
                klien_llm, _bahan_laporan(masukan, baris, est, cek, permintaan), anggaran
            )
        narasi = laporan.narasi
        if laporan.penggunaan:
            penggunaan.append(laporan.penggunaan)

    return HasilKlaim(
        status=status,
        verdict_validitas=verdict,
        cek=cek,
        baris_biaya=baris,
        estimasi=est,
        penilaian=penilaian,
        harga_pasar=harga,
        permintaan_foto=permintaan,
        narasi=narasi,
        phash=[s.phash for s in siap],
        part_tidak_ditemukan=tidak_ketemu,
        penggunaan_token=penggunaan,
        waktu_tahap=waktu,
        temuan_per_foto=per_foto,
        overlay=gambar_overlay,
        bentuk=bentuk_overlay,
    )
