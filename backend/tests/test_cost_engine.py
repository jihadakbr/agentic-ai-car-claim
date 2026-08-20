"""Uji cost engine.

Uji terpenting di berkas ini adalah `test_contoh_avanza_kasus_acuan`, yang menghitung
ulang kasus acuan dari nol. Angka harapannya sama dengan yang dipakai di materi
presentasi, jadi kalau salah satunya berubah tanpa yang lain, uji ini yang menangkapnya.
"""

from decimal import Decimal

import pytest

from app.core.aturan import (
    JAM_STANDAR_BAWAAN,
    JAM_STANDAR_GANTI,
    MATRIKS_PERBAIKAN,
    TARIF_PER_JAM,
)
from app.pipeline.cost_engine import (
    AturanPerbaikan,
    AturanTidakDitemukan,
    Part,
    Tarif,
    Temuan,
    cari_tarif,
    gabungkan_temuan,
    hitung_biaya,
    pilih_aturan,
    sebaran,
    susun_estimasi,
)

AMBANG_TOTAL_LOSS = 0.75
OWN_RISK = Decimal(300_000)
FAKTOR_SALVAGE = 0.30


@pytest.fixture
def matriks() -> list[AturanPerbaikan]:
    return [
        AturanPerbaikan(damage_class=d, rasio_min=lo, rasio_max=hi, operasi=op, ganti_part=ganti)
        for d, lo, hi, op, ganti, _ in MATRIKS_PERBAIKAN
    ]


@pytest.fixture
def tarif() -> list[Tarif]:
    daftar = [
        Tarif(operasi=op, jam_standar=jam, tarif_per_jam=Decimal(TARIF_PER_JAM))
        for op, jam in JAM_STANDAR_BAWAAN.items()
    ]
    daftar += [
        Tarif(
            operasi="ganti part",
            part_class=part,
            jam_standar=jam,
            tarif_per_jam=Decimal(TARIF_PER_JAM),
        )
        for part, jam in JAM_STANDAR_GANTI.items()
    ]
    return daftar


# Harga sparepart Avanza 1.3 G 2013, sama dengan yang diisi ke database. Angka buatan.
HARGA_AVANZA = {
    "Front-bumper": ("Bumper depan", 2_850_000, True),
    "Hood": ("Kap mesin", 4_200_000, True),
    "Fender": ("Fender depan", 2_100_000, True),
    "Headlight": ("Headlamp", 3_750_000, True),
    "Grille": ("Grille", 1_650_000, True),
    "Windshield": ("Kaca depan", 2_950_000, True),
    "Radiator": ("Radiator", 2_400_000, False),
    "Kondensor-AC": ("Kondensor AC", 3_100_000, False),
    "Panel-bodi-depan": ("Panel bodi depan", 5_800_000, False),
    "Airbag-pengemudi": ("Airbag pengemudi", 12_500_000, False),
    "Airbag-penumpang": ("Airbag penumpang depan", 11_800_000, False),
    "Modul-airbag": ("Modul kontrol airbag", 6_200_000, False),
}


@pytest.fixture
def katalog() -> dict[str, Part]:
    return {
        kelas: Part(
            part_class=kelas,
            nama_part=nama,
            harga=Decimal(harga),
            terlihat_dari_luar=terlihat,
        )
        for kelas, (nama, harga, terlihat) in HARGA_AVANZA.items()
    }


def test_pilih_aturan_memakai_rentang_yang_benar(matriks):
    # Baret tipis dipoles, baret luas dicat ulang. Batasnya 15%.
    assert pilih_aturan("Scratch", 0.08, matriks).operasi == "poles"
    assert pilih_aturan("Scratch", 0.35, matriks).operasi == "cat ulang panel"

    # Penyok di bawah 25% masih diketok, di atasnya part diganti.
    assert pilih_aturan("Dent", 0.15, matriks).ganti_part is False
    assert pilih_aturan("Dent", 0.45, matriks).ganti_part is True


def test_batas_rentang_bersifat_inklusif_di_bawah(matriks):
    """Rasio tepat di batas masuk ke rentang atasnya, bukan rentang bawahnya."""
    assert pilih_aturan("Dent", 0.25, matriks).operasi == "ganti part"
    assert pilih_aturan("Scratch", 0.15, matriks).operasi == "cat ulang panel"


def test_kerusakan_tanpa_ambang_selalu_ganti(matriks):
    """Pecah dan hilang tidak bergantung luas sama sekali, termasuk saat 100%."""
    for kelas in ("Broken part", "Missing part"):
        assert pilih_aturan(kelas, 0.01, matriks).ganti_part is True
        assert pilih_aturan(kelas, 1.0, matriks).ganti_part is True


def test_kerusakan_tak_dikenal_melempar_error(matriks):
    """Lebih baik berhenti dengan pesan jelas daripada diam-diam tidak menghitung biaya."""
    with pytest.raises(AturanTidakDitemukan):
        pilih_aturan("Tire flat", 0.5, matriks)


def test_cari_tarif_utamakan_aturan_khusus(tarif):
    assert cari_tarif("ganti part", "Headlight", tarif).jam_standar == 0.8
    assert cari_tarif("ganti part", "Panel-bodi-depan", tarif).jam_standar == 5.0
    # Bagian tanpa aturan khusus jatuh ke nilai bawaan operasinya.
    assert cari_tarif("ganti part", "Bagian-Tak-Dikenal", tarif).jam_standar == 2.5


def test_gabungkan_temuan_ambil_rasio_tertinggi():
    """Satu bagian bisa terlihat di beberapa foto dengan sudut berbeda."""
    temuan = [
        Temuan("Hood", "Dent", 0.31, jumlah_foto=1),
        Temuan("Hood", "Dent", 0.45, jumlah_foto=1),
        Temuan("Hood", "Dent", 0.22, jumlah_foto=1),
    ]
    hasil = gabungkan_temuan(temuan)
    assert len(hasil) == 1
    assert hasil[0].rasio_luas == 0.45
    assert hasil[0].jumlah_foto == 3


def test_kiri_dan_kanan_dihitung_terpisah(katalog, matriks, tarif):
    """Dua fender yang rusak harus jadi dua baris biaya, bukan satu."""
    temuan = [
        Temuan("Fender", "Dent", 0.40, sisi="kiri"),
        Temuan("Fender", "Dent", 0.40, sisi="kanan"),
    ]
    baris, _ = hitung_biaya(temuan, katalog, matriks, tarif)
    assert len(baris) == 2
    assert {b.sisi for b in baris} == {"kiri", "kanan"}


def test_ganti_part_mengalahkan_operasi_perbaikan(katalog, matriks, tarif):
    """Bumper yang baret sekaligus pecah diganti, dan poles tidak ikut ditagihkan."""
    temuan = [
        Temuan("Front-bumper", "Scratch", 0.05),
        Temuan("Front-bumper", "Broken part", 0.02),
    ]
    baris, _ = hitung_biaya(temuan, katalog, matriks, tarif)
    assert len(baris) == 1
    assert baris[0].operasi == "ganti part"
    assert baris[0].harga_part == Decimal(2_850_000)
    assert "tercakup operasi ini" in baris[0].alasan_aturan
    # Kerusakan yang kalah tetap dibawa ke layar, supaya tidak terbaca seolah terlewat.
    assert baris[0].kerusakan_lain == ["Scratch"]


def test_part_di_luar_katalog_dilaporkan(katalog, matriks, tarif):
    """Yang tidak ketemu tidak dibuang diam-diam, tapi dikembalikan untuk dicarikan padanan."""
    temuan = [Temuan("Rocker-panel", "Dent", 0.40)]
    baris, tidak_ketemu = hitung_biaya(temuan, katalog, matriks, tarif)
    assert baris == []
    assert tidak_ketemu == ["Rocker-panel"]


def test_operasi_perbaikan_tidak_menagih_harga_part(katalog, matriks, tarif):
    temuan = [Temuan("Front-door", "Scratch", 0.08)]
    katalog_pintu = dict(katalog)
    katalog_pintu["Front-door"] = Part("Front-door", "Pintu depan", Decimal(5_000_000))
    baris, _ = hitung_biaya(temuan, katalog_pintu, matriks, tarif)
    assert baris[0].operasi == "poles"
    assert baris[0].harga_part == Decimal(0)
    assert baris[0].biaya_jasa == Decimal(700_000)


def test_contoh_avanza_kasus_acuan(katalog, matriks, tarif):
    """Hitung ulang kasus acuan total loss dari nol.

    Delapan baris pertama berasal dari deteksi foto. Enam baris terakhir tidak terlihat
    dari luar dan masuk lewat aturan yang dipicu tingkat keparahan benturan depan.
    """
    terdeteksi = [
        Temuan("Front-bumper", "Broken part", 0.72),
        Temuan("Hood", "Dent", 0.45),
        Temuan("Fender", "Dent", 0.38, sisi="kiri"),
        Temuan("Fender", "Dent", 0.41, sisi="kanan"),
        Temuan("Headlight", "Broken part", 0.60, sisi="kiri"),
        Temuan("Headlight", "Broken part", 0.55, sisi="kanan"),
        Temuan("Grille", "Missing part", 0.90),
        Temuan("Windshield", "Broken part", 0.30),
    ]
    dari_aturan = [
        Temuan(kelas, "Broken part", 1.0, sumber="aturan")
        for kelas in (
            "Radiator",
            "Kondensor-AC",
            "Panel-bodi-depan",
            "Airbag-pengemudi",
            "Airbag-penumpang",
            "Modul-airbag",
        )
    ]

    baris, tidak_ketemu = hitung_biaya(terdeteksi + dari_aturan, katalog, matriks, tarif)
    assert tidak_ketemu == []
    assert len(baris) == 14

    est = susun_estimasi(
        baris,
        harga_pasar_bekas=Decimal(95_000_000),
        ambang_total_loss=AMBANG_TOTAL_LOSS,
        own_risk=OWN_RISK,
        faktor_salvage=FAKTOR_SALVAGE,
    )

    assert est.total_part == Decimal(65_150_000)
    assert sum(b.jam_standar for b in baris) == pytest.approx(26.0)
    assert est.total_jasa == Decimal(9_100_000)
    assert est.total_biaya == Decimal(74_250_000)
    assert round(est.total_loss_ratio * 100, 1) == 78.2
    assert est.rekomendasi == "total_loss"
    assert est.harga_tawaran_salvage == Decimal(28_500_000)

    # Enam baris dari aturan harus tetap bisa dibedakan dari hasil deteksi.
    assert sum(1 for b in baris if b.sumber == "aturan") == 6


def test_contoh_repair_kasus_acuan(katalog, matriks, tarif):
    """Kasus acuan baret ringan: repair, own risk dipotong dari tanggungan."""
    katalog_pintu = dict(katalog)
    katalog_pintu["Back-door"] = Part("Back-door", "Pintu belakang", Decimal(4_800_000))

    baris, _ = hitung_biaya(
        [Temuan("Back-door", "Scratch", 0.08, sisi="kanan")], katalog_pintu, matriks, tarif
    )
    est = susun_estimasi(
        baris,
        harga_pasar_bekas=Decimal(95_000_000),
        ambang_total_loss=AMBANG_TOTAL_LOSS,
        own_risk=OWN_RISK,
        faktor_salvage=FAKTOR_SALVAGE,
    )

    assert est.total_part == Decimal(0)
    assert est.total_biaya == Decimal(700_000)
    assert est.rekomendasi == "repair"
    assert est.own_risk == Decimal(300_000)
    assert est.ditanggung_penanggung == Decimal(400_000)
    assert est.harga_tawaran_salvage is None


def test_ambang_total_loss_inklusif(katalog, matriks, tarif):
    """PSAKBI menyebut "sama dengan atau lebih besar", jadi rasio tepat 75% sudah total loss."""
    baris, _ = hitung_biaya([Temuan("Hood", "Dent", 0.45)], katalog, matriks, tarif)
    # Kap mesin: part 4,200,000 + jasa 2 jam x 350,000 = 4,900,000.
    est = susun_estimasi(
        baris,
        harga_pasar_bekas=Decimal(4_900_000) / Decimal("0.75"),
        ambang_total_loss=0.75,
        own_risk=OWN_RISK,
        faktor_salvage=FAKTOR_SALVAGE,
    )
    assert est.total_loss_ratio == pytest.approx(0.75)
    assert est.rekomendasi == "total_loss"


def test_own_risk_tidak_membuat_tanggungan_negatif(katalog, matriks, tarif):
    """Klaim yang biayanya di bawah own risk ditanggung penuh oleh tertanggung."""
    katalog_kecil = {"Grille": Part("Grille", "Grille", Decimal(1_650_000))}
    baris, _ = hitung_biaya([Temuan("Grille", "Scratch", 0.02)], katalog_kecil, matriks, tarif)
    est = susun_estimasi(
        baris,
        harga_pasar_bekas=Decimal(95_000_000),
        ambang_total_loss=AMBANG_TOTAL_LOSS,
        own_risk=OWN_RISK,
        faktor_salvage=FAKTOR_SALVAGE,
    )
    # Touch-up cat: 0.5 jam x 350,000 = 175,000, di bawah own risk 300,000.
    assert est.total_biaya == Decimal(175_000)
    assert est.own_risk == Decimal(175_000)
    assert est.ditanggung_penanggung == Decimal(0)


def test_hasil_selalu_sama_untuk_masukan_sama(katalog, matriks, tarif):
    """Sifat paling penting untuk asuransi: perhitungan bisa diulang dan hasilnya identik."""
    temuan = [
        Temuan("Hood", "Dent", 0.45),
        Temuan("Front-bumper", "Broken part", 0.20),
        Temuan("Fender", "Scratch", 0.10, sisi="kiri"),
    ]
    hasil = []
    for _ in range(5):
        baris, _ = hitung_biaya(temuan, katalog, matriks, tarif)
        est = susun_estimasi(
            baris,
            harga_pasar_bekas=Decimal(95_000_000),
            ambang_total_loss=AMBANG_TOTAL_LOSS,
            own_risk=OWN_RISK,
            faktor_salvage=FAKTOR_SALVAGE,
        )
        hasil.append((est.total_biaya, est.total_loss_ratio, est.rekomendasi))
    assert len(set(hasil)) == 1


def test_alasan_operasi_tidak_memajang_rasio_sebagai_angka(katalog, matriks, tarif):
    """Rasio luas bergantung sudut foto, jadi tidak boleh tampil seolah hasil ukur."""
    baris, _ = hitung_biaya([Temuan("Hood", "Dent", 0.45)], katalog, matriks, tarif)

    alasan = baris[0].alasan_aturan
    assert "45%" not in alasan
    assert "kerusakan luas" in alasan
    assert "batas 25% luas part" in alasan
    assert "ganti part" in alasan


def test_alasan_menyebut_luas_tidak_dipakai_kalau_aturannya_memang_begitu(
    katalog, matriks, tarif
):
    """Delapan dari sebelas baris matriks berlaku untuk luas berapa pun."""
    baris, _ = hitung_biaya([Temuan("Front-bumper", "Broken part", 0.20)], katalog, matriks, tarif)

    assert "berapa pun luasnya" in baris[0].alasan_aturan


@pytest.mark.parametrize(
    ("rasio", "kata"),
    [(0.0, "kecil"), (0.14, "kecil"), (0.15, "sedang"), (0.39, "sedang"),
     (0.40, "luas"), (1.0, "luas")],
)
def test_sebaran_memetakan_rasio_ke_kata(rasio, kata):
    assert sebaran(rasio) == kata
