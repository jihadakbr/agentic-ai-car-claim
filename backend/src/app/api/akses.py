"""Pembacaan dan perubahan pengguna, peran, dan hak akses.

Dipisah dari `penyimpanan.py` karena isinya soal siapa boleh apa, bukan soal klaim.

Setiap perubahan meninggalkan baris di audit log. Layar Log Aktivitas membacanya dari
sana, jadi tidak ada catatan terpisah yang bisa berbeda dari jejak audit sungguhan.
"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.penyimpanan import catat_audit, waktu_iso
from app.core import izin
from app.core.auth import garam_baru, hash_sandi, periksa_sandi, sandi_demo
from app.db.models import AppUser, AuditLog, Role, RolePermission

TAHAP = "akses"

# Username dipakai apa adanya di alamat API dan di jejak audit, jadi bentuknya dibatasi
# supaya tidak perlu di-escape di mana-mana.
BENTUK_USERNAME = re.compile(r"[a-z0-9._-]+")

PANJANG_SANDI_MINIMAL = 8


def izin_peran(s: Session, kode: str) -> set[str]:
    """Hak yang dimiliki satu peran. Dibaca tiap permintaan, jadi perubahan langsung berlaku."""
    return set(
        s.scalars(select(RolePermission.izin).where(RolePermission.role_kode == kode))
    )


def daftar_pengguna(s: Session) -> list[dict]:
    peran = {r.kode: r.nama for r in s.scalars(select(Role))}
    return [
        {
            "username": u.username,
            "nama": u.nama,
            "peran": u.peran,
            "nama_peran": peran.get(u.peran, u.peran),
            "aktif": u.aktif,
            "dibuat": waktu_iso(u.created_at),
        }
        for u in s.scalars(select(AppUser).order_by(AppUser.username))
    ]


def daftar_peran(s: Session) -> list[dict]:
    jumlah = dict(
        s.execute(select(AppUser.peran, func.count()).group_by(AppUser.peran)).all()
    )
    return [
        {
            "kode": r.kode,
            "nama": r.nama,
            "keterangan": r.keterangan,
            "bawaan": r.bawaan,
            "jumlah_pengguna": jumlah.get(r.kode, 0),
            "izin": sorted(izin_peran(s, r.kode)),
        }
        for r in s.scalars(select(Role).order_by(Role.kode))
    ]


def _sandi_tersimpan(sandi: str) -> tuple[str, str]:
    """Garam baru dan turunannya. Garamnya berbeda tiap kali, jadi dua akun bersandi sama
    tetap menghasilkan turunan yang berbeda di database."""
    garam = garam_baru()
    return garam, hash_sandi(sandi, garam)


def _periksa_panjang(sandi: str) -> None:
    if len(sandi) < PANJANG_SANDI_MINIMAL:
        raise ValueError(f"Kata sandi minimal {PANJANG_SANDI_MINIMAL} karakter")


def buat_pengguna(
    s: Session, username: str, nama: str, peran: str, sandi: str, oleh: str
) -> dict:
    """Akun baru untuk layar Manajemen Akses.

    Sandi yang dikosongkan berarti memakai sandi demo, sama dengan akun contoh bawaan.
    """
    username = username.strip().lower()
    nama = nama.strip()
    if not username or not nama:
        raise ValueError("Username dan nama harus diisi")
    if not BENTUK_USERNAME.fullmatch(username):
        raise ValueError("Username hanya boleh huruf, angka, titik, garis bawah, dan strip")
    if s.scalar(select(AppUser).where(AppUser.username == username)) is not None:
        raise ValueError(f"Pengguna {username} sudah ada")
    if s.scalar(select(Role).where(Role.kode == peran)) is None:
        raise ValueError(f"Peran {peran} tidak ada")
    if sandi:
        _periksa_panjang(sandi)

    garam, turunan = _sandi_tersimpan(sandi or sandi_demo())
    s.add(
        AppUser(
            username=username, nama=nama, peran=peran, garam=garam, sandi_hash=turunan
        )
    )
    catat_audit(s, None, TAHAP, "pengguna_dibuat",
                {"username": username, "nama": nama, "peran": peran, "oleh": oleh})
    return {"username": username, "nama": nama, "peran": peran, "sandi_demo": not sandi}


def ubah_sandi_sendiri(s: Session, username: str, lama: str, baru: str) -> dict:
    """Ganti sandi akun sendiri. Sandi lama tetap diminta, supaya sesi yang tertinggal
    terbuka di layar orang lain tidak bisa mengunci pemiliknya keluar."""
    pengguna = s.scalar(select(AppUser).where(AppUser.username == username))
    if pengguna is None:
        raise ValueError(f"Pengguna {username} tidak ditemukan")
    if not periksa_sandi(lama, pengguna.garam, pengguna.sandi_hash):
        raise ValueError("Kata sandi lama salah")
    _periksa_panjang(baru)
    if baru == lama:
        raise ValueError("Kata sandi baru harus berbeda dari yang lama")

    pengguna.garam, pengguna.sandi_hash = _sandi_tersimpan(baru)
    catat_audit(s, None, TAHAP, "sandi_diubah", {"username": username})
    return {"username": username}


def reset_sandi(s: Session, username: str, oleh: str) -> dict:
    """Kembalikan sandi seseorang ke sandi demo, untuk akun yang pemiliknya lupa."""
    pengguna = s.scalar(select(AppUser).where(AppUser.username == username))
    if pengguna is None:
        raise ValueError(f"Pengguna {username} tidak ditemukan")

    pengguna.garam, pengguna.sandi_hash = _sandi_tersimpan(sandi_demo())
    catat_audit(s, None, TAHAP, "sandi_direset", {"username": username, "oleh": oleh})
    return {"username": username}


def ubah_peran_pengguna(s: Session, username: str, kode: str, oleh: str) -> dict:
    pengguna = s.scalar(select(AppUser).where(AppUser.username == username))
    if pengguna is None:
        raise ValueError(f"Pengguna {username} tidak ditemukan")
    if s.scalar(select(Role).where(Role.kode == kode)) is None:
        raise ValueError(f"Peran {kode} tidak ada")

    # Sistem tanpa satu pun pengelola akses tidak bisa dibetulkan lewat layar mana pun,
    # jadi pengubahan yang menghabiskan pemegang hak terakhir ditolak.
    if pengguna.peran != kode:
        _jaga_pengelola_terakhir(s, username)

    lama = pengguna.peran
    pengguna.peran = kode
    catat_audit(s, None, TAHAP, "peran_pengguna_diubah",
                {"username": username, "dari": lama, "ke": kode, "oleh": oleh})
    return {"username": username, "dari": lama, "ke": kode}


def _jaga_pengelola_terakhir(s: Session, kecuali_username: str) -> None:
    berhak = {
        r.kode
        for r in s.scalars(select(Role))
        if izin.AKSES_KELOLA in izin_peran(s, r.kode)
    }
    sisa = s.scalar(
        select(func.count())
        .select_from(AppUser)
        .where(
            AppUser.peran.in_(berhak),
            AppUser.aktif.is_(True),
            AppUser.username != kecuali_username,
        )
    )
    if not sisa:
        raise ValueError(
            "Ini satu-satunya akun yang boleh mengelola akses. Beri hak itu ke akun lain "
            "lebih dulu, kalau tidak tidak ada yang bisa membetulkannya kembali."
        )


def ubah_aktif_pengguna(s: Session, username: str, aktif: bool, oleh: str) -> dict:
    pengguna = s.scalar(select(AppUser).where(AppUser.username == username))
    if pengguna is None:
        raise ValueError(f"Pengguna {username} tidak ditemukan")
    if not aktif:
        _jaga_pengelola_terakhir(s, username)

    pengguna.aktif = aktif
    catat_audit(s, None, TAHAP, "pengguna_diaktifkan" if aktif else "pengguna_dinonaktifkan",
                {"username": username, "oleh": oleh})
    return {"username": username, "aktif": aktif}


def hapus_pengguna(s: Session, username: str, oleh: str) -> dict:
    """Hapus akun. Klaim dan jejak audit yang menyebut namanya tetap utuh, karena
    keduanya menyimpan username sebagai teks, bukan sambungan ke tabel ini."""
    pengguna = s.scalar(select(AppUser).where(AppUser.username == username))
    if pengguna is None:
        raise ValueError(f"Pengguna {username} tidak ditemukan")
    if username == oleh:
        raise ValueError("Akun yang sedang dipakai masuk tidak bisa dihapus sendiri")
    _jaga_pengelola_terakhir(s, username)

    s.delete(pengguna)
    catat_audit(s, None, TAHAP, "pengguna_dihapus", {"username": username, "oleh": oleh})
    return {"username": username}


def buat_peran(s: Session, kode: str, nama: str, keterangan: str, oleh: str) -> dict:
    kode = kode.strip().lower()
    if not kode or not nama.strip():
        raise ValueError("Kode dan nama peran harus diisi")
    if s.scalar(select(Role).where(Role.kode == kode)) is not None:
        raise ValueError(f"Peran {kode} sudah ada")

    s.add(Role(kode=kode, nama=nama.strip(), keterangan=keterangan.strip(), bawaan=False))
    catat_audit(s, None, TAHAP, "peran_dibuat", {"kode": kode, "nama": nama, "oleh": oleh})
    return {"kode": kode, "nama": nama}


def ubah_peran(s: Session, kode: str, nama: str, keterangan: str, oleh: str) -> dict:
    peran = s.scalar(select(Role).where(Role.kode == kode))
    if peran is None:
        raise ValueError(f"Peran {kode} tidak ada")
    peran.nama = nama.strip() or peran.nama
    peran.keterangan = keterangan.strip()
    catat_audit(s, None, TAHAP, "peran_diubah", {"kode": kode, "nama": peran.nama, "oleh": oleh})
    return {"kode": kode, "nama": peran.nama}


def hapus_peran(s: Session, kode: str, oleh: str) -> dict:
    peran = s.scalar(select(Role).where(Role.kode == kode))
    if peran is None:
        raise ValueError(f"Peran {kode} tidak ada")
    if peran.bawaan:
        raise ValueError("Peran bawaan tidak bisa dihapus, data awal dan uji bergantung padanya")

    dipakai = s.scalar(
        select(func.count()).select_from(AppUser).where(AppUser.peran == kode)
    )
    if dipakai:
        raise ValueError(
            f"Peran ini masih dipakai {dipakai} pengguna. Pindahkan mereka ke peran lain lebih dulu."
        )

    s.query(RolePermission).filter(RolePermission.role_kode == kode).delete()
    s.delete(peran)
    catat_audit(s, None, TAHAP, "peran_dihapus", {"kode": kode, "oleh": oleh})
    return {"kode": kode}


def atur_izin_peran(s: Session, kode: str, daftar: list[str], oleh: str) -> dict:
    peran = s.scalar(select(Role).where(Role.kode == kode))
    if peran is None:
        raise ValueError(f"Peran {kode} tidak ada")

    asing = izin.tidak_dikenal(daftar)
    if asing:
        raise ValueError(f"Hak akses tidak dikenal: {', '.join(asing)}")

    lama = izin_peran(s, kode)
    baru = set(daftar)
    if izin.AKSES_KELOLA in lama and izin.AKSES_KELOLA not in baru:
        _jaga_peran_pengelola_lain(s, kode)

    s.query(RolePermission).filter(RolePermission.role_kode == kode).delete()
    for i in sorted(baru):
        s.add(RolePermission(role_kode=kode, izin=i))

    catat_audit(s, None, TAHAP, "hak_akses_diubah", {
        "peran": kode,
        "ditambah": sorted(baru - lama),
        "dicabut": sorted(lama - baru),
        "oleh": oleh,
    })
    return {"kode": kode, "izin": sorted(baru)}


def _jaga_peran_pengelola_lain(s: Session, kecuali_kode: str) -> None:
    """Cegah hak kelola akses dicabut dari satu-satunya peran yang punya penggunanya."""
    for r in s.scalars(select(Role).where(Role.kode != kecuali_kode)):
        if izin.AKSES_KELOLA not in izin_peran(s, r.kode):
            continue
        ada = s.scalar(
            select(func.count())
            .select_from(AppUser)
            .where(AppUser.peran == r.kode, AppUser.aktif.is_(True))
        )
        if ada:
            return
    raise ValueError(
        "Ini satu-satunya peran berpenghuni yang boleh mengelola akses. Beri hak itu ke "
        "peran lain lebih dulu, kalau tidak layar ini tidak bisa dibuka siapa pun lagi."
    )


def log_aktivitas(s: Session, batas: int = 100) -> list[dict]:
    """Riwayat perubahan akses, terbaru di atas."""
    return [
        {
            "aksi": b.aksi,
            "detail": b.detail,
            "waktu": waktu_iso(b.created_at),
        }
        for b in s.scalars(
            select(AuditLog)
            .where(AuditLog.tahap == TAHAP)
            .order_by(AuditLog.created_at.desc())
            .limit(batas)
        )
    ]
