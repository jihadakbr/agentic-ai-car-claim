"""Pembangkit foto STNK buatan.

Tidak ada data STNK orang sungguhan yang ikut di berkas hasil. Yang dipakai cuma tata letak
lembarnya, diambil dari satu foto acuan; seluruh isian di atasnya ditimpa data karangan,
termasuk nama pejabat, kode QR, dan barcode yang tidak ada hubungannya dengan pembacaan.

Yang benar-benar diuji dengan berkas buatan ini adalah **pembaca field**, yaitu bagian yang
mengubah teks hasil pembacaan jadi Merk, Tipe, Nomor Rangka, dan seterusnya. Karena kita
yang membuat datanya, jawaban benarnya sudah diketahui, sehingga akurasinya bisa dihitung.

Ada dua gaya. `acuan` memakai foto asli sebagai latar sehingga pola kertas, stempel, dan
kontras tintanya yang pudar ikut terbawa. `gambar` menggambar lembar sendiri dari nol, dipakai
kalau templatnya tidak ada dan oleh uji yang tidak boleh bergantung berkas di luar repo.

Gambarnya sengaja dirusak sebelum dipakai. STNK buatan yang bersih dan lurus akan dibaca
hampir sempurna, dan angka akurasi dari situ menyesatkan. Foto STNK di lapangan diambil
surveyor sambil berdiri di bengkel: miring, kena bayangan, kadang STNK-nya sudah lecek.
"""

from __future__ import annotations

import os
import random
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

LEBAR = 1000
TINGGI = 640

_KANDIDAT_FONT = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def _font(ukuran: int) -> ImageFont.ImageFont:
    """Ambil font yang tersedia di sistem, dengan cadangan font bawaan PIL.

    Font bawaan PIL bentuknya bitmap kecil dan hasilnya jelek dibaca OCR, tapi lebih baik
    daripada gagal total di mesin yang tidak punya font TrueType.
    """
    for jalur in _KANDIDAT_FONT:
        if Path(jalur).exists():
            try:
                return ImageFont.truetype(jalur, ukuran)
            except OSError:
                continue
    return ImageFont.load_default()


@dataclass
class DataStnk:
    """Isi satu lembar STNK, sekaligus jawaban benar untuk mengukur pembaca field."""

    nomor_registrasi: str
    nama_pemilik: str
    alamat: str
    merk: str
    tipe: str
    jenis: str
    model: str
    tahun_pembuatan: int
    isi_silinder: str
    nomor_rangka: str
    nomor_mesin: str
    warna: str
    bahan_bakar: str
    warna_tnkb: str
    # Tahun registrasi bukan tahun pembuatan. STNK diperpanjang tiap 5 tahun, jadi tahun
    # registrasinya jauh lebih baru daripada tahun mobilnya dibuat.
    tahun_registrasi: int

    @property
    def berlaku_sampai_tahun(self) -> int:
        return self.tahun_registrasi + 5

    def sebagai_jawaban_benar(self) -> dict:
        """Jawaban benar untuk mengukur akurasi pembaca field."""
        return asdict(self)


# Urutan field mengikuti tata letak STNK, dibagi dua kolom.
_KOLOM_KIRI = [
    ("No. Registrasi", "nomor_registrasi"),
    ("Nama Pemilik", "nama_pemilik"),
    ("Alamat", "alamat"),
    ("Merk", "merk"),
    ("Type", "tipe"),
    ("Jenis", "jenis"),
    ("Model", "model"),
]
_KOLOM_KANAN = [
    ("Tahun Pembuatan", "tahun_pembuatan"),
    ("Isi Silinder", "isi_silinder"),
    ("No. Rangka", "nomor_rangka"),
    ("No. Mesin", "nomor_mesin"),
    ("Warna", "warna"),
    ("Bahan Bakar", "bahan_bakar"),
    ("Warna TNKB", "warna_tnkb"),
]


def render(data: DataStnk) -> Image.Image:
    """Gambar satu lembar STNK bersih, sebelum dirusak."""
    img = Image.new("RGB", (LEBAR, TINGGI), (247, 245, 232))
    d = ImageDraw.Draw(img)

    f_judul = _font(26)
    f_sub = _font(16)
    f_label = _font(17)
    f_nilai = _font(19)

    d.rectangle([12, 12, LEBAR - 12, TINGGI - 12], outline=(90, 90, 90), width=2)
    d.text((LEBAR // 2, 42), "SURAT TANDA NOMOR KENDARAAN BERMOTOR", font=f_judul,
           fill=(25, 45, 90), anchor="mm")
    d.text((LEBAR // 2, 72), "KORPS LALU LINTAS KEPOLISIAN NEGARA REPUBLIK INDONESIA",
           font=f_sub, fill=(70, 70, 70), anchor="mm")
    d.line([40, 92, LEBAR - 40, 92], fill=(120, 120, 120), width=1)

    nilai = data.sebagai_jawaban_benar()

    def potong(teks: str, lebar_maksimum: int) -> str:
        """Pendekkan nilai yang tidak muat di kolomnya.

        Tanpa ini, alamat yang panjang menerobos ke kolom kanan dan menimpa label di sana,
        sehingga labelnya hilang dari hasil OCR dan field sebelah ikut gagal terbaca.
        """
        if d.textlength(teks, font=f_nilai) <= lebar_maksimum:
            return teks
        while teks and d.textlength(teks + "...", font=f_nilai) > lebar_maksimum:
            teks = teks[:-1]
        return teks.rstrip() + "..."

    def gambar_kolom(
        x_label: int, lebar_label: int, field: list[tuple[str, str]], batas_kanan: int
    ) -> None:
        """Titik dua diletakkan setelah label terpanjang di kolomnya.

        Kalau jaraknya dipatok tetap, label panjang seperti "Tahun Pembuatan" akan menimpa
        titik duanya sendiri dan barisnya jadi terlihat beda dari yang lain.
        """
        x_titik = x_label + lebar_label
        x_nilai = x_titik + 22
        y = 125
        for label, kunci in field:
            d.text((x_label, y), label, font=f_label, fill=(90, 90, 90))
            d.text((x_titik, y), ":", font=f_label, fill=(90, 90, 90))
            d.text((x_nilai, y), potong(str(nilai[kunci]), batas_kanan - x_nilai),
                   font=f_nilai, fill=(20, 20, 20))
            y += 58

    def lebar_terpanjang(field: list[tuple[str, str]]) -> int:
        return max(int(d.textlength(label, font=f_label)) for label, _ in field) + 14

    # Kolom kiri berhenti jauh sebelum kolom kanan mulai. Jarak yang mepet membuat pendeteksi
    # teks menyatukan nilai kiri dengan label kanan jadi satu kotak.
    gambar_kolom(45, lebar_terpanjang(_KOLOM_KIRI), _KOLOM_KIRI, batas_kanan=465)
    gambar_kolom(520, lebar_terpanjang(_KOLOM_KANAN), _KOLOM_KANAN, batas_kanan=LEBAR - 40)

    d.line([40, TINGGI - 90, LEBAR - 40, TINGGI - 90], fill=(120, 120, 120), width=1)
    d.text((45, TINGGI - 72), f"Berlaku sampai: 31-12-{data.berlaku_sampai_tahun}",
           font=f_label, fill=(70, 70, 70))
    d.text((LEBAR - 45, TINGGI - 72), "DOKUMEN CONTOH, BUKAN STNK ASLI",
           font=f_label, fill=(160, 40, 40), anchor="ra")

    return img


TEMPLAT = Path(os.getenv("STNK_ACUAN", "data/acuan/stnk-acuan.jpg"))

# Isian STNK dicetak dengan huruf berkait, bukan huruf tanpa kait seperti gaya `gambar`.
# Daftarnya dipisah supaya `render()` yang lama tetap menghasilkan berkas yang sama persis.
_KANDIDAT_FONT_ACUAN = [
    "C:/Windows/Fonts/times.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
]

# Tinta pada lembar acuan sudah pudar, terukur sekitar (100, 95, 85) di atas latar (195,
# 190, 180). Kontras serendah itu justru bagian dari kesulitan yang mau diuji, jadi teks
# pengganti tidak digambar hitam pekat.
_TINTA = (95, 90, 80)

# Kotak tiap isian pada templat, hasil `scripts/kalibrasi_stnk_acuan.py`. Angka kedua adalah
# batas kanan saat menulis, karena nilai pengganti sering lebih panjang daripada nilai asli
# yang kotaknya diukur.
_FIELD: dict[str, tuple[tuple[int, int, int, int], int]] = {
    "nomor_registrasi": ((326, 184, 501, 219), 735),
    "nama_pemilik": ((330, 224, 658, 256), 735),
    "alamat": ((323, 258, 1036, 294), 1040),
    "merk": ((319, 328, 451, 362), 735),
    "tipe": ((314, 364, 995, 396), 995),
    "jenis": ((311, 402, 581, 436), 735),
    "model": ((310, 440, 451, 472), 735),
    "tahun_pembuatan": ((303, 476, 382, 508), 735),
    "isi_silinder": ((306, 512, 379, 544), 735),
    "nomor_rangka": ((302, 548, 633, 582), 735),
    "nomor_mesin": ((299, 584, 487, 618), 735),
    "warna": ((1000, 322, 1390, 368), 1390),
    "bahan_bakar": ((1000, 400, 1390, 436), 1390),
    "warna_tnkb": ((1000, 436, 1390, 470), 1390),
    "tahun_registrasi": ((1000, 470, 1390, 505), 1390),
}

# Isian yang ada di lembar tapi tidak ikut dinilai. Tetap ditimpa karena nilai aslinya milik
# orang sungguhan, dan lembar yang kotaknya dikosongkan begitu saja terlihat janggal.
_PENGISI: dict[str, tuple[tuple[int, int, int, int], int]] = {
    # Batas kanan nomor dokumen berhenti sebelum tanggal terbit, dan batas kanan NIK sebelum
    # nama pejabat. Di lembar aslinya keduanya memang saling menyerempet, jadi kotak hapusnya
    # boleh beririsan, tapi teks penggantinya tidak boleh.
    "no_dokumen": ((957, 62, 1300, 142), 1160),
    "tempat_tanggal": ((1164, 44, 1554, 82), 1600),
    "nik": ((1020, 176, 1265, 230), 1230),
    "pejabat_nama": ((1237, 218, 1537, 250), 1560),
    "pejabat_nrp": ((1243, 250, 1530, 280), 1560),
    "nomor_bpkb": ((1000, 505, 1390, 542), 1390),
    "nomor_pendaftaran": ((1000, 543, 1395, 584), 1395),
    "kode_validasi": ((1418, 502, 1561, 534), 1570),
    "kode_lokasi": ((1747, 512, 1824, 552), 1900),
    "berlaku_sampai": ((1616, 600, 1896, 638), 1900),
}

# Tanda tangan pejabat. Menunjuk satu orang tertentu, tidak pernah dibaca pipeline, dan tidak
# ada gunanya dikarang penggantinya.
_DIKOSONGKAN = [(1225, 138, 1478, 216)]

# Kode QR dan barcode. Isinya menunjuk dokumen tertentu, jadi harus hilang, tapi kotaknya
# tidak dibiarkan kosong: bidang putih di tengah lembar terlihat jelas sebagai bekas
# suntingan, dan hilangnya bidang berpola ikut menghilangkan gangguan yang wajar dihadapi OCR.
_KOTAK_SANDI = [
    (1812, 84, 1958, 200),
    (1410, 362, 1560, 512),
]

# Stempel bulat menumpuk di atas nomor dokumen dan NIK. Tintanya keunguan sedangkan teks di
# bawahnya kecokelatan, jadi keduanya bisa dipisah lewat selisih kanal biru dan hijau. Tanpa
# pemisahan ini, menempelkan potongan stempel apa adanya ikut mengembalikan nomor aslinya.
_STEMPEL = (1100, 100, 1252, 194)

_KOTA = ["SEMARANG", "BANDUNG", "SURABAYA", "MEDAN", "MAKASSAR", "DENPASAR", "PALEMBANG"]
_BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
          "September", "Oktober", "November", "Desember"]
_NAMA_PEJABAT = ["HARDIYANTO WIBOWO", "RAKA PRASETYA", "ANDIKA NUGROHO",
                 "BAGUS SETIAWAN", "IRFAN MAULANA"]


@lru_cache(maxsize=64)
def _font_acuan(ukuran: int) -> ImageFont.ImageFont:
    for jalur in _KANDIDAT_FONT_ACUAN:
        if Path(jalur).exists():
            try:
                return ImageFont.truetype(jalur, ukuran)
            except OSError:
                continue
    return _font(ukuran)


def _warna_latar(pita: np.ndarray, jendela: int = 61) -> np.ndarray:
    """Perkirakan warna kertas di sepanjang pita donor, tanpa ikut membawa tintanya.

    Persentil tinggi, bukan rata-rata, karena kertas selalu lebih terang daripada tinta,
    jadi nilai atas mewakili kertasnya. Hasilnya lalu diratakan mendatar: tanpa itu, huruf
    yang kebetulan tersenggol pita donor akan tercetak jadi garis tegak berulang sepanjang
    tambalan, mirip barcode.
    """
    kasar = np.percentile(pita, 75, axis=0)
    lebar = kasar.shape[0]
    j = min(jendela, lebar if lebar % 2 else lebar - 1)
    if j < 3:
        return kasar
    tepi = j // 2
    lebar_pad = np.pad(kasar, ((tepi, tepi), (0, 0)), mode="edge")
    inti = np.ones(j) / j
    return np.stack(
        [np.convolve(lebar_pad[:, c], inti, mode="valid") for c in range(kasar.shape[1])],
        axis=1,
    )


def _tambal(img: Image.Image, kotak: tuple[int, int, int, int], pita: int = 12) -> None:
    """Hapus isi kotak dengan latar yang menyambung ke sekitarnya.

    Kotak putih polos langsung terlihat sebagai bekas suntingan, dan yang lebih merugikan,
    bidang rata tanpa pola justru membuat teks di atasnya lebih mudah dibaca OCR daripada
    di lembar aslinya. Jadi warnanya digradasi dari pita di atas kotak ke pita di bawahnya,
    lalu tekstur kertas dari pita itu ditempelkan kembali.
    """
    x0, y0, x1, y1 = kotak
    a = np.asarray(img, dtype=np.float32)
    tinggi, lebar = y1 - y0, x1 - x0
    if tinggi <= 0 or lebar <= 0:
        return

    atas = a[max(0, y0 - pita):y0, x0:x1]
    bawah = a[y1:y1 + pita, x0:x1]
    if atas.size == 0:
        atas = bawah
    if bawah.size == 0:
        bawah = atas
    if atas.size == 0:
        return

    warna_atas = _warna_latar(atas)
    warna_bawah = _warna_latar(bawah)
    t = np.linspace(0.0, 1.0, tinggi, dtype=np.float32)[:, None, None]
    hasil = warna_atas[None] * (1 - t) + warna_bawah[None] * t

    # Butiran halus supaya tambalannya tidak jadi bidang rata. Bidang rata bukan cuma
    # terlihat sebagai bekas suntingan, tapi juga membuat teks di atasnya lebih mudah
    # dibaca OCR daripada di lembar aslinya, sehingga angka akurasinya jadi terlalu bagus.
    derau = np.random.default_rng(x0 * 7919 + y0).normal(0, 3.5, hasil.shape)

    a[y0:y1, x0:x1] = np.clip(hasil + derau, 0, 255)
    img.paste(Image.fromarray(a.astype(np.uint8)))


def _tulis(
    d: ImageDraw.ImageDraw, teks: str, kotak: tuple[int, int, int, int], batas_kanan: int
) -> int:
    """Gambar satu nilai supaya pas di kotaknya, kembalikan ukuran huruf yang terpakai.

    Ukurannya dicari turun dari setinggi kotak sampai muat, bukan dipatok per field. Nilai
    karangan panjangnya tidak sama dengan nilai asli yang kotaknya diukur, dan nilai yang
    meluber akan menimpa label di sebelahnya sehingga field itu ikut gagal terbaca.
    """
    x0, y0, _, y1 = kotak
    tinggi = y1 - y0
    lebar_maksimum = batas_kanan - x0

    ukuran = tinggi
    while ukuran > 8:
        f = _font_acuan(ukuran)
        kiri, atas, kanan, bawah = d.textbbox((0, 0), teks, font=f)
        if (bawah - atas) <= tinggi and (kanan - kiri) <= lebar_maksimum:
            break
        ukuran -= 1

    d.text((x0, (y0 + y1) // 2), teks, font=_font_acuan(ukuran), fill=_TINTA, anchor="lm")
    return ukuran


def _nilai_pengisi(data: DataStnk, rng: random.Random) -> dict[str, str]:
    """Isian yang ditimpa tapi tidak ikut jadi jawaban benar."""
    kota = rng.choice(_KOTA)
    return {
        "no_dokumen": f"{rng.randrange(10**8):08d}.{rng.randint(1, 9)}",
        "tempat_tanggal": (
            f"{kota} 1, {rng.randint(1, 28):02d}-{rng.choice(_BULAN)}-"
            f"{data.tahun_pembuatan - rng.randint(0, 3)}"
        ),
        "nik": f"{rng.randrange(10**16):016d}",
        "pejabat_nama": f"{rng.choice(_NAMA_PEJABAT)}, S.I.K., M.H.",
        "pejabat_nrp": f"KOMBES POL NRP {rng.randrange(10**8):08d}",
        "nomor_bpkb": f"P{rng.randrange(10**8):08d}",
        "nomor_pendaftaran": (
            f"{rng.randint(1000, 9999)}/{rng.randint(100, 999)}-{rng.randint(100, 999)}"
            f"/B/{rng.randint(1, 28):02d}{rng.randint(1, 12):02d}{data.tahun_registrasi}"
        ),
        "kode_validasi": "".join(rng.choices("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789", k=9)),
        "kode_lokasi": f"{rng.randrange(10000):04d}",
        "berlaku_sampai": (
            f"{rng.randint(1, 28)} {rng.choice(_BULAN)} {data.berlaku_sampai_tahun}"
        ),
    }


def _gambar_sandi(d: ImageDraw.ImageDraw, kotak: tuple[int, int, int, int],
                  rng: random.Random) -> None:
    """Gambar blok kotak-kotak acak sebagai pengganti kode QR."""
    x0, y0, x1, y1 = kotak
    sisi = 21
    langkah_x = (x1 - x0) / sisi
    langkah_y = (y1 - y0) / sisi
    for baris in range(sisi):
        for kolom in range(sisi):
            if rng.random() < 0.45:
                d.rectangle(
                    [x0 + kolom * langkah_x, y0 + baris * langkah_y,
                     x0 + (kolom + 1) * langkah_x, y0 + (baris + 1) * langkah_y],
                    fill=(70, 68, 66),
                )


def _tempel_stempel(img: Image.Image, asli: Image.Image) -> None:
    """Kembalikan tinta stempel di atas isian yang sudah ditimpa.

    Alpha dibuat bertingkat, bukan ambang keras, karena stempelnya sangat pudar dan ambang
    keras menyisakan bercak berbintik alih-alih lingkaran.
    """
    x0, y0 = _STEMPEL[:2]
    lama = np.asarray(asli.crop(_STEMPEL), dtype=np.float32)
    baru = np.asarray(img.crop(_STEMPEL), dtype=np.float32)
    keunguan = np.clip((lama[:, :, 2] - lama[:, :, 1] - 2) / 8.0, 0, 1)[:, :, None]
    campur = lama * keunguan + baru * (1 - keunguan)
    img.paste(Image.fromarray(campur.astype(np.uint8)), (x0, y0))


def render_dari_acuan(data: DataStnk, rng: random.Random) -> Image.Image:
    """Gambar satu lembar STNK di atas templat foto acuan."""
    asli = Image.open(TEMPLAT).convert("RGB")
    img = asli.copy()

    for kotak in _DIKOSONGKAN + _KOTAK_SANDI:
        _tambal(img, kotak)
    for kotak, _ in list(_FIELD.values()) + list(_PENGISI.values()):
        _tambal(img, kotak)

    d = ImageDraw.Draw(img)
    for kotak in _KOTAK_SANDI:
        _gambar_sandi(d, kotak, rng)

    nilai = data.sebagai_jawaban_benar() | _nilai_pengisi(data, rng)
    for kunci, (kotak, batas) in list(_FIELD.items()) + list(_PENGISI.items()):
        _tulis(d, str(nilai[kunci]), kotak, batas)

    _tempel_stempel(img, asli)
    return img


def _koefisien_perspektif(sumber, tujuan) -> list[float]:
    """Hitung koefisien transformasi perspektif dari empat pasang titik sudut."""
    matriks = []
    for (x, y), (u, v) in zip(tujuan, sumber, strict=True):
        matriks.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        matriks.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    A = np.array(matriks, dtype=float)
    B = np.array(sumber, dtype=float).reshape(8)
    return np.linalg.solve(A, B).tolist()


def rusak_sedikit(img: Image.Image, rng: random.Random, tingkat: float = 1.0) -> Image.Image:
    """Buat gambar terlihat seperti hasil foto HP, bukan hasil render.

    `tingkat` 0 berarti tidak diubah sama sekali, 1 kerusakan wajar, di atas 1 lebih parah.
    Dipakai untuk membuat kumpulan uji bertingkat, dari STNK yang mudah dibaca sampai yang
    memang sulit.
    """
    if tingkat <= 0:
        return img

    hasil = img.convert("RGB")

    # Miringkan seolah difoto dari samping.
    geser = int(18 * tingkat)
    if geser > 0:
        w, h = hasil.size
        tujuan = [(0, 0), (w, 0), (w, h), (0, h)]
        sumber = [
            (rng.randint(0, geser), rng.randint(0, geser)),
            (w - rng.randint(0, geser), rng.randint(0, geser)),
            (w - rng.randint(0, geser), h - rng.randint(0, geser)),
            (rng.randint(0, geser), h - rng.randint(0, geser)),
        ]
        koef = _koefisien_perspektif(sumber, tujuan)
        hasil = hasil.transform((w, h), Image.PERSPECTIVE, koef, Image.BICUBIC,
                                fillcolor=(60, 60, 60))

    # Putar sedikit, karena orang jarang memotret benar-benar lurus.
    hasil = hasil.rotate(rng.uniform(-4, 4) * tingkat, resample=Image.BICUBIC,
                         expand=False, fillcolor=(60, 60, 60))

    # Bayangan tangan atau badan yang menutupi sebagian lembar.
    if rng.random() < 0.6 * tingkat:
        bayangan = Image.new("L", hasil.size, 0)
        db = ImageDraw.Draw(bayangan)
        w, h = hasil.size
        x0 = rng.randint(0, w // 2)
        db.polygon(
            [(x0, 0), (x0 + rng.randint(80, 260), 0), (x0 + rng.randint(40, 200), h), (x0, h)],
            fill=int(70 * tingkat),
        )
        bayangan = bayangan.filter(ImageFilter.GaussianBlur(28))
        gelap = Image.new("RGB", hasil.size, (0, 0, 0))
        hasil = Image.composite(gelap, hasil, bayangan.point(lambda v: min(v, 120)))

    hasil = ImageEnhance.Brightness(hasil).enhance(rng.uniform(0.78, 1.18))
    hasil = ImageEnhance.Contrast(hasil).enhance(rng.uniform(0.82, 1.12))
    hasil = hasil.filter(ImageFilter.GaussianBlur(rng.uniform(0, 1.1) * tingkat))

    # Bintik-bintik sensor kamera pada cahaya kurang. Benih diambil dari rng yang sama
    # supaya seluruh proses tetap bisa diulang persis dengan seed yang sama.
    arr = np.asarray(hasil, dtype=np.int16)
    derau = np.random.default_rng(rng.randrange(1 << 30)).normal(0, 7 * tingkat, arr.shape)
    return Image.fromarray(np.clip(arr + derau, 0, 255).astype(np.uint8))


# Templat acuan sudah berupa foto: miring, berbayang, dan berderau sejak awal. Menumpuk
# kerusakan sebanyak gaya `gambar` di atasnya menghasilkan lembar yang tidak terbaca siapa pun.
REDAM_ACUAN = 0.45


def buat_stnk(
    data: DataStnk,
    rng: random.Random | None = None,
    tingkat_kerusakan: float = 1.0,
    gaya: str = "acuan",
) -> Image.Image:
    """Bangkitkan satu foto STNK buatan, siap dipakai sebagai bahan uji.

    `gaya` boleh `acuan` (templat foto) atau `gambar` (lembar digambar dari nol). Gaya acuan
    otomatis jatuh ke gaya gambar kalau templatnya tidak ada, supaya repo yang baru di-clone
    tetap bisa menjalankan uji tanpa berkas tambahan.
    """
    r = rng or random.Random()
    if gaya == "acuan" and TEMPLAT.exists():
        return rusak_sedikit(render_dari_acuan(data, r), r, tingkat_kerusakan * REDAM_ACUAN)
    return rusak_sedikit(render(data), r, tingkat_kerusakan)
