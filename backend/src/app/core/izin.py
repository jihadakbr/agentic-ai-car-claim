"""Daftar hak akses yang benar-benar ada di sistem.

Ditulis di kode, bukan di database, karena tiap hak di sini menutup alamat API yang memang
ada. Hak yang bisa dibuat bebas dari layar akan menghasilkan centang yang tidak menjaga
apa pun, dan itu lebih berbahaya daripada tidak ada pengaturan sama sekali.

Yang disimpan di database cuma pemberiannya: peran mana punya hak apa.
"""

from __future__ import annotations

POLIS_LIHAT = "polis.lihat"
KLAIM_KIRIM = "klaim.kirim"
KLAIM_LACAK = "klaim.lacak_sendiri"
KLAIM_LIHAT = "klaim.lihat"
KLAIM_PUTUSKAN = "klaim.putuskan"
KLAIM_REVIEW = "klaim.review_deteksi"
KLAIM_HAPUS = "klaim.hapus"
OVERVIEW_LIHAT = "overview.lihat"
AKSES_KELOLA = "akses.kelola"

# Urutannya menentukan urutan tampil di layar Hak Akses, jadi disusun mengikuti alur kerja:
# surveyor lebih dulu, adjuster, lalu yang khusus admin.
KATALOG: list[dict[str, str]] = [
    {
        "kode": POLIS_LIHAT,
        "nama": "Lihat data polis",
        "keterangan": "Mencari polis sebelum mengirim klaim, untuk memastikan nomornya benar",
        "kelompok": "Klaim masuk",
    },
    {
        "kode": KLAIM_KIRIM,
        "nama": "Kirim klaim",
        "keterangan": "Mengirim klaim baru beserta foto, dan mengirim foto tambahan yang diminta",
        "kelompok": "Klaim masuk",
    },
    {
        "kode": KLAIM_LACAK,
        "nama": "Lacak klaim sendiri",
        "keterangan": (
            "Membuka daftar klaim yang dia kirim sendiri beserta statusnya, tanpa biaya "
            "maupun penilaian"
        ),
        "kelompok": "Klaim masuk",
    },
    {
        "kode": KLAIM_LIHAT,
        "nama": "Lihat seluruh klaim",
        "keterangan": "Membuka daftar klaim dan rinciannya, termasuk biaya dan penilaian agent",
        "kelompok": "Penilaian",
    },
    {
        "kode": KLAIM_REVIEW,
        "nama": "Nilai ketepatan deteksi",
        "keterangan": (
            "Menandai tiap temuan deteksi benar atau salah beserta alasannya, dan "
            "memeriksa hasil baca STNK per field"
        ),
        "kelompok": "Penilaian",
    },
    {
        "kode": KLAIM_PUTUSKAN,
        "nama": "Putuskan klaim",
        "keterangan": (
            "Menyetujui, menolak, atau meminta revisi, menerbitkan suratnya, dan "
            "membatalkan keputusan yang sudah diambil"
        ),
        "kelompok": "Penilaian",
    },
    {
        "kode": OVERVIEW_LIHAT,
        "nama": "Lihat Overview",
        "keterangan": "Membuka angka gabungan seluruh klaim dari semua surveyor",
        "kelompok": "Penilaian",
    },
    {
        "kode": KLAIM_HAPUS,
        "nama": "Hapus klaim",
        "keterangan": "Menghapus klaim beserta foto dan seluruh jejak auditnya, tidak bisa dibatalkan",
        "kelompok": "Administrasi",
    },
    {
        "kode": AKSES_KELOLA,
        "nama": "Kelola akses",
        "keterangan": "Mengubah peran pengguna, membuat peran, dan mengatur hak tiap peran",
        "kelompok": "Administrasi",
    },
]

SEMUA = tuple(i["kode"] for i in KATALOG)

# Peran bawaan beserta haknya. Dipakai saat pengisian data awal, dan sesudah itu boleh
# diubah lewat layar Manajemen Akses.
PERAN_BAWAAN: list[dict] = [
    {
        "kode": "surveyor",
        "nama": "Surveyor",
        "keterangan": "Petugas lapangan. Memotret kerusakan dan mengirim klaim, tidak menilai.",
        "izin": [POLIS_LIHAT, KLAIM_KIRIM, KLAIM_LACAK],
    },
    {
        "kode": "adjuster",
        "nama": "Adjuster",
        "keterangan": "Peninjau klaim. Memverifikasi hasil AI lalu mengambil keputusan.",
        "izin": [KLAIM_LIHAT, KLAIM_REVIEW, KLAIM_PUTUSKAN, OVERVIEW_LIHAT],
    },
    {
        "kode": "admin",
        "nama": "Administrator",
        "keterangan": "Akses penuh, termasuk menghapus klaim dan mengatur akses.",
        "izin": list(SEMUA),
    },
]


def tidak_dikenal(daftar: list[str]) -> list[str]:
    """Hak yang tidak ada di katalog. Memberikannya cuma menghasilkan centang kosong."""
    return [i for i in daftar if i not in SEMUA]
