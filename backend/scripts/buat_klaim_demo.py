"""Siapkan tiga klaim contoh beserta hasilnya, sebagai jaring pengaman presentasi.

Jalankan: `uv run python scripts/buat_klaim_demo.py`

Ketiganya diproses lewat pipeline yang sama persis dengan klaim biasa, lalu hasilnya
tersimpan di database sehingga bisa dibuka seketika tanpa menunggu apa pun. Kalau saat
presentasi antrean GPU sedang panjang, Space baru bangun, atau jaringannya bermasalah,
ketiga klaim ini tetap tampil.

Yang ditunjukkan masing-masing:

- perbaikan biasa, biayanya jauh di bawah ambang
- total loss, biayanya melewati ambang PSAKBI sehingga terbit penawaran beli
- gagal pemeriksaan, fotonya dipakai ulang dari klaim pertama

Semuanya memakai foto mobil sungguhan.

Aman dijalankan berulang. Klaim contoh lama dihapus lebih dulu supaya tidak menumpuk, dan
klaim sungguhan tidak ikut tersentuh karena yang dihapus hanya baris bertanda contoh.

Penilaian agent sengaja dilewati di sini meski kunci LLM tersedia. Agent boleh menahan
klaim untuk meminta foto tambahan, dan klaim yang tertahan tampil tanpa narasi maupun
kesimpulan. Jaring pengaman yang isinya berubah tiap kali dijalankan bukan jaring pengaman.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import random
from typing import NamedTuple

from PIL import Image
from sqlalchemy import select

from app.api import penyimpanan
from app.api.server import FOLDER_FOTO, buat_detektor
from app.db.models import (
    AuditLog,
    Claim,
    ClaimPhoto,
    CostEstimate,
    CostEstimateLine,
    PhotoRequest,
    Policy,
    StnkExtraction,
    ValidityCheck,
    VehicleModel,
)
from app.db.session import alamat_database, buat_tabel, sesi
from app.pipeline.detektor import DetektorContoh
from app.pipeline.orkestrasi import MasukanKlaim, proses
from app.pipeline.stnk_dataset import dari_polis
from app.pipeline.stnk_generator import buat_stnk
from app.pipeline.stnk_ocr import baca_stnk
from app.pipeline.validity import HasilStnk

KANDIDAT = (
    Path(__file__).resolve().parents[1] / "data" / "foto-klaim-n-stnk" / "kandidat-demo"
)

# Foto tiap skenario dipilih setelah biayanya diukur lewat cost engine, bukan dikira-kira,
# supaya klaim contoh benar-benar berakhir di rekomendasi yang dimaksud namanya.
FOTO_RINGAN = KANDIDAT / "15 - Car damages 759.png"    # Rp 11.0 jt, 11.6% dari harga pasar
FOTO_BERAT = KANDIDAT / "04 - Car damages 1344.png"    # Rp 84.2 jt, 88.6%, lewat ambang


class Skenario(NamedTuple):
    nama: str
    nomor_polis: str
    kerusakan: str
    rasio: float
    keterangan: str
    # Foto sungguhan yang dipakai. Kalau kosong, dipakai foto klaim sebelumnya, dan itu
    # yang membuat pemeriksaan foto dipakai ulang punya bahan untuk ditangkap.
    foto: Path | None = None


SKENARIO = [
    Skenario("Perbaikan biasa", "POL-2024-0245", "Scratch", 0.20,
             "Kerusakan ringan, biaya jauh di bawah ambang", foto=FOTO_RINGAN),
    Skenario("Total loss", "POL-2024-0037", "Dent", 0.95,
             "Benturan depan berat, biaya melewati ambang PSAKBI", foto=FOTO_BERAT),
    Skenario("Gagal pemeriksaan", "POL-2025-0008", "Dent", 0.40,
             "Foto dipakai ulang dari klaim pertama"),
]



def hapus_klaim_contoh(s) -> int:
    """Buang klaim contoh lama beserta seluruh turunannya."""
    lama = list(s.scalars(select(Claim).where(Claim.contoh_demo.is_(True))))
    for klaim in lama:
        for tabel in (
            ValidityCheck, ClaimPhoto, StnkExtraction, PhotoRequest, AuditLog,
        ):
            s.query(tabel).filter(tabel.claim_id == klaim.id).delete()
        est = s.scalar(select(CostEstimate).where(CostEstimate.claim_id == klaim.id))
        if est is not None:
            s.query(CostEstimateLine).filter(
                CostEstimateLine.cost_estimate_id == est.id
            ).delete()
            s.delete(est)
        s.delete(klaim)
    s.flush()
    return len(lama)


def main() -> None:
    print(f"Database: {alamat_database()}")
    buat_tabel()
    FOLDER_FOTO.mkdir(parents=True, exist_ok=True)
    rng = random.Random(2026)
    detektor = buat_detektor()
    print(f"Detektor: {type(detektor).__name__}")

    with sesi() as s:
        dibuang = hapus_klaim_contoh(s)
        if dibuang:
            print(f"Klaim contoh lama dihapus: {dibuang}")

        foto_pertama: list[Image.Image] = []

        for sk in SKENARIO:
            nama, nomor_polis, keterangan = sk.nama, sk.nomor_polis, sk.keterangan
            polis = s.scalar(select(Policy).where(Policy.nomor_polis == nomor_polis))
            if polis is None:
                raise SystemExit(f"Polis {nomor_polis} tidak ada. Isi data awal lebih dulu.")
            kendaraan = s.get(VehicleModel, polis.vehicle_model_id)

            # Klaim ketiga sengaja memakai foto klaim pertama supaya pemeriksaan foto
            # dipakai ulang benar-benar gagal, bukan sekadar ditulis gagal.
            # Skenario tanpa foto sendiri memakai foto klaim pertama, dan itu memang yang
            # membuat pemeriksaan foto dipakai ulang gagal seperti seharusnya.
            gambar = [Image.open(sk.foto).convert("RGB")] if sk.foto else foto_pertama

            # Harus username akun, bukan nama panggilan, karena layar Klaim Saya menyaring
            # dengan membandingkan kolom ini terhadap akun yang sedang masuk.
            klaim = penyimpanan.buat_klaim(s, polis, kendaraan, surveyor="surveyor")
            klaim.contoh_demo = True

            contoh = dari_polis(polis, kendaraan, rng)
            gambar_stnk = buat_stnk(contoh.data, rng, tingkat_kerusakan=0.3)
            baca = baca_stnk(gambar_stnk, _pembaca())
            stnk = baca.stnk if baca.stnk.nomor_rangka else _stnk_cadangan(polis, kendaraan)
            penyimpanan.simpan_stnk(s, klaim.id, stnk, baca.teks_mentah)

            mesin = (
                DetektorContoh(kerusakan=sk.kerusakan, rasio_kerusakan=sk.rasio)
                if isinstance(detektor, DetektorContoh)
                else detektor
            )

            def jalankan(
                foto,
                _polis=polis,
                _kendaraan=kendaraan,
                _stnk=stnk,
                _klaim=klaim,
                _mesin=mesin,
            ):
                return proses(
                    MasukanKlaim(
                        foto_kerusakan=foto,
                        nomor_polis=_polis.nomor_polis,
                        stnk=_stnk,
                        polis=penyimpanan.data_polis(_polis),
                        nama_kendaraan=_kendaraan.nama_tampil,
                        harga_pasar_bekas=_kendaraan.harga_pasar_bekas,
                    ),
                    penyimpanan.muat_referensi(s, _kendaraan.id),
                    _mesin,
                    penyimpanan.phash_klaim_lain(s, kecuali_claim_id=_klaim.id),
                    klien_llm=None,
                )

            hasil = jalankan(gambar)

            jalur = []
            for i, g in enumerate(gambar):
                berkas = FOLDER_FOTO / f"{klaim.nomor_klaim}-{i:02d}.jpg"
                g.save(berkas, quality=85)
                jalur.append(str(berkas))
            penyimpanan.simpan_foto(s, klaim.id, jalur, hasil.phash)

            berkas_stnk = FOLDER_FOTO / f"{klaim.nomor_klaim}-stnk.jpg"
            gambar_stnk.convert("RGB").save(berkas_stnk, quality=85)
            penyimpanan.simpan_foto(
                s, klaim.id, [str(berkas_stnk)], [None], jenis="stnk",
                mulai_urutan=len(jalur),
            )

            penyimpanan.simpan_hasil(s, klaim, hasil)
            # Tanpa baris ini klaim contoh tidak punya temuan per foto, dan cek C7 pada
            # klaim berikutnya tidak menemukan apa pun untuk dicocokkan.
            penyimpanan.simpan_temuan_foto(s, klaim.id, hasil.temuan_per_foto)

            if not foto_pertama:
                foto_pertama = gambar

            est = hasil.estimasi
            print(
                f"\n{nama} ({klaim.nomor_klaim})\n"
                f"  {keterangan}\n"
                f"  {kendaraan.nama_tampil}, {polis.nama_pemegang}\n"
                f"  validitas {hasil.verdict_validitas}, rekomendasi {est.rekomendasi}\n"
                f"  Rp {est.total_biaya:,.0f} dari harga pasar Rp {est.harga_pasar_bekas:,.0f}"
                f" ({est.total_loss_ratio:.1%})"
            )
            gagal = [c.kode for c in hasil.cek if not c.lolos]
            if gagal:
                print(f"  pemeriksaan gagal: {', '.join(gagal)}")


def _pembaca():
    """Pembaca STNK sungguhan, dimuat sekali dan dipakai ulang antar klaim."""
    global _mata
    if _mata is None:
        from app.pipeline.stnk_ocr import PembacaRapidOcr

        _mata = PembacaRapidOcr()
    return _mata


_mata = None


def _stnk_cadangan(polis: Policy, kendaraan: VehicleModel) -> HasilStnk:
    """Dipakai kalau OCR gagal membaca nomor rangka di STNK contoh.

    Klaim demo harus selalu jadi, jadi kegagalan pembacaan tidak boleh menggagalkan skrip.
    Kalau jalur ini terpakai, artinya STNK contohnya perlu dibuat lebih mudah dibaca.
    """
    print("  catatan: OCR gagal membaca nomor rangka, field diisi dari data polis")
    return HasilStnk(
        merk=kendaraan.merk, tipe=kendaraan.tipe, tahun=kendaraan.tahun,
        nomor_polisi=polis.nomor_polisi, nomor_rangka=polis.nomor_rangka,
        nomor_mesin=polis.nomor_mesin, nama_pemilik=polis.nama_pemegang,
    )


if __name__ == "__main__":
    main()
