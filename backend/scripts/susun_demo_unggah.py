"""Susun folder demo siap unggah, satu folder per skenario.

Saat demo cukup buka satu folder, pilih semua foto kerusakan, pilih STNK-nya, kirim. Tidak
perlu mencocok-cocokkan berkas dari dua folder berbeda.

Foto mobilnya diambil dari dataset Kaggle yang sudah terunduh, dikelompokkan berdasarkan
kemiripan warna dan sebaran terang supaya satu folder tidak terlihat seperti empat mobil
yang tidak berhubungan. Kemiripan ini pendekatan, bukan mobil yang sama: dataset itu memuat
998 mobil dengan satu foto per mobil, dan setelah seluruh pasangan diukur cuma ada 2 pasang
yang mirip. Folder mobil sungguhan dari klien yang isinya benar-benar satu mobil ditangani
terpisah dan fotonya tidak pernah disentuh skrip ini.

Jawaban benar seluruh STNK ditulis ke `jawaban.json` di akar folder, supaya pengukuran
akurasi pembaca field tetap bisa dijalankan setelah `stnk-sintetis` digabung ke sini.

Jalankan dari folder backend:

    uv run python scripts/susun_demo_unggah.py
    uv run python scripts/susun_demo_unggah.py --foto 5
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from app.db.session import buat_tabel, sesi
from app.pipeline.stnk_dataset import dengan_kesalahan, kumpulkan_dari_database
from app.pipeline.stnk_generator import buat_stnk

AKAR = Path(__file__).resolve().parent.parent
KAGGLE = AKAR / "data" / "kaggle"
TUJUAN = AKAR / "data" / "foto-klaim-n-stnk"
LAMA = AKAR / "data" / "stnk-sintetis"

GAMBAR = {".jpg", ".jpeg", ".png"}

# Folder foto sungguhan dari klien. Isinya tidak dibangkitkan skrip ini, cuma dilengkapi
# STNK dan keterangannya, dan tidak pernah ikut dihapus saat folder demo disusun ulang.
FOLDER_RIIL = "6 - contoh-riil-1-mobil"
POLIS_RIIL = "POL-2025-0177"

# Folder yang fotonya diambil ulang dari folder klaim normal, supaya pemeriksaan foto
# dipakai ulang punya pembanding yang benar-benar sama berkasnya.
FOLDER_NORMAL = "0 - klaim normal"
FOLDER_ULANG = "1 - foto-dipakai-ulang"

# Folder yang fotonya sengaja diburamkan, untuk memicu permintaan foto ulang.
FOLDER_BURAM = "2 - foto-buram-minta-ulang"
RADIUS_BURAM = 3.0

# nama folder, nomor polis, kesalahan yang disengaja, tingkat kerusakan gambar STNK,
# jumlah foto, keterangan hasil yang diharapkan
#
# Hampir semua folder cukup satu foto, karena yang diujinya STNK atau jalur harga, bukan
# kelengkapan bukti. Satu foto juga berarti satu folder benar-benar satu mobil, sehingga
# tidak lagi terlihat janggal satu STNK disertai beberapa mobil yang berbeda.
# Sepasang folder pada satu polis yang sama, dipakai memicu cek C7. Folder pertama dikirim
# lebih dulu sebagai klaim biasa, folder kedua menyusul dan kerusakannya dikenali sebagai
# kerusakan yang sudah pernah diklaim. Keduanya harus satu polis, karena C7 mencari
# riwayat per polis, bukan per foto.
FOLDER_KLAIM_PERTAMA = "7 - klaim-pertama-mobil-yang-sama"
FOLDER_DIKLAIM_ULANG = "8 - kerusakan-lama-diklaim-ulang"
POLIS_BERPASANGAN = "POL-2025-0203"

# Foto yang dipatok per folder, ditulis dengan nama berkasnya di dataset. Dipatok karena
# tiap folder harus memperlihatkan kerusakan tertentu, bukan mobil acak yang kebetulan
# terpilih dan kebetulan cocok.
#
# Folder 7 dan 8 dipilih dengan mengukur hasil deteksinya, bukan dilihat sekilas. Keduanya
# menghasilkan Front-door sisi kanan Broken part dengan rasio luas 11.7% dan 12.1%, cukup
# dekat untuk dikenali C7 sebagai kerusakan yang sama, sementara berkasnya berbeda sehingga
# C2 tidak ikut menyalak. Mengganti salah satunya berarti mengukur ulang pasangannya, dan
# yang diukur harus bagian, sisi, jenis kerusakan, dan rasio luas sekaligus. Sisi yang beda
# sudah cukup membuat C7 diam meski rasionya rapat, dan diamnya tidak terlihat sebagai
# kegagalan saat didemokan.
FOTO_FOLDER = {
    FOLDER_NORMAL: [
        "Car damages 777.png",   # Broken part
        "Car damages 619.png",   # Dent
        "Car damages 281.png",   # Missing part
        "Car damages 610.png",   # Scratch
    ],
    "3 - stnk-sulit-dibaca": ["Car damages 495.png"],
    "4 - stnk-polis-lain": ["Car damages 505.png"],
    "5 - harga-tidak-ada-di-database": ["Car damages 997.png"],
    FOLDER_KLAIM_PERTAMA: ["Car damages 709.png"],
    FOLDER_DIKLAIM_ULANG: ["Car damages 608.png"],
}

# Seluruh foto yang dipatok dikeluarkan dari pengundian folder yang belum dipatok. Tanpa
# itu ada peluang satu foto muncul di dua folder dan C2 menyalak pada skenario yang tidak
# mengujinya. Dua nama terakhir dipakai skrip klaim contoh, bukan folder di sini.
FOTO_DIPATOK = {n for daftar in FOTO_FOLDER.values() for n in daftar} | {
    "Car damages 759.png",   # klaim contoh perbaikan biasa
    "Car damages 1344.png",  # klaim contoh total loss
}

SKENARIO = [
    (
        FOLDER_NORMAL,
        "POL-2024-0037",
        None,
        0.4,
        4,
        (
            "Semua pemeriksaan lolos, validitas valid, klaim langsung siap direview. "
            "Empat fotonya dipilih supaya keempat jenis kerusakan yang dikenal sistem "
            "muncul semua, jadi tabel biayanya memperlihatkan keempat jalur perbaikan "
            "sekaligus."
        ),
    ),
    (
        FOLDER_ULANG,
        "POL-2024-0245",
        None,
        0.4,
        1,
        (
            f"Fotonya sama persis dengan foto pertama folder {FOLDER_NORMAL}. Kirim "
            "folder itu lebih dulu, baru folder ini. Pemeriksaan C2 menangkap foto yang "
            "dipakai ulang, validitas jadi invalid. Ini yang menangkap klaim ganda "
            "memakai foto lama."
        ),
    ),
    (
        FOLDER_BURAM,
        "POL-2024-0245",
        None,
        0.4,
        1,
        (
            "Fotonya sengaja diburamkan. Sistem menandainya belum layak dibaca lalu "
            "meminta foto ulang, jadi statusnya Menunggu foto tambahan, bukan ditolak. "
            "Surveyor mengunggah penggantinya lewat menu Klaim Saya, dan klaimnya "
            "dinilai ulang otomatis."
        ),
    ),
    (
        "3 - stnk-sulit-dibaca",
        "POL-2025-0008",
        None,
        # Angka ini duduk di tebing, dan itu disengaja. Pembaca field tidak menurun
        # bertahap: sedikit di bawah nilai ini seluruh field masih terbaca hampir sempurna,
        # tepat di sini pendeteksi teks tidak menemukan satu kotak pun. Mengubah angkanya
        # atau generatornya berarti mengukur ulang lewat scripts/ukur_ocr_stnk.py, karena
        # yang membedakan gagal total dengan terbaca penuh cuma beberapa persepuluh.
        3.3,
        1,
        (
            "STNK-nya sengaja dibuat sampai tidak terbaca: miring, buram, berbayang. "
            "Kemiringannya merusak susunan baris, jadi tulisannya sebagian terbaca tapi "
            "masuk ke field yang salah, misalnya nomor rangka terisi Isi Silinder. "
            "Akibatnya C5 dan C6 dua-duanya gagal keras dan klaimnya invalid. Dipakai "
            "memperlihatkan bahwa hasil baca AI wajib diperiksa adjuster, bukan langsung "
            "dipercaya."
        ),
    ),
    (
        "4 - stnk-polis-lain",
        "POL-2024-0112",
        "nomor_rangka_beda",
        0.4,
        1,
        (
            "Nomor rangka di STNK berbeda dengan yang tercatat di polis. Pemeriksaan C6 "
            "gagal keras, validitas jadi invalid."
        ),
    ),
    (
        FOLDER_KLAIM_PERTAMA,
        POLIS_BERPASANGAN,
        None,
        0.4,
        1,
        (
            "Klaim biasa yang semua pemeriksaannya lolos. Gunanya jadi riwayat untuk "
            f"folder {FOLDER_DIKLAIM_ULANG}, jadi folder ini harus dikirim lebih dulu."
        ),
    ),
    (
        FOLDER_DIKLAIM_ULANG,
        POLIS_BERPASANGAN,
        None,
        0.4,
        1,
        (
            "Mobil yang sama, kerusakan yang sama di pintu depan kanan, tapi diajukan "
            f"sebagai klaim baru. Kirim folder {FOLDER_KLAIM_PERTAMA} lebih dulu. "
            "Pemeriksaan C7 mengenali kerusakannya sudah pernah diklaim, dan baris "
            "tabelnya langsung terpilih Tidak dijamin lengkap dengan nomor klaim "
            "sebelumnya. Angka biayanya tidak berubah, sistem cuma menandai."
        ),
    ),
    (
        "5 - harga-tidak-ada-di-database",
        "POL-2025-0141",
        None,
        0.4,
        1,
        (
            "Kendaraannya tidak ada di katalog harga, jadi agent mencari harga pasar "
            "bekasnya sendiri di internet. Di halaman adjuster muncul kartu peringatan "
            "berisi tautan sumbernya, dan tombol Setujui mati sampai harganya disahkan."
        ),
    ),
]


def sidik_warna(berkas: Path) -> np.ndarray | None:
    """Ringkas satu gambar jadi angka pendek supaya bisa dibandingkan kemiripannya.

    Yang dipotong bagian tengahnya saja, karena tepi gambar berisi lantai bengkel, tembok,
    dan langit yang mirip di hampir semua foto sehingga justru mengaburkan bedanya. Warna
    rata-rata diberi bobot jauh lebih besar daripada polanya, sebab yang paling terlihat
    janggal saat demo adalah satu folder berisi mobil biru bersama tiga mobil perak.
    """
    try:
        with Image.open(berkas) as img:
            rgb = img.convert("RGB")
            lebar, tinggi = rgb.size
            tengah = rgb.crop((
                int(lebar * 0.2), int(tinggi * 0.2),
                int(lebar * 0.8), int(tinggi * 0.8),
            ))
            kecil = tengah.resize((8, 8))
    except OSError:
        return None
    a = np.asarray(kecil, dtype=np.float32) / 255.0
    warna = a.mean(axis=(0, 1))
    # Selisih antar kanal menangkap corak warnanya, bukan cuma terang gelapnya, sehingga
    # perak dan biru muda yang kecerahannya mirip tetap terpisah.
    corak = np.array([warna[0] - warna[1], warna[1] - warna[2], warna[0] - warna[2]])
    pola = a.mean(axis=2).ravel()
    return np.concatenate([warna * 6.0, corak * 12.0, pola])


def buramkan(asal: Path, tujuan: Path) -> None:
    """Salin foto sambil diburamkan, untuk memicu permintaan foto ulang saat demo.

    Dibangkitkan skrip, bukan disiapkan tangan, supaya folder demonya ikut tersusun ulang
    setiap kali skrip ini dijalankan dan tidak ada berkas yatim yang harus dijaga sendiri.
    """
    with Image.open(asal) as img:
        img.convert("RGB").filter(ImageFilter.GaussianBlur(RADIUS_BURAM)).save(
            tujuan, quality=88
        )


def kumpulan_foto(per_folder: list[int], rng: random.Random) -> list[list[Path]]:
    """Ambil foto untuk tiap folder, sebanyak yang diminta folder itu.

    Folder yang butuh lebih dari satu foto diisi mobil yang paling mirip warnanya, dengan
    cara serakah dan sederhana: satu foto acak jadi jangkar, lalu beberapa foto terdekat
    menurut sidik warnanya. Tidak optimal, tapi cukup supaya foldernya tidak terlihat
    seperti kumpulan mobil acak.
    """
    semua = sorted(
        p
        for p in KAGGLE.rglob("*")
        if p.suffix.lower() in GAMBAR
        and not p.parent.name.lower().startswith("mask")
        and p.name not in FOTO_DIPATOK
    )
    total = sum(per_folder)
    if len(semua) < total:
        raise SystemExit(f"Foto di {KAGGLE} tidak cukup, cuma ada {len(semua)}")

    rng.shuffle(semua)
    # Cukup ambil sebagian supaya menghitung sidiknya tidak memakan waktu lama.
    calon = semua[: max(400, total * 12)]
    sidik = {p: s for p in calon if (s := sidik_warna(p)) is not None}

    kelompok: list[list[Path]] = []
    tersisa = list(sidik)
    for jumlah in per_folder:
        jangkar = tersisa.pop(rng.randrange(len(tersisa)))
        jarak = sorted(tersisa, key=lambda p: float(np.linalg.norm(sidik[p] - sidik[jangkar])))
        dekat = jarak[: jumlah - 1]
        for p in dekat:
            tersisa.remove(p)
        kelompok.append([jangkar, *dekat])
    return kelompok


def susun_mobil_riil(dasar: dict, rng: random.Random) -> dict | None:
    """Lengkapi folder foto sungguhan dari klien dengan STNK yang cocok.

    Fotonya tidak pernah disentuh, ditimpa, maupun dihapus. Yang ditulis skrip cuma STNK
    dan keterangannya, karena foto ini satu-satunya bahan yang tidak bisa dibangkitkan
    ulang kalau hilang.
    """
    folder = TUJUAN / FOLDER_RIIL
    if not folder.is_dir():
        return None
    if POLIS_RIIL not in dasar:
        print(f"Polis {POLIS_RIIL} belum ada, folder mobil riil dilewati", file=sys.stderr)
        return None

    ai = sorted(p for p in folder.iterdir() if p.stem.startswith("ai-"))
    pelengkap = sorted(p for p in folder.iterdir() if p.stem.startswith("pelengkap-"))

    contoh = dasar[POLIS_RIIL]
    buat_stnk(contoh.data, rng=rng, tingkat_kerusakan=0.5).save(
        folder / "stnk.jpg", quality=88
    )

    (folder / "keterangan.txt").write_text(
        "\n".join([
            f"Skenario: {FOLDER_RIIL}",
            f"Nomor polis: {POLIS_RIIL}",
            "",
            "Ini satu-satunya folder yang isinya benar-benar satu mobil: Toyota Kijang",
            "Innova putih, plat H 1052 BA, foto dari klien. Folder lain memakai foto",
            "fixture dari mobil yang berbeda-beda.",
            "",
            "Cara memakai:",
            f"  1. Buka menu Ajukan Klaim, isi nomor polis {POLIS_RIIL}",
            f"  2. Kotak foto kerusakan: pilih {len(ai)} berkas ai-*.jpeg",
            f"  3. Kotak foto pelengkap: pilih {len(pelengkap)} berkas pelengkap-*.jpeg",
            "  4. Pilih stnk.jpg di folder ini",
            "  5. Kirim klaim",
            "",
            "Kenapa dipisah dua kotak:",
            "  Berkas ai-* memperlihatkan seluruh badan mobil, jadi model punya konteks",
            "  untuk mengenali bagiannya. Berkas pelengkap-* diambil dari jarak sangat",
            "  dekat, sebagian cuma rangka dan puing di aspal. Foto seperti itu kalau ikut",
            "  dideteksi menghasilkan bagian yang salah, dan bagian salah itu langsung",
            "  masuk ke perhitungan biaya. Di kotak pelengkap dia tetap sampai ke adjuster",
            "  sebagai bukti, tanpa menyentuh angka.",
            "",
            "Catatan penting:",
            "  Inilah folder yang paling jujur menguji modelnya, karena fotonya diambil",
            "  di bengkel sungguhan, bukan dari dataset yang mirip data latih. Kualitas",
            "  deteksinya baru ketahuan setelah bobot Kaggle terpasang.",
        ]),
        encoding="utf-8",
    )
    print(f"{FOLDER_RIIL}: {len(ai)} foto AI + {len(pelengkap)} pelengkap + stnk.jpg")
    return {
        "berkas": f"{FOLDER_RIIL}/stnk.jpg",
        "nomor_polis": contoh.nomor_polis,
        "sengaja_salah": contoh.sengaja_salah,
        "jawaban_benar": contoh.jawaban_benar,
    }


def susun_uji_ocr(dasar: dict, rng: random.Random, jumlah: int) -> list[dict]:
    """Susun kumpulan STNK bertingkat kesulitan, terpisah dari folder demo.

    Folder demo sengaja cuma berisi satu STNK per skenario supaya gampang dipakai saat
    presentasi. Tapi mengukur akurasi pembaca field butuh lebih banyak berkas dan butuh
    tingkat kesulitan yang berjenjang, dari yang mudah dibaca sampai yang memang sulit.
    Keduanya dipisah supaya tidak saling mengganggu.
    """
    folder = TUJUAN / "uji-ocr"
    folder.mkdir()

    tingkat = [0.3, 0.7, 1.0, 1.4]
    polis = sorted(dasar)
    hasil = []

    for i in range(jumlah):
        contoh = dasar[polis[i % len(polis)]]
        # Sekitar seperempat dibuat sengaja tidak cocok, supaya pemeriksaan kecurangan
        # punya bahan uji yang gagal, bukan cuma bahan yang lolos.
        if i % 4 == 3:
            contoh = dengan_kesalahan(contoh, "nomor_rangka_beda", rng)
        nama = f"stnk-{i:03d}-{contoh.data.nomor_registrasi.replace(' ', '')}.jpg"
        gambar = buat_stnk(contoh.data, rng=rng, tingkat_kerusakan=tingkat[i % len(tingkat)])
        gambar.save(folder / nama, quality=88)
        hasil.append({
            "berkas": f"uji-ocr/{nama}",
            "nomor_polis": contoh.nomor_polis,
            "sengaja_salah": contoh.sengaja_salah,
            "jawaban_benar": contoh.jawaban_benar,
        })

    (folder / "keterangan.txt").write_text(
        "\n".join([
            "Kumpulan uji akurasi pembaca field STNK, bukan bahan demo.",
            "",
            f"{jumlah} berkas dengan tingkat kesulitan berjenjang: {tingkat}.",
            "Jawaban benarnya ada di jawaban.json satu tingkat di atas folder ini.",
            "",
            "Ukur dengan:",
            "  uv run --extra ml python scripts/ukur_ocr_stnk.py",
        ]),
        encoding="utf-8",
    )
    print(f"uji-ocr: {jumlah} STNK bertingkat kesulitan")
    return hasil


def main() -> int:
    p = argparse.ArgumentParser(description="Susun folder demo siap unggah")
    p.add_argument("--uji", type=int, default=12, help="jumlah STNK untuk mengukur akurasi")
    p.add_argument("--seed", type=int, default=2026)
    args = p.parse_args()

    if not KAGGLE.exists():
        print(f"Dataset tidak ada di {KAGGLE}", file=sys.stderr)
        return 1

    rng = random.Random(args.seed)
    buat_tabel()

    with sesi() as s:
        dasar = {c.nomor_polis: c for c in kumpulkan_dari_database(s, rng)}

    kurang = [nomor for _, nomor, *_ in SKENARIO if nomor not in dasar]
    if kurang:
        print(f"Polis belum ada di database: {kurang}. Jalankan isi_data_awal.py dulu.",
              file=sys.stderr)
        return 1

    # Yang dibuang cuma yang memang dibangkitkan skrip ini: folder skenario bernomor,
    # kumpulan uji OCR, dan jawaban.json. Folder mobil riil berisi foto milik klien yang
    # tidak bisa dibangkitkan ulang, dan folder lain seperti kandidat foto atau hasil
    # inference milik alat bantu lain, jadi ketiganya tidak boleh ikut terhapus.
    #
    # Folder bernomor lama ikut dibuang meski namanya sudah tidak ada di SKENARIO, supaya
    # penomoran yang berubah tidak meninggalkan folder yatim.
    TUJUAN.mkdir(parents=True, exist_ok=True)
    bernomor = re.compile(r"^\d+ - ")
    for anak in TUJUAN.iterdir():
        if anak.name == FOLDER_RIIL:
            continue
        if anak.is_dir() and (bernomor.match(anak.name) or anak.name == "uji-ocr"):
            shutil.rmtree(anak)
        elif anak.name == "jawaban.json":
            anak.unlink()

    # Undiannya tetap meminta jatah untuk folder yang dipatok, meski jatahnya tidak dipakai.
    # Kalau jatahnya dihapus, folder yang belum dipatok kebagian foto yang berbeda dan
    # tampilan demo ikut berubah tanpa ada yang memintanya.
    kelompok = kumpulan_foto([s[4] for s in SKENARIO], rng)
    berkas_kaggle = {
        p.name: p
        for p in KAGGLE.rglob("*")
        if p.suffix.lower() in GAMBAR and not p.parent.name.lower().startswith("mask")
    }
    hilang = sorted(
        n for daftar in FOTO_FOLDER.values() for n in daftar if n not in berkas_kaggle
    )
    if hilang:
        print(f"Foto yang dipatok tidak ada di dataset: {hilang}", file=sys.stderr)
        return 1
    # Folder demo dibangun dari `SKENARIO`, kumpulan uji OCR dari seluruh polis di database.
    dasar_semua = dict(dasar)
    jawaban = []
    foto_normal: list[Path] = []

    for (nama, nomor_polis, salah, tingkat, _jumlah, keterangan), foto in zip(
        SKENARIO, kelompok, strict=True
    ):
        folder = TUJUAN / nama
        folder.mkdir()

        # Skenario foto dipakai ulang harus memakai berkas yang sama persis dengan folder
        # wajar, kalau tidak pemeriksaan C2 tidak punya apa pun untuk ditangkap.
        # Folder klaim normal memakai empat foto, folder ini cuma satu, jadi yang diambil
        # sebanyak yang memang dibutuhkannya saja.
        if nama == FOLDER_ULANG:
            sumber = foto_normal[: len(foto)]
        elif nama in FOTO_FOLDER:
            sumber = [berkas_kaggle[n] for n in FOTO_FOLDER[nama]]
        else:
            sumber = foto
        for i, asal in enumerate(sumber, start=1):
            tujuan = folder / f"kerusakan-{i:02d}{asal.suffix.lower()}"
            # Foto terakhir di folder buram diburamkan, sisanya disalin apa adanya, supaya
            # yang terlihat saat demo memang cuma satu foto yang bermasalah.
            if nama == FOLDER_BURAM and i == len(sumber):
                buramkan(asal, tujuan)
            else:
                shutil.copy(asal, tujuan)
        if nama == FOLDER_NORMAL:
            foto_normal = sumber

        contoh = dasar[nomor_polis]
        # Undian STNK dipisah per folder, tidak menumpang undian bersama. Kalau menumpang,
        # menambah atau menggeser satu folder mengubah tampilan STNK seluruh folder
        # sesudahnya, dan tingkat kesulitan yang sudah diukur ikut bergeser diam-diam.
        rng_stnk = random.Random(f"{args.seed}-stnk-{nama}")
        if salah:
            contoh = dengan_kesalahan(contoh, salah, random.Random(f"{args.seed}-salah-{nama}"))
        berkas_stnk = folder / "stnk.jpg"
        buat_stnk(contoh.data, rng=rng_stnk, tingkat_kerusakan=tingkat).save(
            berkas_stnk, quality=88
        )

        jawaban.append({
            "berkas": f"{nama}/stnk.jpg",
            "nomor_polis": contoh.nomor_polis,
            "sengaja_salah": contoh.sengaja_salah,
            "jawaban_benar": contoh.jawaban_benar,
        })

        (folder / "keterangan.txt").write_text(
            "\n".join([
                f"Skenario: {nama}",
                f"Nomor polis: {nomor_polis}",
                "",
                "Cara memakai:",
                f"  1. Buka menu Ajukan Klaim, isi nomor polis {nomor_polis}",
                f"  2. Kotak foto kerusakan: pilih {len(sumber)} berkas kerusakan-*",
                "  3. Pilih stnk.jpg di folder ini",
                "  4. Kirim klaim",
                "",
                "Yang diharapkan:",
                f"  {keterangan}",
                "",
                "Catatan penting:",
                "  Bobot model sungguhan sudah terpasang, jadi isi foto benar-benar",
                "  menentukan: tiap folder menghasilkan bagian, jenis kerusakan, dan angka",
                "  biaya yang berbeda. Kalau berkas bobot di backend/models/ hilang, sistem",
                "  kembali memakai detektor contoh dan angkanya jadi sama di semua folder.",
                *([
                    "",
                    "  Foto di folder ini mobilnya berbeda-beda, satu foto per jenis",
                    "  kerusakan. Dataset yang dipakai memuat satu foto per mobil, jadi",
                    "  beberapa sudut dari satu mobil memang tidak tersedia.",
                ] if len(sumber) > 1 else []),
                f"  Folder {FOLDER_RIIL} berisi satu mobil sungguhan dari klien.",
            ]),
            encoding="utf-8",
        )
        print(f"{nama}: {len(sumber)} foto + stnk.jpg")

    riil = susun_mobil_riil(dasar_semua, rng)
    if riil:
        jawaban.append(riil)

    jawaban += susun_uji_ocr(dasar_semua, rng, args.uji)

    (TUJUAN / "jawaban.json").write_text(
        json.dumps(jawaban, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if LAMA.exists():
        shutil.rmtree(LAMA)
        print(f"Folder lama {LAMA.name} dihapus, isinya sudah pindah ke sini.")

    print(f"\nSelesai. {len(SKENARIO)} folder di {TUJUAN}")
    print("Ukur akurasi OCR-nya dengan:")
    print(f"  uv run --extra ml python scripts/ukur_ocr_stnk.py {TUJUAN.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
