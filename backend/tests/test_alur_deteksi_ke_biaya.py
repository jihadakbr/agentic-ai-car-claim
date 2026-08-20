"""Uji sambungan seluruh lapisan deterministik, dari mask sampai rupiah.

Uji-uji lain memeriksa tiap bagian sendiri-sendiri. Berkas ini memeriksa bahwa bagian-bagian
itu benar-benar nyambung: mask hasil deteksi ditumpuk, diringkas antar foto, diubah jadi
temuan biaya, dicocokkan ke katalog dari database, lalu keluar angka rupiah dan keputusan
total loss.

Yang paling sering salah di sistem berlapis bukan tiap lapisannya, tapi sambungannya.
"""

from decimal import Decimal

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

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
from app.pipeline.cost_engine import hitung_biaya, susun_estimasi
from app.pipeline.overlay import MaskDeteksi, ke_temuan_biaya, ringkas_antar_foto, tumpuk
from app.pipeline.validity import (
    VALID,
    DataPolis,
    FotoKerusakan,
    HasilStnk,
    TemuanFoto,
    jalankan_semua,
)

TINGGI, LEBAR = 200, 400


def kotak(x0, y0, x1, y1) -> np.ndarray:
    m = np.zeros((TINGGI, LEBAR), dtype=bool)
    m[y0:y1, x0:x1] = True
    return m


@pytest.fixture
def s() -> Session:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as sesi:
        isi_semua(sesi)
        sesi.commit()
        yield sesi


def mask_mobil_depan():
    """Susun mask seolah hasil model bagian pada satu foto tampak depan."""
    return [
        MaskDeteksi("Hood", 0.93, kotak(100, 20, 300, 90)),
        MaskDeteksi("Front-bumper", 0.91, kotak(90, 120, 310, 170)),
        MaskDeteksi("Headlight", 0.88, kotak(100, 90, 150, 120)),
        MaskDeteksi("Headlight", 0.87, kotak(250, 90, 300, 120)),
        MaskDeteksi("Grille", 0.85, kotak(160, 95, 240, 120)),
        MaskDeteksi("License-plate", 0.80, kotak(180, 135, 220, 155)),
    ]


def test_mask_sampai_rupiah_nyambung(s):
    """Satu foto tampak depan, dijalankan sampai keluar angka biaya."""
    part = mask_mobil_depan()
    damage = [
        MaskDeteksi("Dent", 0.90, kotak(100, 20, 300, 55)),  # setengah kap mesin
        MaskDeteksi("Broken part", 0.92, kotak(90, 120, 310, 170)),  # seluruh bumper
    ]

    gabungan = tumpuk(part, damage, bagian_diabaikan=frozenset({"License-plate"}))
    ringkas, jumlah_foto = ringkas_antar_foto([gabungan])
    temuan = ke_temuan_biaya(ringkas, jumlah_foto)

    kendaraan = cari_kendaraan(s, "TOYOTA", "F601RM GMMFJJ", 2013)
    baris, tidak_ketemu = hitung_biaya(
        temuan, muat_katalog(s, kendaraan.id), muat_matriks(s), muat_tarif(s)
    )

    assert tidak_ketemu == []
    per_part = {b.part_class: b for b in baris}

    # Kap mesin penyok 50%, di atas ambang 25%, jadi diganti.
    assert per_part["Hood"].operasi == "ganti part"
    assert per_part["Hood"].harga_part == Decimal(4_200_000)

    # Bumper pecah, selalu diganti berapa pun luasnya.
    assert per_part["Front-bumper"].ganti_part is True

    est = susun_estimasi(
        baris,
        harga_pasar_bekas=Decimal(kendaraan.harga_pasar_bekas),
        ambang_total_loss=ambil_config_float(s, "ambang_total_loss"),
        own_risk=ambil_config_rupiah(s, "own_risk"),
        faktor_salvage=ambil_config_float(s, "faktor_salvage"),
    )

    assert est.total_biaya > 0
    assert est.rekomendasi == "repair"
    assert est.ditanggung_penanggung == est.total_biaya - est.own_risk


def test_plat_nomor_tidak_pernah_masuk_tagihan(s):
    """Plat dipakai untuk memeriksa identitas, bukan bagian yang bisa diklaim."""
    part = mask_mobil_depan()
    damage = [MaskDeteksi("Scratch", 0.9, kotak(180, 135, 220, 155))]

    gabungan = tumpuk(part, damage, bagian_diabaikan=frozenset({"License-plate"}))
    temuan = ke_temuan_biaya(*ringkas_antar_foto([gabungan]))

    assert all(t.part_class != "License-plate" for t in temuan)


def test_bagian_tak_ada_di_katalog_dilaporkan_bukan_dibuang(s):
    """Yang tidak ketemu diteruskan ke pencari padanan, bukan hilang diam-diam."""
    part = [MaskDeteksi("Bagian-Karangan", 0.9, kotak(10, 10, 110, 60))]
    damage = [MaskDeteksi("Dent", 0.9, kotak(10, 10, 110, 40))]

    temuan = ke_temuan_biaya(*ringkas_antar_foto([tumpuk(part, damage)]))
    kendaraan = cari_kendaraan(s, "TOYOTA", "F601RM GMMFJJ", 2013)

    baris, tidak_ketemu = hitung_biaya(
        temuan, muat_katalog(s, kendaraan.id), muat_matriks(s), muat_tarif(s)
    )
    assert baris == []
    assert tidak_ketemu == ["Bagian-Karangan"]


def test_hitungan_foto_dari_overlay_dipakai_cek_konsistensi(s):
    """Angka jumlah foto mengalir dari overlay sampai ke pemeriksaan antar sudut."""
    part = mask_mobil_depan()
    hanya_kap = [MaskDeteksi("Hood", 0.93, kotak(100, 20, 300, 90))]

    penyok_kap = MaskDeteksi("Dent", 0.9, kotak(100, 20, 300, 55))
    lampu_pecah = MaskDeteksi("Broken part", 0.9, kotak(250, 90, 300, 120))

    per_foto = [
        tumpuk(part, [penyok_kap, lampu_pecah]),
        tumpuk(hanya_kap, [penyok_kap]),
        tumpuk(hanya_kap, [penyok_kap]),
        tumpuk(hanya_kap, [penyok_kap]),
    ]
    _, jumlah_foto = ringkas_antar_foto(per_foto)

    assert jumlah_foto[("Hood", None)] == 4
    assert jumlah_foto[("Headlight", "kanan")] == 1

    # Angka itu yang membuat cek C3 menandai headlamp kanan.
    foto_cek = [
        FotoKerusakan(
            id=f"f{i}",
            phash=f"9f8a3c2d1e0b765{i}",
            confidence_kendaraan=0.93,
            plat_terbaca="B 1234 XYZ",
            temuan=[TemuanFoto(t.part_class, t.damage_class, 0.9, t.sisi) for t in per_foto[i]],
        )
        for i in range(4)
    ]
    stnk = HasilStnk(
        merk="TOYOTA", tipe="F601RM GMMFJJ", tahun=2013, nomor_polisi="B 1234 XYZ",
        nomor_rangka="MHKM1BA3JDK012345", nomor_mesin="1NRF012345", nama_pemilik="BUDI SANTOSO",
    )
    polis = DataPolis("B 1234 XYZ", "MHKM1BA3JDK012345", "1NRF012345", "BUDI SANTOSO")

    hasil, _ = jalankan_semua(foto_cek, stnk, polis, {})
    c3 = next(h for h in hasil if h.kode == "C3")
    assert c3.lolos is False
    assert "Headlight" in c3.alasan


def test_klaim_sehat_lolos_validitas_dan_menghasilkan_biaya(s):
    """Jalur bahagia lengkap: validitas lolos, biaya keluar, rekomendasi terbentuk."""
    part = mask_mobil_depan()
    damage = [MaskDeteksi("Dent", 0.9, kotak(100, 20, 300, 55))]
    per_foto = [tumpuk(part, damage, bagian_diabaikan=frozenset({"License-plate"}))] * 4
    ringkas, jumlah_foto = ringkas_antar_foto(per_foto)

    foto_cek = [
        FotoKerusakan(
            id=f"f{i}",
            phash=f"9f8a3c2d1e0b765{i}",
            confidence_kendaraan=0.93,
            plat_terbaca="B 1234 XYZ",
            temuan=[TemuanFoto(t.part_class, t.damage_class, 0.9, t.sisi) for t in ringkas],
        )
        for i in range(4)
    ]
    stnk = HasilStnk(
        merk="TOYOTA", tipe="F601RM GMMFJJ", tahun=2013, nomor_polisi="B 1234 XYZ",
        nomor_rangka="MHKM1BA3JDK012345", nomor_mesin="1NRF012345", nama_pemilik="BUDI SANTOSO",
    )
    polis = DataPolis("B 1234 XYZ", "MHKM1BA3JDK012345", "1NRF012345", "BUDI SANTOSO")

    hasil_cek, verdict = jalankan_semua(foto_cek, stnk, polis, {})
    assert verdict == VALID

    kendaraan = cari_kendaraan(s, "TOYOTA", "F601RM GMMFJJ", 2013)
    baris, _ = hitung_biaya(
        ke_temuan_biaya(ringkas, jumlah_foto),
        muat_katalog(s, kendaraan.id), muat_matriks(s), muat_tarif(s),
    )
    est = susun_estimasi(
        baris,
        harga_pasar_bekas=Decimal(kendaraan.harga_pasar_bekas),
        ambang_total_loss=ambil_config_float(s, "ambang_total_loss"),
        own_risk=ambil_config_rupiah(s, "own_risk"),
        faktor_salvage=ambil_config_float(s, "faktor_salvage"),
    )

    assert len(hasil_cek) == 7
    assert est.rekomendasi == "repair"
    assert est.total_biaya == Decimal(4_900_000)  # kap mesin 4,200,000 + jasa 2 jam


def test_klaim_tidak_valid_tetap_dihitung_biayanya(s):
    """Adjuster tetap butuh tahu nilai kerusakannya meski validitasnya bermasalah."""
    part = mask_mobil_depan()
    damage = [MaskDeteksi("Dent", 0.9, kotak(100, 20, 300, 55))]
    ringkas, jumlah_foto = ringkas_antar_foto([tumpuk(part, damage)])

    foto_cek = [
        FotoKerusakan(id="f0", phash="9f8a3c2d1e0b7650", confidence_kendaraan=0.93,
                      plat_terbaca="B 9999 ZZZ",
                      temuan=[TemuanFoto("Hood", "Dent", 0.9)])
    ]
    stnk = HasilStnk(
        merk="TOYOTA", tipe="F601RM GMMFJJ", tahun=2013, nomor_polisi="B 1234 XYZ",
        nomor_rangka="MHKM1BA3JDK012345", nomor_mesin="1NRF012345", nama_pemilik="BUDI SANTOSO",
    )
    polis = DataPolis("B 1234 XYZ", "MHKM1BA3JDK012345", "1NRF012345", "BUDI SANTOSO")

    _, verdict = jalankan_semua(foto_cek, stnk, polis, {})
    assert verdict == "invalid"

    kendaraan = cari_kendaraan(s, "TOYOTA", "F601RM GMMFJJ", 2013)
    baris, _ = hitung_biaya(
        ke_temuan_biaya(ringkas, jumlah_foto),
        muat_katalog(s, kendaraan.id), muat_matriks(s), muat_tarif(s),
    )
    est = susun_estimasi(
        baris,
        harga_pasar_bekas=Decimal(kendaraan.harga_pasar_bekas),
        ambang_total_loss=ambil_config_float(s, "ambang_total_loss"),
        own_risk=ambil_config_rupiah(s, "own_risk"),
        faktor_salvage=ambil_config_float(s, "faktor_salvage"),
    )
    assert est.total_biaya > 0
