"""Menumpuk mask bagian mobil dengan mask kerusakan.

Ini operasi paling menentukan di seluruh sistem. Model bagian tahu di mana kap mesin
berada tapi tidak tahu ada kerusakan. Model kerusakan tahu di mana ada penyok tapi tidak
tahu itu bagian apa. Modul inilah yang menggabungkan keduanya jadi kalimat
"kap mesin, penyok, 45% luas part", dan angka 45% itu yang menentukan biaya klaim.

Mask direpresentasikan sebagai larik boolean dua dimensi, bentuk yang memang dikeluarkan
model segmentasi, jadi tidak ada perhitungan geometri poligon yang perlu ditiru sendiri.

Ada dua pembagian berbeda di sini dan keduanya diperlukan:

- **Bagian kerusakan yang berada di dalam satu part** menjawab "kerusakan ini milik siapa"
- **Bagian part yang tertutup kerusakan** menjawab "seberapa parah part itu rusak"
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.pipeline.cost_engine import Temuan


@dataclass(frozen=True)
class MaskDeteksi:
    """Satu hasil segmentasi dari model, entah bagian mobil atau kerusakan."""

    kelas: str
    confidence: float
    mask: np.ndarray
    # Garis tepi mask, dinormalkan ke 0 sampai 1. Dipakai layar yang menggambar overlaynya
    # sendiri sebagai vektor supaya warnanya bisa diganti dan lapisannya bisa dimatikan.
    # Perhitungan biaya tidak memakainya sama sekali, jadi boleh kosong.
    poligon: list[list[float]] = field(default_factory=list)

    @property
    def luas(self) -> int:
        return int(np.count_nonzero(self.mask))


@dataclass
class TemuanGabungan:
    """Satu kerusakan yang sudah diketahui menempel di bagian mana."""

    part_class: str
    damage_class: str
    sisi: str | None
    confidence_part: float
    confidence_damage: float
    luas_part_px: int
    luas_damage_px: int
    luas_irisan_px: int
    rasio_luas: float
    # Nomor mask asalnya di daftar part dan damage foto ini. Dipakai layar untuk menomori
    # instance sekelas, supaya baris tabel dan bentuk di gambarnya menunjuk hal yang sama.
    part_urutan: int = 0
    damage_urutan: int = 0


def bentuk_json(daftar: list[MaskDeteksi]) -> list[dict]:
    """Bentuk tiap mask untuk layar yang menggambar overlaynya sendiri.

    Mask yang tidak membawa kontur, misalnya dari detektor contoh yang bentuknya memang
    persegi, dipakaikan kotak pembatasnya. Tanpa itu layar pratinjau kosong padahal
    deteksinya ada.
    """
    hasil = []
    for m in daftar:
        titik = m.poligon
        if not titik:
            ys, xs = m.mask.nonzero()
            if len(xs) == 0:
                continue
            tinggi, lebar = m.mask.shape
            x0, x1 = int(xs.min()) / lebar, int(xs.max()) / lebar
            y0, y1 = int(ys.min()) / tinggi, int(ys.max()) / tinggi
            titik = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        hasil.append({
            "kelas": m.kelas,
            "keyakinan": round(float(m.confidence), 3),
            "titik": [[round(x, 4), round(y, 4)] for x, y in titik],
        })
    return hasil


def pusat_x(mask: np.ndarray) -> float | None:
    """Titik tengah mendatar dari sebuah mask. None kalau mask-nya kosong."""
    kolom = np.nonzero(mask)[1]
    if kolom.size == 0:
        return None
    return float(kolom.mean())


def pusat_kendaraan(part: list[MaskDeteksi]) -> float | None:
    """Perkirakan titik tengah mendatar mobil dari gabungan seluruh mask bagian.

    Dipakai untuk menentukan sisi kiri atau kanan. Titik tengah gambar tidak dipakai karena
    mobil sering tidak berada persis di tengah bingkai foto.
    """
    ada = [p.mask for p in part if p.luas > 0]
    if not ada:
        return None
    return pusat_x(np.logical_or.reduce(ada))


def tentukan_sisi(mask: np.ndarray, pusat: float | None) -> str | None:
    """Tentukan sisi kiri atau kanan dari posisi mask terhadap titik tengah mobil.

    Dataset yang dipakai tidak membedakan kiri dan kanan, yang ada cuma `Front-door`, jadi
    sisinya dihitung, bukan dideteksi. Untuk biaya ini tidak berpengaruh karena harga kiri
    dan kanan sama. Yang terpengaruh cuma ketepatan penamaan di laporan.

    Sisi ditentukan dari sudut pandang orang yang melihat foto, bukan dari sudut pandang
    pengemudi. Ini pilihan sadar: adjuster melihat foto, bukan duduk di dalam mobil.
    """
    if pusat is None:
        return None
    x = pusat_x(mask)
    if x is None:
        return None
    # Bagian yang membentang melewati titik tengah, misalnya kap mesin atau bumper, tidak
    # punya sisi. Memaksakan label kiri atau kanan untuk bagian itu justru menyesatkan.
    kolom = np.nonzero(mask)[1]
    lebar = kolom.max() - kolom.min() + 1
    if abs(x - pusat) < lebar * 0.25:
        return None
    return "kiri" if x < pusat else "kanan"


def tumpuk(
    part: list[MaskDeteksi],
    damage: list[MaskDeteksi],
    ambang_irisan: float = 0.30,
    bagian_diabaikan: frozenset[str] = frozenset(),
    ambang_part_tertutup: float = 0.15,
) -> list[TemuanGabungan]:
    """Cari bagian mana yang rusak, dan seberapa luas.

    Satu kerusakan bisa membentang ke lebih dari satu bagian, misalnya benturan yang
    merusak bumper sekaligus fender. Dalam kasus itu kerusakannya dihitung untuk kedua
    bagian dengan rasio masing-masing, karena keduanya memang perlu dikerjakan bengkel.

    Kerusakan dianggap milik satu bagian kalau **salah satu** dari dua syarat terpenuhi:

    - Sebagian besar luas kerusakan berada di dalam bagian itu (`ambang_irisan`)
    - Bagian itu tertutup kerusakan cukup luas (`ambang_part_tertutup`)

    Syarat kedua diperlukan untuk benturan besar yang menyapu banyak bagian sekaligus.
    Untuk benturan seperti itu, tiap bagian cuma memuat sebagian kecil dari total luas
    kerusakan, sehingga syarat pertama saja akan menolak semuanya padahal semuanya memang
    rusak. Sebaliknya, syarat pertama menangkap kerusakan kecil yang seluruhnya berada di
    satu bagian. Kerusakan yang ujungnya cuma menyenggol bagian tetangga gagal di dua-duanya.
    """
    pusat = pusat_kendaraan(part)
    hasil: list[TemuanGabungan] = []

    for i_d, d in enumerate(damage):
        luas_d = d.luas
        if luas_d == 0:
            continue

        for i_p, p in enumerate(part):
            if p.kelas in bagian_diabaikan:
                continue
            luas_p = p.luas
            if luas_p == 0:
                continue

            irisan = int(np.count_nonzero(np.logical_and(p.mask, d.mask)))
            if irisan == 0:
                continue

            bagian_dari_kerusakan = irisan / luas_d
            bagian_dari_part = irisan / luas_p
            if bagian_dari_kerusakan < ambang_irisan and bagian_dari_part < ambang_part_tertutup:
                continue

            hasil.append(
                TemuanGabungan(
                    part_class=p.kelas,
                    damage_class=d.kelas,
                    sisi=tentukan_sisi(p.mask, pusat),
                    confidence_part=p.confidence,
                    confidence_damage=d.confidence,
                    luas_part_px=luas_p,
                    luas_damage_px=luas_d,
                    luas_irisan_px=irisan,
                    rasio_luas=irisan / luas_p,
                    part_urutan=i_p,
                    damage_urutan=i_d,
                )
            )

    hasil.sort(key=lambda t: (t.part_class, t.sisi or "", t.damage_class))
    return hasil


def ringkas_antar_foto(
    per_foto: list[list[TemuanGabungan]],
) -> tuple[list[TemuanGabungan], dict[tuple[str, str | None], int]]:
    """Gabungkan hasil beberapa foto jadi satu daftar.

    Rasio yang dipakai adalah yang tertinggi di antara semua foto, dengan alasan sudut yang
    paling jelas memperlihatkan kerusakan adalah yang paling mendekati keadaan sebenarnya.
    Sudut yang menangkap kerusakan secara menyerong selalu memperkecil luasnya.

    Selain daftar temuan, dikembalikan juga hitungan berapa foto yang memperlihatkan tiap
    bagian. Angka itu dipakai pemeriksaan konsistensi antar sudut (cek C3).
    """
    terbaik: dict[tuple[str, str | None, str], TemuanGabungan] = {}
    foto_per_bagian: dict[tuple[str, str | None], int] = {}

    for temuan_foto in per_foto:
        bagian_di_foto_ini: set[tuple[str, str | None]] = set()

        for t in temuan_foto:
            kunci = (t.part_class, t.sisi, t.damage_class)
            sebelumnya = terbaik.get(kunci)
            if sebelumnya is None or t.rasio_luas > sebelumnya.rasio_luas:
                terbaik[kunci] = t
            bagian_di_foto_ini.add((t.part_class, t.sisi))

        for kunci in bagian_di_foto_ini:
            foto_per_bagian[kunci] = foto_per_bagian.get(kunci, 0) + 1

    hasil = sorted(
        terbaik.values(), key=lambda t: (t.part_class, t.sisi or "", t.damage_class)
    )
    return hasil, foto_per_bagian


def ke_temuan_biaya(
    temuan: list[TemuanGabungan],
    jumlah_foto: dict[tuple[str, str | None], int] | None = None,
) -> list[Temuan]:
    """Ubah hasil penumpukan jadi bentuk yang dimengerti cost engine.

    Dipisah jadi fungsi tersendiri supaya cost engine tetap tidak tahu apa-apa soal mask,
    piksel, maupun model deteksi. Cost engine cuma menerima "bagian ini, kerusakan ini,
    sekian persen luasnya", dan itu membuatnya bisa diuji tanpa gambar sama sekali.
    """
    n = jumlah_foto or {}
    return [
        Temuan(
            part_class=t.part_class,
            damage_class=t.damage_class,
            rasio_luas=t.rasio_luas,
            sisi=t.sisi,
            jumlah_foto=n.get((t.part_class, t.sisi), 1),
            sumber="deteksi",
        )
        for t in temuan
    ]
