"""Uji jalur harga pasar bekas, dari katalog sampai pencarian AI.

Harga pasar bekas adalah penyebut rasio total loss dan penentu besar penawaran beli
kendaraan. Yang paling penting dibuktikan di sini bukan bahwa pencariannya jalan, tapi
bahwa angka yang tidak bisa dipertanggungjawabkan tidak pernah lolos diam-diam.

Seluruh uji memakai pencari tiruan. Uji yang hasilnya bergantung mesin pencari sungguhan
akan gagal di waktu acak dan berhenti dipercaya.
"""

import json
from decimal import Decimal

import pytest

from app.agents import harga_pasar
from app.agents.pencari_web import HasilCari, PencariMati
from app.core.llm import Jawaban, Penggunaan, PenjagaAnggaran


class PencariTiruan:
    def __init__(self, *hasil: HasilCari):
        self.hasil = list(hasil)
        self.kueri: list[str] = []

    def cari(self, kueri: str, maksimal: int = 5) -> list[HasilCari]:
        self.kueri.append(kueri)
        return self.hasil


class KlienTiruan:
    def __init__(self, teks: str):
        self.nama = "tiruan"
        self.teks = teks
        self.prompt: list[str] = []

    def jawab(self, prompt: str, max_tokens: int) -> Jawaban:
        self.prompt.append(prompt)
        return Jawaban(self.teks, Penggunaan("tiruan", "m", 100, 20))


def hasil_contoh() -> list[HasilCari]:
    return [
        HasilCari("Harga Xpander bekas 2021", "https://contoh.test/a",
                  "Mitsubishi Xpander 2021 dijual mulai Rp 215.000.000"),
        HasilCari("Promo kredit mobil", "https://contoh.test/b",
                  "Angsuran mulai Rp 3.500.000 per bulan"),
    ]


def jawaban(**ubah) -> str:
    return json.dumps({"harga": 215_000_000, "alasan": "Dari iklan bekas",
                       "sumber_dipakai": [0], **ubah})


@pytest.fixture
def penjaga() -> PenjagaAnggaran:
    return PenjagaAnggaran()


def test_harga_ketemu_beserta_sumbernya(penjaga):
    pencari = PencariTiruan(*hasil_contoh())
    hasil = harga_pasar.cari(
        "MITSUBISHI", "XPANDER", 2021, pencari, KlienTiruan(jawaban()), penjaga
    )

    assert hasil.nilai == Decimal(215_000_000)
    assert hasil.sumber == harga_pasar.SUMBER_PENCARIAN
    assert hasil.dari_pencarian is True
    assert hasil.diketahui is True


def test_cuma_sumber_yang_dipakai_agent_yang_disimpan(penjaga):
    """Menampilkan seluruh hasil pencarian membuat adjuster memeriksa tautan yang salah."""
    pencari = PencariTiruan(*hasil_contoh())
    hasil = harga_pasar.cari(
        "MITSUBISHI", "XPANDER", 2021, pencari, KlienTiruan(jawaban()), penjaga
    )

    assert [r.url for r in hasil.rujukan] == ["https://contoh.test/a"]


def test_pencarian_kosong_jadi_tidak_diketahui_bukan_nol(penjaga):
    """Harga nol akan diam-diam jadi rekomendasi perbaikan, dan itu jebakan yang mahal."""
    hasil = harga_pasar.cari(
        "MITSUBISHI", "XPANDER", 2021, PencariMati(), KlienTiruan(jawaban()), penjaga
    )

    assert hasil.nilai is None
    assert hasil.sumber == harga_pasar.SUMBER_TIDAK_DIKETAHUI
    assert hasil.diketahui is False


@pytest.mark.parametrize(
    "kesalahan",
    [RuntimeError("penyedia mengembalikan 404"), ValueError("balasan aneh")],
)
def test_llm_yang_mati_tidak_menggagalkan_klaim(penjaga, kesalahan):
    """Penyedia gratis bisa mati kapan saja, dan klaim tetap harus selesai diproses."""

    class KlienMati:
        nama = "mati"

        def jawab(self, prompt, max_tokens):
            raise kesalahan

    hasil = harga_pasar.cari(
        "MITSUBISHI", "XPANDER", 2021, PencariTiruan(*hasil_contoh()), KlienMati(), penjaga
    )

    assert hasil.sumber == harga_pasar.SUMBER_TIDAK_DIKETAHUI
    assert "gagal" in hasil.keterangan


def test_jawaban_llm_tanpa_json_jadi_tidak_diketahui(penjaga):
    """Model bernalar kerap menghabiskan jatah keluaran dan menyisakan teks kosong."""
    hasil = harga_pasar.cari(
        "MITSUBISHI", "XPANDER", 2021, PencariTiruan(*hasil_contoh()),
        KlienTiruan(""), penjaga,
    )

    assert hasil.sumber == harga_pasar.SUMBER_TIDAK_DIKETAHUI


def test_harga_null_dari_agent_jadi_tidak_diketahui(penjaga):
    pencari = PencariTiruan(*hasil_contoh())
    hasil = harga_pasar.cari(
        "MITSUBISHI", "XPANDER", 2021, pencari,
        KlienTiruan(jawaban(harga=None, alasan="Tidak ada yang menyebut harga mobil ini")),
        penjaga,
    )

    assert hasil.nilai is None
    assert "Tidak ada yang menyebut" in hasil.keterangan


@pytest.mark.parametrize("angka", [3_500_000, 5_000_000_000])
def test_harga_di_luar_batas_wajar_ditolak(penjaga, angka):
    """Model bisa salah mengambil angsuran bulanan atau nomor telepon sebagai harga."""
    pencari = PencariTiruan(*hasil_contoh())
    hasil = harga_pasar.cari(
        "MITSUBISHI", "XPANDER", 2021, pencari, KlienTiruan(jawaban(harga=angka)), penjaga
    )

    assert hasil.nilai is None
    assert hasil.sumber == harga_pasar.SUMBER_TIDAK_DIKETAHUI


def test_harga_berformat_rupiah_tetap_terbaca(penjaga):
    pencari = PencariTiruan(*hasil_contoh())
    hasil = harga_pasar.cari(
        "MITSUBISHI", "XPANDER", 2021, pencari,
        KlienTiruan(jawaban(harga="Rp 215.000.000")), penjaga,
    )

    assert hasil.nilai == Decimal(215_000_000)


def test_nomor_sumber_yang_ngawur_diabaikan(penjaga):
    pencari = PencariTiruan(*hasil_contoh())
    hasil = harga_pasar.cari(
        "MITSUBISHI", "XPANDER", 2021, pencari,
        KlienTiruan(jawaban(sumber_dipakai=[9, "bukan angka", 1])), penjaga,
    )

    assert [r.url for r in hasil.rujukan] == ["https://contoh.test/b"]


def test_kueri_menyebut_kendaraannya(penjaga):
    pencari = PencariTiruan(*hasil_contoh())
    harga_pasar.cari(
        "MITSUBISHI", "XPANDER", 2021, pencari, KlienTiruan(jawaban()), penjaga
    )

    kueri = pencari.kueri[0]
    assert "MITSUBISHI" in kueri
    assert "XPANDER" in kueri
    assert "2021" in kueri


def test_kueri_memakai_nama_pasar_bukan_kode_tipe_stnk(penjaga):
    """Kode tipe pabrik tidak pernah muncul di iklan mobil bekas, jadi kunci pencariannya nihil."""
    pencari = PencariTiruan(*hasil_contoh())
    harga_pasar.cari(
        "WULING", "AF12 LUX CVT", 2022, pencari, KlienTiruan(jawaban()), penjaga,
        nama_pasar="Wuling Almaz RS",
    )

    kueri = pencari.kueri[0]
    assert "Wuling Almaz RS" in kueri
    assert "AF12" not in kueri
    assert "2022" in kueri


def test_pemakaian_token_ikut_dilaporkan(penjaga):
    pencari = PencariTiruan(*hasil_contoh())
    hasil = harga_pasar.cari(
        "MITSUBISHI", "XPANDER", 2021, pencari, KlienTiruan(jawaban()), penjaga
    )

    assert len(hasil.penggunaan) == 1
    assert hasil.penggunaan[0].token_masuk == 100


class PencariDuaTahap:
    """Kueri pertama menjawab tanpa angka, kueri kedua baru memuat harga."""

    def __init__(self, tanpa_harga: list[HasilCari], berharga: list[HasilCari]):
        self.jawaban = [tanpa_harga, berharga]
        self.kueri: list[str] = []

    def cari(self, kueri: str, maksimal: int = 5) -> list[HasilCari]:
        self.kueri.append(kueri)
        return self.jawaban.pop(0) if self.jawaban else []


def test_kueri_utama_menyebut_bentuk_kalimat_harga(penjaga):
    """Cuplikan hasil pencarian sering tanpa angka kalau kuerinya tidak mengarahkan."""
    pencari = PencariTiruan(*hasil_contoh())
    harga_pasar.cari("MITSUBISHI", "XPANDER", 2021, pencari, KlienTiruan(jawaban()), penjaga)

    assert "mulai dari Rp" in pencari.kueri[0]


def test_pencarian_diulang_dengan_kueri_lain_kalau_cuplikan_tanpa_harga(penjaga):
    tanpa = [HasilCari("Jual beli mobil", "https://contoh.test/x", "Pilihan mobil bekas.")]
    ada = [HasilCari("Harga Xpander bekas", "https://contoh.test/y",
                     "Xpander 2021 mulai Rp 215.000.000")]
    pencari = PencariDuaTahap(tanpa, ada)

    hasil = harga_pasar.cari(
        "MITSUBISHI", "XPANDER", 2021, pencari, KlienTiruan(jawaban()), penjaga
    )

    assert len(pencari.kueri) == 2
    assert pencari.kueri[0] != pencari.kueri[1]
    assert hasil.diketahui


def test_pencarian_tidak_diulang_kalau_cuplikan_sudah_memuat_harga(penjaga):
    """Kueri kedua memakan waktu dan kuota, jadi cuma dipakai saat memang perlu."""
    pencari = PencariTiruan(*hasil_contoh())
    harga_pasar.cari("MITSUBISHI", "XPANDER", 2021, pencari, KlienTiruan(jawaban()), penjaga)

    assert len(pencari.kueri) == 1


def test_hasil_kedua_kueri_digabung_tanpa_alamat_kembar(penjaga):
    sama = HasilCari("Sama", "https://contoh.test/z", "Belum ada angka")
    tanpa = [sama]
    ada = [sama, HasilCari("Harga", "https://contoh.test/w", "mulai Rp 215.000.000")]
    pencari = PencariDuaTahap(tanpa, ada)
    klien = KlienTiruan(jawaban())

    harga_pasar.cari("MITSUBISHI", "XPANDER", 2021, pencari, klien, penjaga)

    # Alamat tidak ikut masuk prompt, jadi kembarnya dilihat dari judul dan penomoran.
    assert klien.prompt[0].count("Sama") == 1
    assert "[1]" in klien.prompt[0]
    assert "[2]" not in klien.prompt[0]
