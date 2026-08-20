"""Lapisan HTTP.

Dibangun di atas `gradio.Server`, yang mewarisi FastAPI sehingga route biasa tetap ditulis
seperti FastAPI pada umumnya. Ini satu-satunya jalur yang masih gratis di Hugging Face
setelah Docker Space jadi berbayar.

Catatan soal GPU: yang meminta GPU bukan lapisan ini, melainkan `pipeline/detektor.py`,
yang membungkus satu panggilan deteksi untuk seluruh foto satu klaim. Hanya bagian deteksi
yang masuk ke dalamnya, karena kuota dihitung dari lama fungsi berjalan, bukan dari
pemakaian GPU murni.
"""

from __future__ import annotations

import io
import logging
import os
from decimal import Decimal
from pathlib import Path

from fastapi import BackgroundTasks, Depends, Header, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import func, select

from app.agents import pencari_web
from app.api import akses, demo, penyimpanan
from app.core import auth, izin, penyedia
from app.core.berkas import Penyimpan, buat_penyimpan
from app.core.llm import KlienLLM, PenjagaAnggaran
from app.db.models import (
    AdjusterDecision,
    AppUser,
    Claim,
    ClaimPhoto,
    Policy,
    VehicleModel,
)
from app.db.repository import ambil_config_float
from app.db.session import buat_tabel, sesi
from app.laporan import estimasi_pdf, surat_pdf
from app.pipeline import stnk_ocr
from app.pipeline.detektor import Detektor, DetektorContoh
from app.pipeline.orkestrasi import STATUS_MENUNGGU_FOTO, MasukanKlaim, proses

FORMAT_DITERIMA = {"image/jpeg", "image/png"}
FOLDER_FOTO = Path(os.getenv("FOLDER_FOTO", "data/foto-klaim"))
STATUS_DIPROSES = "diproses"
STATUS_GAGAL = "gagal"

_log = logging.getLogger(__name__)


class KeputusanMasuk(BaseModel):
    keputusan: str
    catatan: str = ""


class KonfirmasiHargaMasuk(BaseModel):
    """Pengesahan harga pasar oleh adjuster, boleh sekalian mengoreksi angkanya."""

    harga_dikoreksi: Decimal | None = None


class PenilaianTemuan(BaseModel):
    temuan_id: str
    benar: bool
    alasan: str | None = None


class ReviewMasuk(BaseModel):
    penilaian: list[PenilaianTemuan]


class PenilaianStnk(BaseModel):
    field: str
    benar: bool
    nilai_benar: str | None = None


class ReviewStnkMasuk(BaseModel):
    penilaian: list[PenilaianStnk]


class LoginMasuk(BaseModel):
    username: str
    password: str


class PenggunaMasuk(BaseModel):
    peran: str | None = None
    aktif: bool | None = None


class PenggunaBaru(BaseModel):
    username: str = ""
    nama: str = ""
    peran: str = ""
    sandi: str = ""


class SandiMasuk(BaseModel):
    lama: str = ""
    baru: str = ""


class PasangDemo(BaseModel):
    asal: str = ""
    folder: str = ""
    slot: int = 1


class PeranMasuk(BaseModel):
    kode: str = ""
    nama: str = ""
    keterangan: str = ""


class IzinMasuk(BaseModel):
    izin: list[str]


def pengguna_sekarang(authorization: str = Header(default="")) -> dict:
    """Baca pengguna dari header Authorization.

    Token yang rusak, dipalsukan, atau kedaluwarsa sama-sama dijawab 401 dengan pesan yang
    sama, supaya tidak memberi petunjuk bagian mana yang perlu ditebak berikutnya.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Belum masuk")
    try:
        return auth.baca_token(authorization.removeprefix("Bearer ").strip())
    except auth.TokenTidakSah as e:
        raise HTTPException(401, str(e)) from e


def wajib_izin(kode: str):
    """Penjaga alamat. Dipasang di server, bukan cuma dengan menyembunyikan menu.

    Haknya dibaca dari database tiap permintaan, bukan dari isi token, supaya perubahan di
    layar Manajemen Akses langsung berlaku tanpa menunggu orangnya masuk ulang.

    Menu yang disembunyikan tanpa penjagaan di sini tidak menahan siapa pun yang mengetik
    alamatnya langsung.
    """

    def penjaga(saya: dict = Depends(pengguna_sekarang)) -> dict:
        with sesi() as s:
            if kode not in akses.izin_peran(s, saya.get("peran", "")):
                raise HTTPException(403, "Peran Anda tidak berhak membuka bagian ini")
        return saya

    return penjaga


POLIS_LIHAT = wajib_izin(izin.POLIS_LIHAT)
KLAIM_KIRIM = wajib_izin(izin.KLAIM_KIRIM)
KLAIM_LACAK = wajib_izin(izin.KLAIM_LACAK)
KLAIM_LIHAT = wajib_izin(izin.KLAIM_LIHAT)
KLAIM_PUTUSKAN = wajib_izin(izin.KLAIM_PUTUSKAN)
KLAIM_REVIEW = wajib_izin(izin.KLAIM_REVIEW)
KLAIM_HAPUS = wajib_izin(izin.KLAIM_HAPUS)
OVERVIEW_LIHAT = wajib_izin(izin.OVERVIEW_LIHAT)
AKSES_KELOLA = wajib_izin(izin.AKSES_KELOLA)


FOLDER_MODEL = Path(os.getenv("FOLDER_MODEL", "models"))


def jalur_model() -> tuple[Path, Path] | None:
    """Cari bobot bagian dan kerusakan, kembalikan None kalau belum lengkap.

    Tanpa variabel lingkungan, bobot dicari di `models/` sehingga menaruh berkasnya lalu
    menyalakan ulang server sudah cukup. Kedua bobot harus ada: menjalankan model bagian
    bersama deteksi kerusakan contoh menghasilkan campuran yang hasilnya tidak berarti.
    """
    part = Path(os.getenv("MODEL_PART") or FOLDER_MODEL / "part.pt")
    damage = Path(os.getenv("MODEL_DAMAGE") or FOLDER_MODEL / "damage.pt")
    return (part, damage) if part.exists() and damage.exists() else None


def buat_detektor() -> Detektor:
    """Pilih detektor sesuai ketersediaan bobot model.

    Selama model belum dilatih, detektor contoh dipakai supaya seluruh alur tetap bisa
    dijalankan dan didemokan.
    """
    jalur = jalur_model()
    if jalur is None:
        return DetektorContoh()

    from app.pipeline.detektor import DetektorYolo

    return DetektorYolo(*jalur)


def _baca_gambar(berkas: UploadFile) -> Image.Image:
    if berkas.content_type not in FORMAT_DITERIMA:
        raise HTTPException(
            400,
            f"Format {berkas.content_type} tidak didukung. Kirim foto JPG atau PNG.",
        )
    isi = berkas.file.read()
    if not isi:
        raise HTTPException(400, f"Berkas {berkas.filename} kosong")
    try:
        return Image.open(io.BytesIO(isi)).convert("RGB")
    except OSError as e:
        raise HTTPException(400, f"Berkas {berkas.filename} bukan gambar yang bisa dibaca") from e


def buat_pembaca() -> stnk_ocr.PembacaOcr:
    """Siapkan pembaca huruf untuk foto STNK.

    Sengaja gagal keras kalau pustakanya belum ada, bukan diam-diam mengisi field dari data
    polis. Field STNK yang berasal dari polis membuat pemeriksaan C5 dan C6 membandingkan
    data dengan dirinya sendiri, jadi selalu cocok dan tidak memeriksa apa pun.
    """
    try:
        return stnk_ocr.PembacaRapidOcr()
    except ImportError as e:
        raise RuntimeError(
            "Pembaca STNK butuh dependensi opsional ml. Pasang dengan: uv sync --extra ml"
        ) from e


def _simpan_overlay(s, lemari, klaim, gambar_overlay, bentuk=None) -> None:
    """Simpan gambar berlapis hasil deteksi, satu untuk tiap foto kerusakan.

    Seluruhnya ditulis ulang dari nomor nol tiap kali klaim diproses, urut sama dengan foto
    kerusakannya, supaya pasangannya bisa dicari tanpa tabel penghubung tambahan.
    """
    if not gambar_overlay:
        return
    penyimpanan.hapus_foto_jenis(s, klaim.id, "overlay")
    jalur = [
        lemari.simpan(f"{klaim.nomor_klaim}-{i:02d}-overlay.jpg", g)
        for i, g in enumerate(gambar_overlay)
    ]
    penyimpanan.simpan_foto(
        s, klaim.id, jalur, [None] * len(jalur), jenis="overlay", bentuk=bentuk,
    )


def buat_server(
    detektor: Detektor | None = None,
    pembaca: stnk_ocr.PembacaOcr | None = None,
    klien_llm: KlienLLM | None = None,
    penyimpan: Penyimpan | None = None,
    pencari: pencari_web.PencariWeb | None = None,
):
    from gradio import Server

    app = Server()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("ASAL_DIIZINKAN", "*").split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    mesin = detektor or buat_detektor()
    mata = pembaca or buat_pembaca()
    otak = klien_llm or penyedia.buat_klien()
    lemari = penyimpan or buat_penyimpan(FOLDER_FOTO)
    # Pencarian harga bisa dimatikan lewat lingkungan, misalnya di jaringan tertutup.
    # Dimatikan berarti harga yang tidak ada di katalog dinyatakan tidak diketahui, bukan
    # ditebak, dan adjuster yang mengisinya.
    mesin_cari = pencari or (
        pencari_web.PencariMati()
        if os.getenv("CARI_HARGA_WEB", "1") == "0"
        else pencari_web.PencariDuckDuckGo()
    )
    buat_tabel()

    # Tabel peran ikut dibuat otomatis, tapi isinya tidak. Tanpa isi, tidak ada satu pun
    # akun yang punya hak, jadi semua orang terkunci di luar. Diisi di sini supaya
    # database lama tetap bisa dipakai tanpa menjalankan ulang pengisian data awal, dan
    # supaya hak yang baru muncul di versi berikutnya sampai ke peran bawaan yang sudah ada.
    with sesi() as s:
        from app.db.seed import isi_peran

        peran_baru, izin_baru = isi_peran(s)
        if peran_baru or izin_baru:
            _log.info("peran bawaan dilengkapi: %s peran, %s hak", peran_baru, izin_baru)

    @app.get("/api/kesehatan")
    def kesehatan():
        """Dipanggil sebelum presentasi untuk membangunkan Space dan memuat model.

        Sekalian membaca satu gambar kosong, karena model OCR baru dimuat saat dipakai
        pertama kali dan itu memakan belasan detik. Tanpa pemanasan di sini, biaya
        pemuatan itu ditanggung klaim pertama yang dikirim di depan atasan.
        """
        mata.baca(Image.new("RGB", (64, 64), (255, 255, 255)))
        with sesi() as s:
            jumlah = s.scalar(select(Policy).limit(1))
        return {
            "siap": jumlah is not None,
            "detektor": type(mesin).__name__,
            # Dibedakan tegas dari nama kelasnya, supaya tidak ada yang menyangka deteksinya
            # sudah nyata padahal masih dibuat-buat.
            "model_asli": not isinstance(mesin, DetektorContoh),
            "llm": otak is not None,
            "pesan": "Database terisi" if jumlah else "Database belum diisi data awal",
        }

    @app.post("/api/login")
    def masuk(data: LoginMasuk):
        with sesi() as s:
            akun = s.scalar(select(AppUser).where(AppUser.username == data.username.strip()))
            # Username tidak dikenal dan sandi salah dijawab sama persis, supaya tidak
            # ketahuan username mana yang benar-benar ada.
            sah = (
                akun is not None
                and akun.aktif
                and auth.periksa_sandi(data.password, akun.garam, akun.sandi_hash)
            )
            if not sah:
                raise HTTPException(401, "Username atau kata sandi salah")

            penyimpanan.catat_audit(s, None, "auth", "masuk", {"username": akun.username})
            return {
                "token": auth.buat_token(akun.username, akun.peran),
                "username": akun.username,
                "nama": akun.nama,
                "peran": akun.peran,
                # Frontend memakai daftar ini untuk memilih menu yang tampil. Penjagaan
                # sungguhannya tetap di server, ini cuma supaya layarnya tidak menawarkan
                # halaman yang ujungnya ditolak.
                "izin": sorted(akses.izin_peran(s, akun.peran)),
            }

    @app.get("/api/saya")
    def saya(pengguna: dict = Depends(pengguna_sekarang)):
        """Dipakai frontend memulihkan sesi setelah halaman dimuat ulang."""
        with sesi() as s:
            akun = s.scalar(select(AppUser).where(AppUser.username == pengguna["sub"]))
            if akun is None or not akun.aktif:
                raise HTTPException(401, "Akun tidak aktif lagi")
            return {
                "username": akun.username,
                "nama": akun.nama,
                "peran": akun.peran,
                "izin": sorted(akses.izin_peran(s, akun.peran)),
            }

    @app.get("/api/polis/{nomor_polis}")
    def lihat_polis(nomor_polis: str, _=Depends(POLIS_LIHAT)):
        with sesi() as s:
            polis = s.scalar(select(Policy).where(Policy.nomor_polis == nomor_polis))
            if polis is None:
                raise HTTPException(404, f"Nomor polis {nomor_polis} tidak ditemukan")
            kendaraan = s.get(VehicleModel, polis.vehicle_model_id)
            return {
                "nomor_polis": polis.nomor_polis,
                "nomor_polisi": polis.nomor_polisi,
                "pemegang": polis.nama_pemegang,
                "kendaraan": kendaraan.nama_tampil,
                "tahun": kendaraan.tahun,
            }

    @app.get("/api/klaim")
    def daftar_klaim(_=Depends(KLAIM_LIHAT)):
        with sesi() as s:
            nama = penyimpanan.peta_nama_pengguna(s)
            return [
                penyimpanan.ringkasan_klaim(s, k, nama)
                for k in s.scalars(select(Claim).order_by(Claim.created_at.desc()))
            ]

    # Harus didaftarkan sebelum alamat berpola `/api/klaim/{klaim_id}`. FastAPI mencocokkan
    # menurut urutan pendaftaran, jadi kalau dibalik, "saya" terbaca sebagai id klaim.
    @app.get("/api/klaim/saya")
    def kiriman_saya(pengguna: dict = Depends(KLAIM_LACAK)):
        """Klaim untuk layar Klaim Saya.

        Yang berhak melihat seluruh klaim mendapat semuanya termasuk kirimannya sendiri,
        selain itu tersaring ke pengirimnya.
        """
        with sesi() as s:
            semua = izin.KLAIM_LIHAT in akses.izin_peran(s, pengguna.get("peran", ""))
            return penyimpanan.kiriman_saya(s, pengguna["sub"], semua=semua)

    @app.get("/api/klaim/{klaim_id}")
    def lihat_klaim(klaim_id: str, _=Depends(KLAIM_LIHAT)):
        with sesi() as s:
            klaim = s.get(Claim, klaim_id)
            if klaim is None:
                raise HTTPException(404, "Klaim tidak ditemukan")
            return penyimpanan.detail_klaim(s, klaim)

    def _proses_di_latar(
        klaim_id: str,
        gambar: list[Image.Image],
        gambar_stnk: Image.Image | None = None,
        foto_tambahan: int = 0,
    ) -> None:
        """Jalankan pipeline lengkap di luar permintaan HTTP.

        Sesinya dibuka sendiri karena fungsi ini berjalan setelah jawaban terkirim, di
        thread lain, jadi tidak boleh menumpang sesi milik permintaan tadi.

        Kalau ada yang gagal, statusnya jadi gagal. Klaim yang tertinggal selamanya di
        status diproses tanpa keterangan jauh lebih menyulitkan daripada klaim yang jelas
        gagal.
        """
        try:
            with sesi() as s:
                klaim = s.get(Claim, klaim_id)
                polis = s.get(Policy, klaim.policy_id)
                kendaraan = s.get(VehicleModel, klaim.vehicle_model_id)

                if gambar_stnk is not None:
                    baca = stnk_ocr.baca_stnk(gambar_stnk, mata)
                    penyimpanan.simpan_stnk(s, klaim.id, baca.stnk, baca.teks_mentah)
                    stnk = baca.stnk
                else:
                    stnk = penyimpanan.stnk_tersimpan(s, klaim.id)

                hasil = _jalankan(
                    s, klaim, polis, kendaraan, stnk, gambar,
                    # Pengiriman awal memeriksa seluruh fotonya. Penilaian ulang cuma
                    # memeriksa foto yang baru datang.
                    foto_sudah_diperiksa=len(gambar) - foto_tambahan if foto_tambahan else 0,
                )

                penyimpanan.perbarui_phash(s, klaim.id, hasil.phash)
                # Seluruh foto dinilai ulang tiap kali, jadi overlay dan temuannya ditulis
                # ulang dari nomor nol, bukan disambung dari yang lama.
                _simpan_overlay(s, lemari, klaim, hasil.overlay, bentuk=hasil.bentuk)
                penyimpanan.simpan_temuan_foto(s, klaim.id, hasil.temuan_per_foto)
                if foto_tambahan:
                    penyimpanan.tandai_permintaan_dipenuhi(s, klaim.id, foto_tambahan)
                penyimpanan.simpan_hasil(s, klaim, hasil)
        except Exception as e:  # noqa: BLE001
            _log.exception("pipeline gagal untuk klaim %s", klaim_id)
            with sesi() as s:
                klaim = s.get(Claim, klaim_id)
                if klaim is not None:
                    klaim.status = STATUS_GAGAL
                penyimpanan.catat_audit(
                    s, klaim_id, "pipeline", "gagal", {"sebab": str(e)}
                )

    def _jalankan(s, klaim, polis, kendaraan, stnk, gambar, foto_sudah_diperiksa=0):
        """Jalankan pipeline untuk satu klaim.

        Dipakai pengiriman awal maupun pemrosesan ulang setelah foto tambahan masuk, supaya
        tidak ada dua jalur perhitungan yang bisa berbeda diam-diam.
        """
        return proses(
            MasukanKlaim(
                foto_kerusakan=gambar,
                nomor_polis=polis.nomor_polis,
                stnk=stnk,
                polis=penyimpanan.data_polis(polis),
                nama_kendaraan=kendaraan.nama_tampil,
                harga_pasar_bekas=kendaraan.harga_pasar_bekas,
            ),
            penyimpanan.muat_referensi(s, kendaraan.id),
            mesin,
            penyimpanan.phash_klaim_lain(s, kecuali_claim_id=klaim.id),
            riwayat_polis=penyimpanan.riwayat_temuan_polis(s, klaim),
            klien_llm=otak,
            # Anggaran dibuat baru tiap klaim, jadi satu klaim boros tidak menghabiskan
            # jatah klaim berikutnya.
            penjaga=PenjagaAnggaran(),
            # Foto yang kelayakannya sudah pernah dinilai tidak diperiksa lagi. Tanpa ini,
            # foto buram yang sudah diganti tetap ditandai tiap penilaian ulang dan
            # klaimnya tidak pernah bisa keluar dari status menunggu foto.
            foto_sudah_diperiksa=foto_sudah_diperiksa,
            # Tiga alat milik agent. Sesinya ikut sesi pipeline yang sudah terbuka, jadi
            # tidak ada koneksi kedua yang dibuka di tengah pemrosesan.
            pencari=mesin_cari,
            cari_di_katalog=lambda merk, tipe, tahun: penyimpanan.harga_di_katalog(
                s, merk, tipe, tahun
            ),
            ambil_konteks=lambda: penyimpanan.konteks_untuk_agent(s, polis.id, klaim.id),
        )

    @app.get("/api/klaim/{klaim_id}/foto/{urutan}")
    def lihat_foto(
        klaim_id: str,
        urutan: int,
        jenis: str = "kerusakan",
        token: str = "",
        authorization: str = Header(default=""),
    ):
        """Kirim satu berkas foto. Surveyor juga boleh, karena perlu memeriksa foto yang
        baru saja dia kirim sebelum meninggalkan lokasi.

        Token boleh lewat query, karena tag gambar di browser tidak bisa mengirim header.
        Alamat yang memuat token bisa tercatat di log server dan riwayat browser, jadi
        untuk pemakaian sungguhan lebih baik memakai alamat berbatas waktu.
        """
        if not authorization and token:
            authorization = f"Bearer {token}"
        pengguna_sekarang(authorization)

        with sesi() as s:
            baris = s.scalar(
                select(ClaimPhoto).where(
                    ClaimPhoto.claim_id == klaim_id,
                    ClaimPhoto.jenis == jenis,
                    ClaimPhoto.urutan == urutan,
                )
            )
            if baris is None:
                raise HTTPException(404, "Foto tidak ditemukan")
            lokasi = baris.path

        gambar = lemari.buka(lokasi)
        penyangga = io.BytesIO()
        gambar.save(penyangga, format="JPEG", quality=88)
        return Response(content=penyangga.getvalue(), media_type="image/jpeg")

    @app.get("/api/klaim/{klaim_id}/estimasi.pdf")
    def estimasi_pdf_klaim(
        klaim_id: str,
        unduh: int = 0,
        token: str = "",
        authorization: str = Header(default=""),
    ):
        """Kirim estimasi perbaikan sebagai PDF.

        Token boleh lewat query dengan alasan yang sama seperti alamat foto: tab baru dan
        unduhan tidak bisa membawa header. Izinnya tetap diperiksa, jadi peran yang tidak
        boleh melihat klaim juga tidak bisa mengambil dokumennya lewat alamat ini.
        """
        if not authorization and token:
            authorization = f"Bearer {token}"
        saya = pengguna_sekarang(authorization)
        with sesi() as s:
            if izin.KLAIM_LIHAT not in akses.izin_peran(s, saya.get("peran", "")):
                raise HTTPException(403, "Peran Anda tidak berhak membuka bagian ini")

            klaim = s.get(Claim, klaim_id)
            if klaim is None:
                raise HTTPException(404, "Klaim tidak ditemukan")
            rincian = penyimpanan.detail_klaim(s, klaim)
            polis = s.get(Policy, klaim.policy_id)
            alamat = polis.alamat if polis else ""

        if not rincian.get("biaya"):
            raise HTTPException(
                404,
                "Klaim ini belum punya estimasi biaya, jadi belum ada yang bisa dicetak",
            )

        isi = estimasi_pdf.susun_pdf(rincian, alamat)
        nama = f"Estimasi-{rincian['nomor_klaim']}.pdf"
        sikap = "attachment" if unduh else "inline"
        return Response(
            content=isi,
            media_type="application/pdf",
            headers={"Content-Disposition": f'{sikap}; filename="{nama}"'},
        )

    @app.get("/api/klaim/{klaim_id}/surat.pdf")
    def surat_pdf_klaim(
        klaim_id: str,
        unduh: int = 0,
        token: str = "",
        authorization: str = Header(default=""),
    ):
        """Kirim surat perintah kerja atau penawaran beli sebagai PDF.

        Token boleh lewat query dengan alasan yang sama seperti alamat estimasi: tab baru
        dan unduhan tidak bisa membawa header.
        """
        if not authorization and token:
            authorization = f"Bearer {token}"
        saya = pengguna_sekarang(authorization)
        with sesi() as s:
            if izin.KLAIM_LIHAT not in akses.izin_peran(s, saya.get("peran", "")):
                raise HTTPException(403, "Peran Anda tidak berhak membuka bagian ini")

            klaim = s.get(Claim, klaim_id)
            if klaim is None:
                raise HTTPException(404, "Klaim tidak ditemukan")
            rincian = penyimpanan.detail_klaim(s, klaim)
            polis = s.get(Policy, klaim.policy_id)
            alamat = polis.alamat if polis else ""

        surat = rincian.get("surat")
        if not surat:
            raise HTTPException(
                404,
                "Klaim ini belum menerbitkan surat, jadi belum ada yang bisa dicetak",
            )

        if surat["jenis"] == "spk":
            isi = surat_pdf.susun_spk(rincian, surat)
            nama = f"{surat['nomor']}.pdf"
        else:
            # Penawaran ditujukan ke tertanggung, jadi alamat polis ikut tercetak.
            isi = surat_pdf.susun_penawaran(rincian, surat, alamat)
            nama = f"Penawaran-{rincian['nomor_klaim']}.pdf"

        sikap = "attachment" if unduh else "inline"
        return Response(
            content=isi,
            media_type="application/pdf",
            headers={"Content-Disposition": f'{sikap}; filename="{nama}"'},
        )

    @app.get("/api/overview")
    def ringkasan(_=Depends(OVERVIEW_LIHAT)):
        with sesi() as s:
            return penyimpanan.ringkasan_semua_klaim(s)

    @app.post("/api/klaim", status_code=202)
    async def kirim_klaim(
        nomor_polis: str,
        latar: BackgroundTasks,
        foto_stnk: UploadFile,
        foto: list[UploadFile] = (),
        foto_pelengkap: list[UploadFile] = (),
        pengguna: dict = Depends(KLAIM_KIRIM),
    ):
        """Terima klaim, simpan fotonya, lalu jawab tanpa menunggu pipeline.

        Surveyor masih di lokasi dan perlu lanjut ke mobil berikutnya, jadi dia tidak boleh
        menunggu OCR, deteksi, dan penilaian agent selesai. Hasilnya dibaca adjuster nanti.

        Foto pelengkap adalah bukti dekat seperti nomor rangka dan ruang mesin. Foto seperti
        itu tidak memuat bentuk mobil yang utuh, jadi kalau ikut dideteksi dia menghasilkan
        bagian yang salah dan bagian salah itu langsung masuk ke perhitungan biaya. Karena
        itu dia disimpan untuk dilihat adjuster, tidak pernah masuk deteksi.
        """
        with sesi() as s:
            batas_min = int(ambil_config_float(s, "min_foto_kerusakan"))
            batas_max = int(ambil_config_float(s, "max_foto_kerusakan"))
            if not (batas_min <= len(foto) <= batas_max):
                raise HTTPException(
                    400,
                    f"Kirim {batas_min} sampai {batas_max} foto kerusakan, "
                    f"yang diterima {len(foto)}",
                )

            batas_pelengkap = int(ambil_config_float(s, "max_foto_pelengkap"))
            if len(foto_pelengkap) > batas_pelengkap:
                raise HTTPException(
                    400,
                    f"Foto pelengkap paling banyak {batas_pelengkap}, "
                    f"yang diterima {len(foto_pelengkap)}",
                )

            polis = s.scalar(select(Policy).where(Policy.nomor_polis == nomor_polis))
            if polis is None:
                raise HTTPException(404, f"Nomor polis {nomor_polis} tidak ditemukan")

            kendaraan = s.get(VehicleModel, polis.vehicle_model_id)
            gambar = [_baca_gambar(f) for f in foto]
            gambar_stnk = _baca_gambar(foto_stnk)
            gambar_pelengkap = [_baca_gambar(f) for f in foto_pelengkap]

            # Nama surveyor diambil dari akun yang sedang masuk, bukan diketik, supaya
            # jejak audit menunjuk orang yang benar-benar bertanggung jawab.
            klaim = penyimpanan.buat_klaim(s, polis, kendaraan, pengguna["sub"])

            # Sidik jari fotonya masih kosong di sini, diisi pipeline nanti.
            jalur = [
                lemari.simpan(f"{klaim.nomor_klaim}-{i:02d}.jpg", g)
                for i, g in enumerate(gambar)
            ]
            penyimpanan.simpan_foto(s, klaim.id, jalur, [None] * len(jalur))

            # Foto STNK tidak diberi sidik jari, karena cek foto dipakai ulang hanya berlaku
            # untuk foto kerusakan. STNK yang sama memang wajar muncul di klaim berulang
            # dari kendaraan yang sama.
            lokasi_stnk = lemari.simpan(f"{klaim.nomor_klaim}-stnk.jpg", gambar_stnk)
            penyimpanan.simpan_foto(
                s, klaim.id, [lokasi_stnk], [None], jenis="stnk", mulai_urutan=len(jalur)
            )

            if gambar_pelengkap:
                jalur_pelengkap = [
                    lemari.simpan(f"{klaim.nomor_klaim}-pelengkap-{i:02d}.jpg", g)
                    for i, g in enumerate(gambar_pelengkap)
                ]
                penyimpanan.simpan_foto(
                    s, klaim.id, jalur_pelengkap, [None] * len(jalur_pelengkap),
                    jenis="pelengkap",
                )
            jawaban = {
                "id": klaim.id,
                "nomor_klaim": klaim.nomor_klaim,
                "status": klaim.status,
            }

        latar.add_task(_proses_di_latar, jawaban["id"], gambar, gambar_stnk)
        return jawaban

    @app.post("/api/klaim/{klaim_id}/kirim-ulang", status_code=202)
    async def kirim_ulang_klaim(
        klaim_id: str,
        latar: BackgroundTasks,
        foto: list[UploadFile] = (),
        foto_stnk: UploadFile = None,
        foto_pelengkap: list[UploadFile] = (),
        _=Depends(KLAIM_KIRIM),
    ):
        """Kirim ulang seluruh berkas klaim yang ditahan menunggu foto.

        Kiriman lamanya dihapus dan digantikan seluruhnya, foto STNK sekalian. Klaim ditahan
        justru karena kirimannya tidak layak jadi dasar keputusan, dan menyisakan satu
        berkas lama membuat klaim berdiri di atas dua kiriman yang berbeda.
        """
        with sesi() as s:
            klaim = s.get(Claim, klaim_id)
            if klaim is None:
                raise HTTPException(404, "Klaim tidak ditemukan")
            if klaim.status != STATUS_MENUNGGU_FOTO:
                raise HTTPException(
                    400,
                    f"Klaim ini tidak sedang menunggu foto, statusnya {klaim.status}",
                )
            batas_min = int(ambil_config_float(s, "min_foto_kerusakan"))
            batas_max = int(ambil_config_float(s, "max_foto_kerusakan"))
            if not (batas_min <= len(foto) <= batas_max):
                raise HTTPException(
                    400,
                    f"Kirim {batas_min} sampai {batas_max} foto kerusakan, "
                    f"yang diterima {len(foto)}",
                )

            batas_pelengkap = int(ambil_config_float(s, "max_foto_pelengkap"))
            if len(foto_pelengkap) > batas_pelengkap:
                raise HTTPException(
                    400,
                    f"Foto pelengkap paling banyak {batas_pelengkap}, "
                    f"yang diterima {len(foto_pelengkap)}",
                )

            if foto_stnk is None:
                raise HTTPException(400, "Kirim juga foto STNK-nya")

            gambar = [_baca_gambar(f) for f in foto]
            gambar_stnk = _baca_gambar(foto_stnk)
            gambar_pelengkap = [_baca_gambar(f) for f in foto_pelengkap]

            dibuang = penyimpanan.siapkan_kirim_ulang(s, klaim.id, "surveyor")
            for lokasi in dibuang:
                lemari.hapus(lokasi)

            jalur = [
                lemari.simpan(f"{klaim.nomor_klaim}-{i:02d}.jpg", g)
                for i, g in enumerate(gambar)
            ]
            penyimpanan.simpan_foto(s, klaim.id, jalur, [None] * len(jalur))

            lokasi_stnk = lemari.simpan(f"{klaim.nomor_klaim}-stnk.jpg", gambar_stnk)
            penyimpanan.simpan_foto(
                s, klaim.id, [lokasi_stnk], [None], jenis="stnk", mulai_urutan=len(jalur),
            )

            if gambar_pelengkap:
                mulai = len(penyimpanan.daftar_pelengkap(s, klaim.id))
                jalur_pelengkap = [
                    lemari.simpan(
                        f"{klaim.nomor_klaim}-pelengkap-{mulai + i:02d}.jpg", g
                    )
                    for i, g in enumerate(gambar_pelengkap)
                ]
                penyimpanan.simpan_foto(
                    s, klaim.id, jalur_pelengkap, [None] * len(jalur_pelengkap),
                    jenis="pelengkap", mulai_urutan=mulai,
                )

            klaim.status = STATUS_DIPROSES
            jawaban = {
                "id": klaim.id,
                "nomor_klaim": klaim.nomor_klaim,
                "status": klaim.status,
            }

        # Seluruh fotonya baru, jadi tidak ada yang dilewati pemeriksaan kelayakan maupun
        # pemeriksaan foto dipakai ulang.
        latar.add_task(_proses_di_latar, klaim_id, gambar, gambar_stnk, len(gambar))
        return jawaban

    @app.get("/api/klaim/{klaim_id}/status")
    def status_klaim(klaim_id: str, pengguna: dict = Depends(pengguna_sekarang)):
        """Status ringkas untuk layar surveyor.

        Sengaja tidak membawa biaya, verdict, maupun narasi. Surveyor cuma perlu tahu
        klaimnya sudah selesai diproses atau masih ditahan menunggu foto.
        """
        with sesi() as s:
            klaim = s.get(Claim, klaim_id)
            if klaim is None:
                raise HTTPException(404, "Klaim tidak ditemukan")
            # Yang diperiksa haknya, bukan nama perannya. Membandingkan nama peran membuat
            # peran buatan bernama bebas yang dibuat lewat Manajemen Akses lolos begitu saja
            # dan bisa membaca status klaim milik siapa pun.
            boleh_semua = izin.KLAIM_LIHAT in akses.izin_peran(s, pengguna.get("peran", ""))
            if not boleh_semua and klaim.surveyor != pengguna["sub"]:
                raise HTTPException(403, "Klaim ini bukan kiriman Anda")
            return {
                "id": klaim.id,
                "nomor_klaim": klaim.nomor_klaim,
                "status": klaim.status,
                "permintaan_foto": penyimpanan.permintaan_foto(s, klaim.id),
            }

    @app.delete("/api/klaim/{klaim_id}")
    def hapus_klaim(klaim_id: str, pengguna: dict = Depends(KLAIM_HAPUS)):
        with sesi() as s:
            klaim = s.get(Claim, klaim_id)
            if klaim is None:
                raise HTTPException(404, "Klaim tidak ditemukan")
            hasil = penyimpanan.hapus_klaim(s, klaim, lemari)
            penyimpanan.catat_audit(
                s, None, "admin", "klaim_dihapus", {**hasil, "oleh": pengguna["sub"]}
            )
            s.commit()
            return hasil

    @app.post("/api/klaim/{klaim_id}/review-deteksi")
    def review_deteksi(klaim_id: str, masuk: ReviewMasuk, pengguna: dict = Depends(KLAIM_REVIEW)):
        with sesi() as s:
            klaim = s.get(Claim, klaim_id)
            if klaim is None:
                raise HTTPException(404, "Klaim tidak ditemukan")
            try:
                jumlah = penyimpanan.catat_review_temuan(
                    s, klaim_id, [p.model_dump() for p in masuk.penilaian], pengguna["sub"]
                )
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            return {"dinilai": jumlah, "foto": penyimpanan.daftar_foto(s, klaim_id)}

    @app.post("/api/klaim/{klaim_id}/keputusan")
    def putuskan(klaim_id: str, masuk: KeputusanMasuk, pengguna: dict = Depends(KLAIM_PUTUSKAN)):
        if masuk.keputusan not in {"setuju", "tolak", "revisi"}:
            raise HTTPException(400, "Keputusan harus setuju, tolak, atau revisi")

        with sesi() as s:
            klaim = s.get(Claim, klaim_id)
            if klaim is None:
                raise HTTPException(404, "Klaim tidak ditemukan")
            # Penanda tangan keputusan diambil dari akun yang masuk. Nama yang bisa diketik
            # bebas tidak ada gunanya sebagai jejak audit.
            try:
                return penyimpanan.catat_keputusan(
                    s, klaim, masuk.keputusan, masuk.catatan, pengguna["sub"]
                )
            except (
                penyimpanan.HargaBelumDikonfirmasi,
                penyimpanan.ReviewBelumLengkap,
                penyimpanan.CatatanWajib,
            ) as e:
                raise HTTPException(400, str(e)) from e

    @app.post("/api/klaim/{klaim_id}/review-stnk")
    def review_stnk(
        klaim_id: str, masuk: ReviewStnkMasuk, pengguna: dict = Depends(KLAIM_REVIEW)
    ):
        """Catat benar atau salahnya tiap field hasil baca STNK.

        Koreksinya tidak menjalankan ulang cek validitas. Cek yang membandingkan STNK ke
        polis sudah menghasilkan verdict yang dilihat orang, dan verdict itu tidak boleh
        berubah karena isian yang datang setelahnya.
        """
        with sesi() as s:
            klaim = s.get(Claim, klaim_id)
            if klaim is None:
                raise HTTPException(404, "Klaim tidak ditemukan")
            try:
                jumlah = penyimpanan.catat_review_stnk(
                    s, klaim_id, [p.model_dump() for p in masuk.penilaian], pengguna["sub"]
                )
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            return {"dinilai": jumlah, "review_stnk": penyimpanan.review_stnk(s, klaim_id)}

    def _tolak_kalau_sudah_diputuskan(s, klaim_id: str) -> None:
        sudah = s.scalar(
            select(func.count())
            .select_from(AdjusterDecision)
            .where(AdjusterDecision.claim_id == klaim_id)
        )
        if sudah:
            raise HTTPException(
                400,
                "Klaim ini sudah diputuskan. Batalkan keputusannya lebih dulu sebelum "
                "mengubah penilaiannya.",
            )

    @app.delete("/api/klaim/{klaim_id}/review-deteksi")
    def batalkan_review_deteksi(klaim_id: str, pengguna: dict = Depends(KLAIM_REVIEW)):
        """Tarik penilaian temuan supaya bisa diisi ulang.

        Ditolak kalau klaimnya sudah diputuskan. Penilaian itu dasar keputusannya, jadi
        keputusannya harus dibatalkan lebih dulu sebelum dasarnya boleh diubah.
        """
        with sesi() as s:
            klaim = s.get(Claim, klaim_id)
            if klaim is None:
                raise HTTPException(404, "Klaim tidak ditemukan")
            _tolak_kalau_sudah_diputuskan(s, klaim_id)
            try:
                jumlah = penyimpanan.batalkan_review_temuan(s, klaim_id, pengguna["sub"])
            except penyimpanan.ReviewBelumAda as e:
                raise HTTPException(400, str(e)) from e
            return {"dibatalkan": jumlah, "review_kurang": penyimpanan.review_belum_lengkap(
                s, klaim_id
            )}

    @app.delete("/api/klaim/{klaim_id}/review-stnk")
    def batalkan_review_stnk(klaim_id: str, pengguna: dict = Depends(KLAIM_REVIEW)):
        """Tarik penilaian STNK supaya bisa diisi ulang."""
        with sesi() as s:
            klaim = s.get(Claim, klaim_id)
            if klaim is None:
                raise HTTPException(404, "Klaim tidak ditemukan")
            _tolak_kalau_sudah_diputuskan(s, klaim_id)
            try:
                jumlah = penyimpanan.batalkan_review_stnk(s, klaim_id, pengguna["sub"])
            except penyimpanan.ReviewBelumAda as e:
                raise HTTPException(400, str(e)) from e
            return {"dibatalkan": jumlah, "review_kurang": penyimpanan.review_belum_lengkap(
                s, klaim_id
            )}

    @app.delete("/api/klaim/{klaim_id}/keputusan")
    def batalkan(klaim_id: str, pengguna: dict = Depends(KLAIM_PUTUSKAN)):
        """Tarik kembali keputusan yang sudah diambil, supaya klaim bisa diputuskan ulang.

        Dijaga izin yang sama dengan pengambilan keputusan: yang boleh menandatangani
        keputusan adalah yang boleh menariknya.
        """
        with sesi() as s:
            klaim = s.get(Claim, klaim_id)
            if klaim is None:
                raise HTTPException(404, "Klaim tidak ditemukan")
            try:
                return penyimpanan.batalkan_keputusan(s, klaim, pengguna["sub"])
            except penyimpanan.KeputusanBelumAda as e:
                raise HTTPException(400, str(e)) from e

    @app.post("/api/klaim/{klaim_id}/konfirmasi-harga")
    def konfirmasi_harga(
        klaim_id: str, masuk: KonfirmasiHargaMasuk, pengguna: dict = Depends(KLAIM_PUTUSKAN)
    ):
        """Sahkan harga pasar bekas, boleh sekalian mengoreksi angkanya.

        Dijaga izin yang sama dengan pengambilan keputusan, karena inilah tanda tangan atas
        angka yang menentukan total loss dan besar penawaran beli kendaraan.
        """
        if masuk.harga_dikoreksi is not None and masuk.harga_dikoreksi <= 0:
            raise HTTPException(400, "Harga koreksi harus lebih besar dari nol")

        with sesi() as s:
            klaim = s.get(Claim, klaim_id)
            if klaim is None:
                raise HTTPException(404, "Klaim tidak ditemukan")
            penyimpanan.koreksi_harga_pasar(
                s, klaim, masuk.harga_dikoreksi, pengguna["sub"]
            )
            return penyimpanan.detail_klaim(s, klaim)["biaya"]

    @app.delete("/api/klaim/{klaim_id}/konfirmasi-harga")
    def batalkan_konfirmasi_harga(klaim_id: str, pengguna: dict = Depends(KLAIM_PUTUSKAN)):
        """Tarik pengesahan harga pasar, supaya angkanya bisa diperiksa ulang.

        Ditolak kalau klaimnya sudah diputuskan, karena harga itu sudah jadi dasar surat
        yang terbit. Batalkan keputusannya lebih dulu, baru harganya bisa dibuka lagi.
        """
        with sesi() as s:
            klaim = s.get(Claim, klaim_id)
            if klaim is None:
                raise HTTPException(404, "Klaim tidak ditemukan")
            sudah = s.scalar(
                select(func.count())
                .select_from(AdjusterDecision)
                .where(AdjusterDecision.claim_id == klaim_id)
            )
            if sudah:
                raise HTTPException(
                    400,
                    "Klaim ini sudah diputuskan. Batalkan keputusannya lebih dulu sebelum "
                    "membuka kembali harganya.",
                )
            try:
                penyimpanan.batalkan_konfirmasi_harga(s, klaim, pengguna["sub"])
            except penyimpanan.PengesahanBelumAda as e:
                raise HTTPException(400, str(e)) from e
            return penyimpanan.detail_klaim(s, klaim)["biaya"]

    @app.get("/api/akses/pengguna")
    def akses_pengguna(_=Depends(AKSES_KELOLA)):
        with sesi() as s:
            return akses.daftar_pengguna(s)

    @app.post("/api/akses/pengguna")
    def akses_buat_pengguna(masuk: PenggunaBaru, pengguna: dict = Depends(AKSES_KELOLA)):
        with sesi() as s:
            try:
                hasil = akses.buat_pengguna(
                    s, masuk.username, masuk.nama, masuk.peran, masuk.sandi,
                    pengguna["sub"],
                )
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            s.commit()
            return hasil

    @app.post("/api/akses/pengguna/{username}")
    def akses_ubah_pengguna(
        username: str, masuk: PenggunaMasuk, pengguna: dict = Depends(AKSES_KELOLA)
    ):
        with sesi() as s:
            try:
                if masuk.peran is not None:
                    hasil = akses.ubah_peran_pengguna(s, username, masuk.peran, pengguna["sub"])
                elif masuk.aktif is not None:
                    hasil = akses.ubah_aktif_pengguna(s, username, masuk.aktif, pengguna["sub"])
                else:
                    raise HTTPException(400, "Tidak ada yang diubah")
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            s.commit()
            return hasil

    @app.delete("/api/akses/pengguna/{username}")
    def akses_hapus_pengguna(username: str, pengguna: dict = Depends(AKSES_KELOLA)):
        with sesi() as s:
            try:
                hasil = akses.hapus_pengguna(s, username, pengguna["sub"])
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            s.commit()
            return hasil

    @app.post("/api/akses/pengguna/{username}/reset-sandi")
    def akses_reset_sandi(username: str, pengguna: dict = Depends(AKSES_KELOLA)):
        with sesi() as s:
            try:
                hasil = akses.reset_sandi(s, username, pengguna["sub"])
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            s.commit()
            return hasil

    # Mengganti sandi sendiri tidak butuh hak apa pun selain sudah masuk, karena yang
    # diubah cuma akun pemanggilnya sendiri.
    @app.post("/api/sandi")
    def ubah_sandi(masuk: SandiMasuk, pengguna: dict = Depends(pengguna_sekarang)):
        with sesi() as s:
            try:
                hasil = akses.ubah_sandi_sendiri(s, pengguna["sub"], masuk.lama, masuk.baru)
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            s.commit()
            return hasil

    @app.get("/api/akses/peran")
    def akses_peran(_=Depends(AKSES_KELOLA)):
        with sesi() as s:
            return {"peran": akses.daftar_peran(s), "katalog_izin": izin.KATALOG}

    @app.post("/api/akses/peran")
    def akses_buat_peran(masuk: PeranMasuk, pengguna: dict = Depends(AKSES_KELOLA)):
        with sesi() as s:
            try:
                hasil = akses.buat_peran(
                    s, masuk.kode, masuk.nama, masuk.keterangan, pengguna["sub"]
                )
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            s.commit()
            return hasil

    @app.put("/api/akses/peran/{kode}")
    def akses_ubah_peran(kode: str, masuk: PeranMasuk, pengguna: dict = Depends(AKSES_KELOLA)):
        with sesi() as s:
            try:
                hasil = akses.ubah_peran(s, kode, masuk.nama, masuk.keterangan, pengguna["sub"])
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            s.commit()
            return hasil

    @app.delete("/api/akses/peran/{kode}")
    def akses_hapus_peran(kode: str, pengguna: dict = Depends(AKSES_KELOLA)):
        with sesi() as s:
            try:
                hasil = akses.hapus_peran(s, kode, pengguna["sub"])
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            s.commit()
            return hasil

    @app.put("/api/akses/peran/{kode}/izin")
    def akses_atur_izin(kode: str, masuk: IzinMasuk, pengguna: dict = Depends(AKSES_KELOLA)):
        with sesi() as s:
            try:
                hasil = akses.atur_izin_peran(s, kode, masuk.izin, pengguna["sub"])
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            s.commit()
            return hasil

    # Alat bantu menyiapkan video demo. Menyalin foto ke folder skenario lewat layar,
    # bukan lewat penjelajah berkas, karena aturan penamaannya mudah keliru.
    @app.get("/api/demo/target")
    def demo_target(_=Depends(AKSES_KELOLA)):
        return demo.daftar_target()

    @app.post("/api/demo/pasang")
    def demo_pasang(masuk: PasangDemo, pengguna: dict = Depends(AKSES_KELOLA)):
        try:
            ditulis = demo.pasang(masuk.asal, masuk.folder, masuk.slot)
        except demo.TargetTidakSah as e:
            raise HTTPException(400, str(e)) from e
        with sesi() as s:
            penyimpanan.catat_audit(
                s, None, "demo", "foto_demo_dipasang",
                {"asal": masuk.asal, "tujuan": ditulis, "oleh": pengguna["sub"]},
            )
            s.commit()
        return {"ditulis": ditulis}

    @app.get("/api/akses/log")
    def akses_log(_=Depends(AKSES_KELOLA)):
        with sesi() as s:
            return akses.log_aktivitas(s)

    return app


if __name__ == "__main__":
    buat_server().launch(server_name="0.0.0.0", server_port=7860)
