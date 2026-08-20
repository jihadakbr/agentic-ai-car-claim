"""Uji agent penilai klaim dan ketiga LLM step.

Seluruh uji memakai klien tiruan, tidak ada panggilan ke penyedia sungguhan. Selain supaya
uji bisa dijalankan tanpa jaringan dan tanpa kunci API, ini juga menjaga kuota gratis yang
memang ketat tidak habis hanya untuk menjalankan uji.

Klien tiruan mencatat setiap prompt yang diterimanya, sehingga bisa diperiksa bukan cuma
hasil akhirnya, tapi juga apakah pemanggilan kedua benar-benar dilewati saat memang tidak
dibutuhkan.
"""

import json
from decimal import Decimal

import pytest

from app.agents import claim_assessment as agent
from app.core.llm import (
    AnggaranTerlampaui,
    BatasKuota,
    Jawaban,
    KlienBerjenjang,
    LlmError,
    ModelTidakAda,
    Penggunaan,
    PenjagaAnggaran,
    PenyediaTidakTersedia,
    ambil_json,
    daftar_teks,
    perkiraan_token,
)
from app.llm_steps import parts_resolver, report_generator, stnk_resolver


class KlienTiruan:
    """Klien yang mengembalikan jawaban yang sudah disiapkan, sambil mencatat prompt."""

    def __init__(self, jawaban: list[str], nama: str = "tiruan"):
        self.nama = nama
        self.antrean = list(jawaban)
        self.prompt: list[str] = []

    def jawab(self, prompt: str, max_tokens: int) -> Jawaban:
        self.prompt.append(prompt)
        teks = self.antrean.pop(0) if self.antrean else "{}"
        return Jawaban(
            teks=teks,
            penggunaan=Penggunaan(self.nama, "model-tiruan", perkiraan_token(prompt), 50),
        )


class KlienKehabisanKuota:
    nama = "habis"

    def __init__(self):
        self.dipanggil = 0

    def jawab(self, prompt: str, max_tokens: int) -> Jawaban:
        self.dipanggil += 1
        raise BatasKuota("kuota harian habis")


def jawaban_agent(**ubah) -> str:
    """Susun jawaban agent dari nilai bawaan yang wajar, cuma yang diuji yang diubah."""
    dasar = {
        "cukup_bukti": True,
        "permintaan_foto": [],
        "perlu_konteks_tambahan": False,
        "rekomendasi": "total_loss",
        "alasan": "Bukti lengkap dari empat foto",
    }
    return json.dumps({**dasar, **ubah})


@pytest.fixture
def penjaga() -> PenjagaAnggaran:
    return PenjagaAnggaran(batas_token_per_klaim=6000)


@pytest.fixture
def temuan() -> list[agent.RingkasanTemuan]:
    return [
        agent.RingkasanTemuan("Hood", None, "Dent", 0.45, "ganti part", 3, "deteksi"),
        agent.RingkasanTemuan("Headlight", "kanan", "Broken part", 0.60, "ganti part", 1, "deteksi"),
    ]


@pytest.fixture
def cek() -> list[agent.RingkasanCek]:
    return [
        agent.RingkasanCek("C1", "Kerusakannya benar ada", True, None, "lolos"),
        agent.RingkasanCek("C3", "Konsisten antar sudut", False, "soft",
                           "Headlight sisi kanan cuma terlihat di 1 dari 4 foto"),
    ]


@pytest.fixture
def biaya() -> agent.RingkasanBiaya:
    return agent.RingkasanBiaya(
        total_part=Decimal(65_150_000),
        total_jasa=Decimal(9_100_000),
        total_biaya=Decimal(74_250_000),
        harga_pasar_bekas=Decimal(95_000_000),
        total_loss_ratio=0.782,
        ambang_total_loss=0.75,
        rekomendasi_mesin="total_loss",
    )


def test_perkiraan_token_naik_seiring_panjang_teks():
    assert perkiraan_token("halo") < perkiraan_token("halo " * 100)
    assert perkiraan_token("") >= 1


def test_ambil_json_menembus_pagar_kode():
    assert ambil_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert ambil_json('Ini jawabannya: {"a": 2} semoga membantu') == {"a": 2}


def test_ambil_json_menolak_yang_bukan_objek():
    with pytest.raises(LlmError):
        ambil_json("[1, 2, 3]")
    with pytest.raises(LlmError):
        ambil_json("tidak ada json di sini")


def test_daftar_teks_memaksa_bentuk_yang_benar():
    """LLM kadang mengembalikan null untuk daftar kosong, atau teks tunggal."""
    assert daftar_teks(None) == []
    assert daftar_teks("satu") == ["satu"]
    assert daftar_teks(["a", "", "b"]) == ["a", "b"]


def test_penjaga_menolak_prompt_yang_kelewat_panjang():
    kecil = PenjagaAnggaran(batas_token_per_klaim=100)
    with pytest.raises(AnggaranTerlampaui):
        kecil.periksa("x" * 10_000, 400)


def test_penjaga_menghitung_pemakaian_kumulatif(penjaga):
    penjaga.catat(Penggunaan("a", "m", 1000, 200))
    penjaga.catat(Penggunaan("a", "m", 500, 100))
    assert penjaga.terpakai == 1800
    assert penjaga.sisa() == 4200


def test_klien_berjenjang_pindah_saat_kuota_habis():
    habis = KlienKehabisanKuota()
    cadangan = KlienTiruan(['{"ok": true}'], nama="cadangan")

    hasil = KlienBerjenjang([habis, cadangan]).jawab("halo", 100)

    assert habis.dipanggil == 1
    assert hasil.penggunaan.provider == "cadangan"


def test_klien_berjenjang_menyerah_kalau_semua_habis():
    with pytest.raises(PenyediaTidakTersedia, match="Tidak ada penyedia"):
        KlienBerjenjang([KlienKehabisanKuota(), KlienKehabisanKuota()]).jawab("halo", 100)


def test_klien_berjenjang_pindah_saat_model_dihapus_penyedia():
    """Penyedia gratis menghapus model tanpa pemberitahuan, dan penyedia lain masih bisa."""

    class ModelnyaHilang:
        nama = "hilang"

        def jawab(self, prompt, max_tokens):
            raise ModelTidakAda("hilang tidak punya model itu")

    cadangan = KlienTiruan(['{"ok": true}'], nama="cadangan")

    hasil = KlienBerjenjang([ModelnyaHilang(), cadangan]).jawab("halo", 100)

    assert hasil.penggunaan.provider == "cadangan"


def test_klien_berjenjang_tidak_menyamarkan_error_lain():
    """Prompt yang salah bentuk gagal di semua penyedia, jadi mencobanya berulang sia-sia."""

    class Rusak:
        nama = "rusak"

        def jawab(self, prompt, max_tokens):
            raise ValueError("prompt salah bentuk")

    with pytest.raises(ValueError):
        KlienBerjenjang([Rusak(), KlienTiruan(['{"a":1}'])]).jawab("halo", 100)


def test_prompt_agent_tidak_pernah_memuat_gambar(temuan, cek, biaya):
    """Penghematan token terbesar: yang dikirim cuma ringkasan teks."""
    prompt = agent.susun_prompt(temuan, cek, biaya)
    for kata in ("base64", "data:image", ".jpg", ".png", "mask", "piksel"):
        assert kata not in prompt.lower()


def test_prompt_agent_memuat_bahan_keputusan(temuan, cek, biaya):
    prompt = agent.susun_prompt(temuan, cek, biaya)
    assert "Hood" in prompt
    assert "Headlight sisi kanan" in prompt
    assert "C3" in prompt
    assert "78.2%" in prompt


def test_agent_klaim_normal_cuma_sekali_panggil(temuan, cek, biaya, penjaga):
    """Klaim yang buktinya cukup tidak boleh menghabiskan panggilan kedua."""
    klien = KlienTiruan([jawaban_agent()])

    hasil = agent.nilai(klien, temuan, cek, biaya, penjaga)

    assert hasil.jumlah_pass == 1
    assert len(klien.prompt) == 1
    assert hasil.cukup_bukti is True
    assert hasil.rekomendasi == "total_loss"


def test_agent_meminta_foto_tambahan_saat_bukti_kurang(temuan, cek, biaya, penjaga):
    klien = KlienTiruan([
        jawaban_agent(
            cukup_bukti=False,
            permintaan_foto=[{
                "foto": "foto sisi kanan depan dari jarak 2 meter, headlamp kanan utuh",
                "alasan": "Headlamp kanan cuma terlihat di satu foto",
            }],
            alasan="Bukti untuk headlamp kanan belum cukup",
        )
    ])

    hasil = agent.nilai(klien, temuan, cek, biaya, penjaga)

    assert hasil.cukup_bukti is False
    assert len(hasil.permintaan_foto) == 1
    assert "sisi kanan" in hasil.permintaan_foto[0].foto
    assert "Headlamp kanan" in hasil.permintaan_foto[0].alasan
    assert hasil.jumlah_pass == 1


def test_permintaan_agent_bentuk_lama_tetap_diterima(temuan, cek, biaya, penjaga):
    """Model gratis sering menjawab daftar teks polos. Penilaiannya tidak boleh dibuang."""
    klien = KlienTiruan([
        jawaban_agent(cukup_bukti=False, permintaan_foto=["foto sisi kanan depan"])
    ])

    hasil = agent.nilai(klien, temuan, cek, biaya, penjaga)

    assert len(hasil.permintaan_foto) == 1
    assert hasil.permintaan_foto[0].foto == "foto sisi kanan depan"
    assert hasil.permintaan_foto[0].alasan == agent.ALASAN_AGENT_KOSONG


def test_agent_tidak_menarik_konteks_saat_bukti_kurang(temuan, cek, biaya, penjaga):
    """Menarik panduan untuk klaim yang fotonya belum lengkap cuma membuang token."""
    dipanggil = []

    def ambil_konteks():
        dipanggil.append(True)
        return agent.KonteksTambahan(panduan_underwriting=["apa saja"])

    klien = KlienTiruan([
        jawaban_agent(
            cukup_bukti=False,
            permintaan_foto=["foto sisi kanan"],
            perlu_konteks_tambahan=True,
        )
    ])

    agent.nilai(klien, temuan, cek, biaya, penjaga, ambil_konteks=ambil_konteks)

    assert dipanggil == []


def test_agent_pass_dua_jalan_untuk_kasus_di_batas(temuan, cek, biaya, penjaga):
    """Inilah yang membuat komponen ini agentic: jalurnya ditentukan model sendiri."""

    def ambil_konteks():
        return agent.KonteksTambahan(
            panduan_underwriting=["Klaim di atas 75% wajib disetujui kepala cabang"],
            klaim_serupa=["Klaim KLM-2024-0091 rasio 76% disetujui sebagai total loss"],
        )

    klien = KlienTiruan([
        jawaban_agent(perlu_konteks_tambahan=True, alasan="Rasio dekat ambang"),
        jawaban_agent(alasan="Sesuai preseden klaim serupa"),
    ])

    hasil = agent.nilai(klien, temuan, cek, biaya, penjaga, ambil_konteks=ambil_konteks)

    assert hasil.jumlah_pass == 2
    assert len(klien.prompt) == 2
    assert "KONTEKS TAMBAHAN" in klien.prompt[1]
    assert "kepala cabang" in klien.prompt[1]
    assert hasil.alasan == "Sesuai preseden klaim serupa"


def test_agent_tanpa_pengambil_konteks_berhenti_di_pass_satu(temuan, cek, biaya, penjaga):
    klien = KlienTiruan([
        jawaban_agent(perlu_konteks_tambahan=True, rekomendasi="repair")
    ])
    hasil = agent.nilai(klien, temuan, cek, biaya, penjaga)
    assert hasil.jumlah_pass == 1


def test_agent_jatuh_ke_rekomendasi_mesin_kalau_llm_tidak_menjawabnya(temuan, cek, biaya, penjaga):
    """Angka sudah dihitung mesin, jadi keputusannya tidak boleh hilang gara-gara LLM diam."""
    klien = KlienTiruan(['{"cukup_bukti": true}'])
    hasil = agent.nilai(klien, temuan, cek, biaya, penjaga)
    assert hasil.rekomendasi == "total_loss"


def test_agent_mencatat_pemakaian_token(temuan, cek, biaya, penjaga):
    klien = KlienTiruan(['{"cukup_bukti": true, "rekomendasi": "repair", "alasan": "ok"}'])
    hasil = agent.nilai(klien, temuan, cek, biaya, penjaga)
    assert len(hasil.penggunaan) == 1
    assert penjaga.terpakai > 0


def test_dekat_batas_mengenali_kasus_yang_layak_ditimbang(biaya):
    assert agent.dekat_batas(biaya) is True
    jauh = agent.RingkasanBiaya(
        Decimal(1), Decimal(1), Decimal(2), Decimal(95_000_000), 0.02, 0.75, "repair"
    )
    assert agent.dekat_batas(jauh) is False


@pytest.fixture
def bahan() -> report_generator.BahanLaporan:
    return report_generator.BahanLaporan(
        nama_kendaraan="Toyota Avanza 1.3 G 2013",
        jumlah_part_diganti=14,
        jumlah_part_diperbaiki=0,
        part_termahal=["Airbag pengemudi", "Airbag penumpang depan"],
        total_biaya=Decimal(74_250_000),
        harga_pasar_bekas=Decimal(95_000_000),
        total_loss_ratio=0.782,
        ambang_total_loss=0.75,
        rekomendasi="total_loss",
        catatan_validitas=["C3 menandai headlamp kanan cuma terlihat di satu foto"],
        permintaan_foto_sebelumnya=[],
    )


def test_laporan_memakai_jawaban_llm(bahan, penjaga):
    klien = KlienTiruan(["Kendaraan mengalami kerusakan berat pada bagian depan."])
    hasil = report_generator.susun(klien, bahan, penjaga)
    assert hasil.narasi.startswith("Kendaraan mengalami")
    assert hasil.penggunaan is not None


def test_laporan_punya_cadangan_tanpa_llm(bahan, penjaga):
    """Layar adjuster tidak boleh kosong hanya karena satu layanan pihak ketiga mati."""
    hasil = report_generator.susun(None, bahan, penjaga)
    assert "Rp 74,250,000" in hasil.narasi
    assert "total loss" in hasil.narasi.lower()
    assert hasil.penggunaan is None


def test_laporan_cadangan_dipakai_saat_llm_gagal(bahan, penjaga):
    hasil = report_generator.susun(KlienKehabisanKuota(), bahan, penjaga)
    assert "Rp 74,250,000" in hasil.narasi


def test_laporan_cadangan_dipakai_saat_llm_menjawab_kosong(bahan, penjaga):
    hasil = report_generator.susun(KlienTiruan(["   "]), bahan, penjaga)
    assert "Rp 74,250,000" in hasil.narasi


def test_prompt_laporan_melarang_mengubah_angka(bahan):
    prompt = report_generator.susun_prompt(bahan)
    assert "jangan mengubah angka" in prompt.lower()


def test_parts_resolver_memilih_dari_kandidat(penjaga):
    kandidat = [
        parts_resolver.Kandidat("Rocker-panel", "Panel samping bawah"),
        parts_resolver.Kandidat("Quarter-panel", "Panel samping belakang"),
    ]
    klien = KlienTiruan(['{"padanan": "Rocker-panel", "alasan": "posisinya sama"}'])

    hasil = parts_resolver.cari(klien, "Side-skirt", kandidat, penjaga)

    assert hasil.padanan == "Rocker-panel"


def test_parts_resolver_menolak_padanan_karangan(penjaga):
    """LLM kadang mengarang nama bagian yang tidak ada di katalog."""
    kandidat = [parts_resolver.Kandidat("Rocker-panel", "Panel samping bawah")]
    klien = KlienTiruan(['{"padanan": "Bagian-Karangan", "alasan": "kelihatan cocok"}'])

    hasil = parts_resolver.cari(klien, "Side-skirt", kandidat, penjaga)

    assert hasil.padanan is None
    assert "ditolak" in hasil.alasan


def test_parts_resolver_tanpa_kandidat_tidak_memanggil_llm(penjaga):
    klien = KlienTiruan(['{"padanan": "apa saja"}'])
    hasil = parts_resolver.cari(klien, "Side-skirt", [], penjaga)
    assert hasil.padanan is None
    assert klien.prompt == []


def test_parts_resolver_membatasi_jumlah_kandidat_di_prompt():
    """Katalog utuh terlalu boros dikirim, jadi cuma daftar pendek yang masuk."""
    kandidat = [parts_resolver.Kandidat(f"Part-{i}", f"Nama {i}") for i in range(30)]
    prompt = parts_resolver.susun_prompt("Side-skirt", kandidat)
    assert prompt.count("- Part-") == parts_resolver.MAX_KANDIDAT


def test_stnk_resolver_tidak_menimpa_field_yang_sudah_terbaca(penjaga):
    """Hasil pencarian label lebih bisa dipercaya karena berasal dari posisi tulisan."""
    klien = KlienTiruan(['{"merk": "HONDA", "tipe": "SALAH", "tahun": 2020}'])
    sudah = {"merk": "TOYOTA", "tipe": "F601RM GMMFJJ"}

    hasil = stnk_resolver.susun(klien, "teks berantakan", sudah, penjaga)

    assert hasil.field["merk"] == "TOYOTA"
    assert hasil.field["tipe"] == "F601RM GMMFJJ"
    assert hasil.field["tahun"] == 2020


def test_stnk_resolver_menolak_tahun_di_luar_akal(penjaga):
    klien = KlienTiruan(['{"tahun": 9999}'])
    hasil = stnk_resolver.susun(klien, "teks", {}, penjaga)
    assert hasil.field["tahun"] is None


def test_stnk_resolver_tidak_jalan_tanpa_teks(penjaga):
    klien = KlienTiruan(['{"merk": "TOYOTA"}'])
    hasil = stnk_resolver.susun(klien, "   ", {}, penjaga)
    assert hasil.dipakai is False
    assert klien.prompt == []


def test_stnk_resolver_bertahan_saat_jawaban_rusak(penjaga):
    hasil = stnk_resolver.susun(KlienTiruan(["bukan json sama sekali"]), "teks", {}, penjaga)
    assert hasil.dipakai is False
    assert hasil.field["merk"] is None


def test_klaim_normal_cuma_dua_panggilan_llm(temuan, cek, biaya, bahan, penjaga):
    """Janji hemat token: agent sekali, laporan sekali, dua LLM step lain tidak jalan."""
    klien_agent = KlienTiruan([jawaban_agent()])
    klien_laporan = KlienTiruan(["Ringkasan singkat."])

    agent.nilai(klien_agent, temuan, cek, biaya, penjaga)
    report_generator.susun(klien_laporan, bahan, penjaga)

    assert len(klien_agent.prompt) + len(klien_laporan.prompt) == 2
    assert len(penjaga.riwayat) == 2


def test_narasi_menyebut_bagian_yang_tidak_terlihat_di_foto():
    """Narasi tidak boleh menyiratkan seluruh bagian benar-benar terpantau kamera."""
    bahan = report_generator.BahanLaporan(
        nama_kendaraan="Toyota Avanza 1.3 G",
        jumlah_part_diganti=14,
        jumlah_part_diperbaiki=0,
        jumlah_part_dari_aturan=6,
        part_termahal=["Airbag pengemudi"],
        total_biaya=Decimal(74_250_000),
        harga_pasar_bekas=Decimal(95_000_000),
        total_loss_ratio=0.782,
        ambang_total_loss=0.75,
        rekomendasi="total_loss",
        catatan_validitas=[],
        permintaan_foto_sebelumnya=[],
    )
    narasi = report_generator.narasi_cadangan(bahan)
    assert "6 bagian tidak terlihat di foto" in narasi


def test_narasi_tidak_menyebut_aturan_kalau_semuanya_dari_foto():
    bahan = report_generator.BahanLaporan(
        nama_kendaraan="Honda Brio Satya E",
        jumlah_part_diganti=1,
        jumlah_part_diperbaiki=1,
        jumlah_part_dari_aturan=0,
        part_termahal=["Kap mesin"],
        total_biaya=Decimal(7_200_000),
        harga_pasar_bekas=Decimal(125_000_000),
        total_loss_ratio=0.058,
        ambang_total_loss=0.75,
        rekomendasi="repair",
        catatan_validitas=[],
        permintaan_foto_sebelumnya=[],
    )
    assert "tidak terlihat di foto" not in report_generator.narasi_cadangan(bahan)


def test_bagian_tertutup_bodi_ditandai_mustahil_difoto():
    """Tanpa penanda ini, agent meminta foto radiator dan klaim macet selamanya."""
    prompt = agent.susun_prompt(
        [
            agent.RingkasanTemuan("Hood", None, "Dent", 0.62, "ganti part", 3, "deteksi"),
            agent.RingkasanTemuan("Radiator", None, "", 0.0, "ganti part", 0, "aturan"),
        ],
        [agent.RingkasanCek("C1", "Kerusakannya benar ada", True, None, "lolos")],
        agent.RingkasanBiaya(
            total_part=Decimal(20_000_000),
            total_jasa=Decimal(3_000_000),
            total_biaya=Decimal(23_000_000),
            harga_pasar_bekas=Decimal(95_000_000),
            total_loss_ratio=0.242,
            ambang_total_loss=0.75,
            rekomendasi_mesin="repair",
        ),
    )

    baris_radiator = next(b for b in prompt.splitlines() if b.startswith("- Radiator"))
    assert "tertutup bodi" in baris_radiator
    assert "foto tambahan tidak mungkin" in baris_radiator
    assert "Jangan pernah meminta foto bagian yang ditandai tertutup bodi" in prompt
