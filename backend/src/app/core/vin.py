"""Nomor rangka kendaraan (VIN) menurut ISO 3779.

Dipakai di dua tempat: membangkitkan nomor rangka untuk STNK buatan, dan memeriksa
kewajaran nomor rangka hasil pembacaan di cek validitas C5.

Aturan yang dipakai:

- Panjangnya tepat 17 karakter.
- Huruf I, O, dan Q tidak pernah dipakai, supaya tidak tertukar dengan angka 1 dan 0.
- Karakter ke-10 menandakan tahun pembuatan, dan kodenya berulang tiap 30 tahun.

Catatan penting soal karakter ke-10: pengkodean tahun ini wajib di Amerika Utara, tapi
tidak semua pabrikan di luar sana mengikutinya. Karena itu ketidakcocokan tahun hanya
dijadikan tanda peringatan, bukan penolakan.
"""

import random

KARAKTER_SAH = set("ABCDEFGHJKLMNPRSTUVWXYZ0123456789")
KARAKTER_TERLARANG = set("IOQ")

# Kode tahun pada karakter ke-10, berurutan dan berulang tiap 30 tahun. Selain I, O, dan Q,
# huruf U dan Z juga tidak dipakai di posisi ini.
_URUTAN_KODE_TAHUN = "ABCDEFGHJKLMNPRSTVWXY123456789"
_TAHUN_AWAL = 1980


def kode_tahun(tahun: int) -> str:
    """Ubah tahun pembuatan jadi satu karakter kode."""
    return _URUTAN_KODE_TAHUN[(tahun - _TAHUN_AWAL) % 30]


def tahun_dari_kode(kode: str, tahun_acuan: int | None = None) -> list[int]:
    """Kembalikan tahun yang mungkin dari satu karakter kode.

    Karena kodenya berulang tiap 30 tahun, satu karakter selalu cocok ke lebih dari satu
    tahun. Contoh: 'D' bisa berarti 1983, 2013, atau 2043. Kalau `tahun_acuan` diisi, hasil
    yang jauh dari masa kini dibuang supaya perbandingan jadi berarti.
    """
    posisi = _URUTAN_KODE_TAHUN.find(kode.upper())
    if posisi < 0:
        return []
    kandidat = [_TAHUN_AWAL + posisi + (30 * n) for n in range(4)]
    if tahun_acuan is None:
        return kandidat
    return [t for t in kandidat if abs(t - tahun_acuan) <= 30]


def masalah_format(vin: str) -> list[str]:
    """Periksa kewajaran nomor rangka, kembalikan daftar masalah dalam bahasa manusia.

    Daftar kosong berarti formatnya wajar. Pesannya sengaja ditulis untuk dibaca adjuster,
    bukan untuk dibaca programmer, karena isinya muncul di layar sebagai alasan cek C5.
    """
    masalah: list[str] = []
    bersih = (vin or "").strip().upper()

    if not bersih:
        return ["Nomor rangka tidak terbaca sama sekali"]

    if len(bersih) != 17:
        masalah.append(f"Panjangnya {len(bersih)} karakter, seharusnya tepat 17")

    terlarang = sorted(set(bersih) & KARAKTER_TERLARANG)
    if terlarang:
        masalah.append(
            f"Mengandung huruf {', '.join(terlarang)} yang tidak pernah dipakai di nomor rangka"
        )

    tak_dikenal = sorted(set(bersih) - KARAKTER_SAH - KARAKTER_TERLARANG)
    if tak_dikenal:
        masalah.append(f"Mengandung karakter yang bukan huruf atau angka: {', '.join(tak_dikenal)}")

    return masalah


def tahun_cocok(vin: str, tahun_stnk: int) -> bool | None:
    """Bandingkan kode tahun di nomor rangka dengan tahun pembuatan di STNK.

    Mengembalikan None kalau perbandingannya tidak bisa dilakukan, misalnya nomor rangkanya
    terlalu pendek atau kode tahunnya tidak dikenal. None berarti "tidak tahu", dan itu
    berbeda dari False yang berarti "tidak cocok".
    """
    bersih = (vin or "").strip().upper()
    if len(bersih) < 10:
        return None
    kandidat = tahun_dari_kode(bersih[9], tahun_acuan=tahun_stnk)
    if not kandidat:
        return None
    return tahun_stnk in kandidat


def buat_vin(wmi: str, tahun: int, urutan: int, rng: random.Random | None = None) -> str:
    """Bangkitkan nomor rangka buatan yang formatnya benar.

    `wmi` adalah tiga karakter pertama yang menandakan negara dan pabrikan, misalnya `MHK`
    untuk kendaraan rakitan Indonesia. Karakter ke-10 diisi kode tahun yang benar supaya
    pemeriksaan kecocokan tahun di cek C5 punya bahan uji yang sungguhan, termasuk kasus
    yang sengaja dibuat salah.
    """
    r = rng or random.Random()
    tersedia = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"

    wmi_bersih = wmi.upper()[:3].ljust(3, "M")
    vds = "".join(r.choice(tersedia) for _ in range(5))
    pemeriksa = r.choice("0123456789X")
    vis = f"{urutan:06d}"[-6:]

    vin = f"{wmi_bersih}{vds}{pemeriksa}{kode_tahun(tahun)}{r.choice(tersedia)}{vis}"
    assert len(vin) == 17, vin
    return vin
