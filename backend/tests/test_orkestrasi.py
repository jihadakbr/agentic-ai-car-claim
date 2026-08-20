"""Uji perakit alur klaim, dari foto sampai rekomendasi.

Memakai detektor contoh, bukan model sungguhan, supaya uji bisa jalan tanpa bobot model
ratusan megabita dan hasilnya bisa diulang persis. Yang diuji di sini bukan ketepatan
deteksi, melainkan apakah tahap-tahapnya dirangkai dengan urutan dan syarat yang benar.
"""

import json
from decimal import Decimal

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.llm import Jawaban, Penggunaan, PenjagaAnggaran, perkiraan_token
from app.db.models import Base
from app.db.repository import (
    ambil_config_float,
    ambil_config_rupiah,
    cari_kendaraan,
    muat_katalog,
    muat_matriks,
    muat_tarif,
)
from app.db.seed import isi_semua
from app.pipeline import pra_proses
from app.pipeline.detektor import DetektorContoh
from app.pipeline.orkestrasi import (
    STATUS_MENUNGGU_FOTO,
    STATUS_SIAP_REVIEW,
    MasukanKlaim,
    Referensi,
    proses,
)
from app.pipeline.validity import DataPolis, HasilStnk


class KlienTiruan:
    def __init__(self, jawaban: list[str]):
        self.nama = "tiruan"
        self.antrean = list(jawaban)
        self.prompt: list[str] = []

    def jawab(self, prompt: str, max_tokens: int) -> Jawaban:
        self.prompt.append(prompt)
        teks = self.antrean.pop(0) if self.antrean else "{}"
        return Jawaban(teks, Penggunaan("tiruan", "m", perkiraan_token(prompt), 40))


def jawaban_agent(**ubah) -> str:
    dasar = {
        "cukup_bukti": True,
        "permintaan_foto": [],
        "perlu_konteks_tambahan": False,
        "rekomendasi": "repair",
        "alasan": "Bukti cukup",
    }
    return json.dumps({**dasar, **ubah})


def foto_mobil(warna: int = 120, ukuran=(800, 600)) -> Image.Image:
    """Gambar bercorak. Detektor contoh menghasilkan mask dari ukurannya, bukan dari isinya.

    Coraknya tetap dibutuhkan: gambar polos tidak punya tepi sama sekali, sehingga gerbang
    kelayakan foto menganggapnya buram lalu meminta seluruh fotonya diulang.
    """
    img = Image.new("RGB", ukuran, (warna, warna, warna))
    d = ImageDraw.Draw(img)
    gelap = max(0, warna - 90)
    for i in range(0, ukuran[0], 24):
        d.line([(i, 0), (i, ukuran[1])], fill=(gelap, gelap, gelap), width=4)
    for j in range(0, ukuran[1], 24):
        d.line([(0, j), (ukuran[0], j)], fill=(gelap, gelap, gelap), width=4)
    return img


@pytest.fixture
def s() -> Session:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as sesi:
        isi_semua(sesi)
        sesi.commit()
        yield sesi


@pytest.fixture
def referensi(s) -> Referensi:
    kendaraan = cari_kendaraan(s, "TOYOTA", "F601RM GMMFJJ", 2013)
    return Referensi(
        katalog=muat_katalog(s, kendaraan.id),
        matriks=muat_matriks(s),
        tarif=muat_tarif(s),
        ambang_total_loss=ambil_config_float(s, "ambang_total_loss"),
        own_risk=ambil_config_rupiah(s, "own_risk"),
        faktor_salvage=ambil_config_float(s, "faktor_salvage"),
    )


@pytest.fixture
def masukan() -> MasukanKlaim:
    return MasukanKlaim(
        foto_kerusakan=[foto_mobil(100 + i * 20) for i in range(4)],
        nomor_polis="POL-2024-0037",
        stnk=HasilStnk(
            merk="TOYOTA", tipe="F601RM GMMFJJ", tahun=2013, nomor_polisi="B 1234 XYZ",
            nomor_rangka="MHKM1BA3JDK012345", nomor_mesin="1NRF012345",
            nama_pemilik="BUDI SANTOSO",
        ),
        polis=DataPolis("B 1234 XYZ", "MHKM1BA3JDK012345", "1NRF012345", "BUDI SANTOSO"),
        nama_kendaraan="Toyota Avanza 1.3 G 2013",
        harga_pasar_bekas=Decimal(95_000_000),
    )


def test_pra_proses_memperkecil_foto_besar():
    besar = Image.new("RGB", (4032, 3024), (90, 90, 90))
    hasil = pra_proses.siapkan(besar)
    assert max(hasil.gambar.size) == pra_proses.SISI_TERPANJANG
    assert hasil.lebar_asli == 4032


def test_pra_proses_membiarkan_foto_yang_sudah_kecil():
    kecil = Image.new("RGB", (640, 480), (90, 90, 90))
    assert pra_proses.siapkan(kecil).gambar.size == (640, 480)


def test_sidik_jari_bertahan_setelah_simpan_ulang(tmp_path):
    """Inti cek foto dipakai ulang: menyimpan ulang tidak mengubah sidik jarinya banyak."""
    asli = Image.new("RGB", (400, 300), (30, 30, 30))
    gambar = ImageDraw.Draw(asli)
    for x in range(400):
        gambar.line([(x, 0), (x, 300)], fill=(x % 200 + 40, 60, 120))
    gambar.ellipse([80, 60, 300, 240], fill=(220, 200, 60))
    gambar.rectangle([20, 20, 120, 90], fill=(20, 90, 200))

    berkas = tmp_path / "ulang.jpg"
    asli.save(berkas, quality=55)
    with Image.open(berkas) as dibuka:
        sesudah = pra_proses.sidik_jari(dibuka.convert("RGB"))

    sebelum = pra_proses.sidik_jari(asli)
    beda = (int(sebelum, 16) ^ int(sesudah, 16)).bit_count()
    assert beda <= 5


def test_detektor_contoh_menghasilkan_hasil_yang_sama_untuk_foto_sama():
    d = DetektorContoh()
    a = d.deteksi(foto_mobil())
    b = d.deteksi(foto_mobil())
    assert [m.kelas for m in a.part] == [m.kelas for m in b.part]
    assert a.part[0].luas == b.part[0].luas


def test_mask_detektor_contoh_bukan_persegi():
    """Model sungguhannya menghasilkan mask, jadi demo tidak boleh terlihat seperti kotak."""
    mask = DetektorContoh().deteksi(foto_mobil()).part[0].mask
    baris = [b.sum() for b in mask if b.any()]

    assert len(set(baris)) > 1, "tiap baris sama lebarnya, bentuknya masih persegi"


def test_alur_lengkap_menghasilkan_rekomendasi(masukan, referensi):
    klien = KlienTiruan([jawaban_agent(), "Kerusakan kap mesin, direkomendasikan perbaikan."])

    hasil = proses(masukan, referensi, DetektorContoh(), {}, klien_llm=klien)

    assert hasil.status == STATUS_SIAP_REVIEW
    assert hasil.verdict_validitas == "valid"
    assert len(hasil.cek) == 7
    assert hasil.baris_biaya
    assert hasil.estimasi.total_biaya > 0
    assert hasil.narasi.startswith("Kerusakan kap mesin")


def test_plat_nomor_tidak_pernah_jadi_baris_biaya(masukan, referensi):
    hasil = proses(masukan, referensi, DetektorContoh(), {}, klien_llm=KlienTiruan([]))
    assert all(b.part_class != "License-plate" for b in hasil.baris_biaya)


def test_klaim_normal_cuma_dua_panggilan_llm(masukan, referensi):
    """Janji hemat token diuji pada alur utuh, bukan cuma pada komponennya sendiri."""
    klien = KlienTiruan([jawaban_agent(), "Ringkasan."])
    penjaga = PenjagaAnggaran()

    proses(masukan, referensi, DetektorContoh(), {}, klien_llm=klien, penjaga=penjaga)

    assert len(klien.prompt) == 2
    assert len(penjaga.riwayat) == 2


def test_agent_minta_foto_menghentikan_alur_sebelum_narasi(masukan, referensi):
    """Narasi yang disusun sekarang langsung tidak berlaku setelah foto tambahan masuk."""
    klien = KlienTiruan([
        jawaban_agent(cukup_bukti=False, permintaan_foto=["foto sisi kanan dari 2 meter"])
    ])

    hasil = proses(masukan, referensi, DetektorContoh(), {}, klien_llm=klien)

    assert hasil.status == STATUS_MENUNGGU_FOTO
    assert [p.permintaan for p in hasil.permintaan_foto] == ["foto sisi kanan dari 2 meter"]
    assert [p.sumber for p in hasil.permintaan_foto] == ["agent"]
    assert hasil.narasi == ""
    assert len(klien.prompt) == 1


def test_klaim_tidak_valid_tetap_dihitung_biayanya(masukan, referensi):
    """Aturan yang tidak boleh dilanggar: validitas gagal bukan alasan berhenti menghitung."""
    masukan.stnk.nomor_rangka = "MHKM1BA3JDK099887"

    hasil = proses(masukan, referensi, DetektorContoh(), {}, klien_llm=KlienTiruan([]))

    assert hasil.verdict_validitas == "invalid"
    assert hasil.baris_biaya
    assert hasil.estimasi.total_biaya > 0


def test_foto_dipakai_ulang_terdeteksi_lewat_alur(masukan, referensi):
    siap = pra_proses.siapkan(masukan.foto_kerusakan[0])
    lain = {siap.phash: "KLM-2024-0118"}

    hasil = proses(masukan, referensi, DetektorContoh(), lain, klien_llm=KlienTiruan([]))

    c2 = next(c for c in hasil.cek if c.kode == "C2")
    assert c2.lolos is False
    assert "KLM-2024-0118" in c2.alasan
    assert hasil.verdict_validitas == "invalid"


def test_kerusakan_berat_jadi_total_loss(masukan, referensi):
    """Detektor contoh disetel merusak hampir seluruh bagian, biayanya harus melewati ambang."""
    detektor = DetektorContoh(kerusakan="Broken part", rasio_kerusakan=0.95)
    masukan.harga_pasar_bekas = Decimal(9_000_000)

    hasil = proses(masukan, referensi, detektor, {}, klien_llm=KlienTiruan([]))

    assert hasil.estimasi.rekomendasi == "total_loss"
    assert hasil.estimasi.harga_tawaran_salvage is not None


def test_benturan_depan_berat_mereproduksi_contoh_avanza(masukan, referensi):
    """Contoh acuan di dokumen harus keluar dari pipeline penuh, bukan cuma dari hitungan tangan.

    Angkanya dipakai saat presentasi, jadi perubahan harga part, jam standar, atau aturan
    bagian tersembunyi harus menggagalkan uji ini, bukan diam-diam menggeser totalnya.
    """
    masukan.harga_pasar_bekas = Decimal(95_000_000)
    hasil = proses(
        masukan,
        referensi,
        DetektorContoh(kerusakan="Dent", rasio_kerusakan=0.95),
        {},
        klien_llm=None,
    )

    est = hasil.estimasi
    assert est.total_part == Decimal(81_505_000)
    assert est.total_jasa == Decimal(14_595_000)
    assert est.total_biaya == Decimal(96_100_000)
    assert round(est.total_loss_ratio, 3) == 1.012
    assert est.rekomendasi == "total_loss"

    dari_deteksi = [b for b in hasil.baris_biaya if b.sumber == "deteksi"]
    dari_aturan = [b for b in hasil.baris_biaya if b.sumber == "aturan"]
    assert len(dari_deteksi) == 8
    assert len(dari_aturan) == 16
    assert all(b.ganti_part for b in hasil.baris_biaya)


def test_kerusakan_ringan_tidak_memunculkan_bagian_tersembunyi(masukan, referensi):
    """Radiator dan airbag cuma ikut kalau benturannya memang menembus bodi."""
    hasil = proses(
        masukan,
        referensi,
        DetektorContoh(kerusakan="Scratch", rasio_kerusakan=0.2),
        {},
        klien_llm=None,
    )
    assert [b.sumber for b in hasil.baris_biaya] == ["deteksi"]


def test_llm_mati_di_tengah_tidak_menggagalkan_klaim(masukan, referensi):
    """Penyedia LLM mati saat presentasi tidak boleh membuat klaim gagal diproses."""

    class KlienMati:
        def jawab(self, prompt, max_tokens):
            raise RuntimeError("penyedia sedang mati")

    hasil = proses(masukan, referensi, DetektorContoh(), {}, klien_llm=KlienMati())

    assert hasil.status == STATUS_SIAP_REVIEW
    assert hasil.penilaian is None
    assert hasil.estimasi.total_biaya > 0
    assert hasil.narasi
    assert hasil.cek


def test_tanpa_llm_alur_tetap_selesai(masukan, referensi):
    """Kuota habis tidak boleh membuat klaim gagal diproses sama sekali."""
    hasil = proses(masukan, referensi, DetektorContoh(), {}, klien_llm=None)

    assert hasil.status == STATUS_SIAP_REVIEW
    assert hasil.penilaian is None
    assert hasil.narasi
    assert hasil.estimasi.total_biaya > 0


def test_bagian_diganti_yang_cuma_satu_foto_diminta_ulang_tanpa_llm(masukan, referensi):
    """Jalur permintaan foto tidak boleh bergantung pada adanya kunci LLM.

    Kalau bergantung, jalur ini tidak bisa diuji, tidak bisa didemokan berulang, dan hilang
    di lingkungan yang tidak punya kunci.
    """
    masukan.foto_kerusakan = [foto_mobil(120)]

    hasil = proses(masukan, referensi, DetektorContoh(), {}, klien_llm=None)

    assert hasil.status == STATUS_MENUNGGU_FOTO
    assert hasil.penilaian is None
    assert hasil.permintaan_foto
    assert all(p.sumber == "aturan" for p in hasil.permintaan_foto)


def test_tiap_permintaan_menyebut_bagiannya_sendiri(masukan, referensi):
    """Bug sebelumnya mencap satu alasan tingkat klaim ke seluruh permintaan."""
    masukan.foto_kerusakan = [foto_mobil(120)]

    hasil = proses(masukan, referensi, DetektorContoh(), {}, klien_llm=None)

    alasan = [p.alasan for p in hasil.permintaan_foto]
    assert len(alasan) == len(set(alasan)), "tiap permintaan harus punya alasan sendiri"
    for p in hasil.permintaan_foto:
        bagian = p.permintaan.removeprefix("Foto ").removesuffix(" dari sudut berbeda")
        assert bagian in p.alasan


def test_bagian_yang_terlihat_di_banyak_foto_tidak_diminta_ulang(masukan, referensi):
    """Detektor contoh menandai bagian yang sama di tiap foto, jadi empat foto sudah cukup."""
    hasil = proses(masukan, referensi, DetektorContoh(), {}, klien_llm=None)

    assert hasil.status == STATUS_SIAP_REVIEW
    assert hasil.permintaan_foto == []


def test_bagian_tertutup_bodi_tidak_pernah_diminta_fotonya(masukan, referensi):
    """Radiator dan airbag tidak muncul di foto mana pun, memintanya membuat klaim macet."""
    masukan.foto_kerusakan = [foto_mobil(120)]

    hasil = proses(masukan, referensi, DetektorContoh(rasio_kerusakan=0.95), {}, klien_llm=None)

    tersembunyi = {b.nama_part for b in hasil.baris_biaya if b.sumber != "deteksi"}
    assert tersembunyi, "skenario ini harus memunculkan bagian tertutup bodi"
    for p in hasil.permintaan_foto:
        assert not any(nama in p.permintaan for nama in tersembunyi)


def test_bagian_yang_cuma_diperbaiki_tidak_diminta_ulang(masukan, referensi):
    """Selisih biaya perbaikan kecil, menahan klaim untuk itu lebih merugikan."""
    masukan.foto_kerusakan = [foto_mobil(120)]

    hasil = proses(
        masukan,
        referensi,
        DetektorContoh(kerusakan="Scratch", rasio_kerusakan=0.2),
        {},
        klien_llm=None,
    )

    assert not any(b.ganti_part for b in hasil.baris_biaya)
    assert hasil.status == STATUS_SIAP_REVIEW
    assert hasil.permintaan_foto == []


def test_permintaan_agent_yang_mengulang_bagian_dibuang(masukan, referensi):
    """Aturan sudah meminta Fender, agent tidak boleh menambah baris kedua untuk Fender."""
    masukan.foto_kerusakan = [foto_mobil(120)]
    klien = KlienTiruan([
        jawaban_agent(
            cukup_bukti=False,
            permintaan_foto=[
                {"foto": "Foto Fender depan kanan lagi", "alasan": "kurang jelas"},
                {"foto": "Foto bagasi dari belakang", "alasan": "belum ada sama sekali"},
            ],
        )
    ])

    hasil = proses(masukan, referensi, DetektorContoh(), {}, klien_llm=klien)

    dari_agent = [p.permintaan for p in hasil.permintaan_foto if p.sumber == "agent"]
    assert dari_agent == ["Foto bagasi dari belakang"]


def test_sidik_jari_tiap_foto_dikembalikan(masukan, referensi):
    """Nilai ini yang disimpan ke database untuk memeriksa klaim berikutnya."""
    hasil = proses(masukan, referensi, DetektorContoh(), {}, klien_llm=None)
    assert len(hasil.phash) == 4
    assert all(p for p in hasil.phash)


def test_hasil_sama_untuk_masukan_sama(masukan, referensi):
    def jalankan():
        h = proses(masukan, referensi, DetektorContoh(), {}, klien_llm=None)
        return (h.verdict_validitas, h.estimasi.total_biaya, h.estimasi.rekomendasi)

    assert len({jalankan() for _ in range(3)}) == 1


def test_permintaan_foto_ganda_menunjuk_klaim_pembanding_bukan_klaim_ini():
    """Kalimatnya harus menyebut klaim ini yang ditandai, bukan klaim pembandingnya.

    Sebelumnya kalimat ini disusun agent dan arahnya sempat terbalik, terbaca seolah klaim
    orang lain yang bermasalah. Kalimat itu tampil di layar surveyor.
    """
    from app.pipeline.orkestrasi import permintaan_dari_foto_ganda
    from app.pipeline.validity import HARD, SOFT, HasilCek

    cek = [
        HasilCek("C2", "Foto tidak dipakai ulang", False, HARD, "identik",
                 {"kembar": [{"foto": "f0", "klaim_lain": "KLM-2026-0001", "jarak": 0}]}),
    ]
    hasil = permintaan_dari_foto_ganda(cek)
    assert len(hasil) == 1
    assert "klaim ini ditandai identik" in hasil[0].permintaan
    assert "KLM-2026-0001" in hasil[0].permintaan
    assert hasil[0].sumber == "aturan"

    # Mirip saja belum cukup, itu sudah ditangani sebagai soft flag tanpa menahan klaim.
    cek[0] = HasilCek("C2", "Foto tidak dipakai ulang", False, SOFT, "mirip", {"kembar": []})
    assert permintaan_dari_foto_ganda(cek) == []

    cek[0] = HasilCek("C2", "Foto tidak dipakai ulang", True, None, "aman", {})
    assert permintaan_dari_foto_ganda(cek) == []
