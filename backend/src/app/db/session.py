"""Koneksi database.

Satu skema dipakai di tiga tempat: SQLite saat mengembangkan di laptop, Postgres di
Supabase saat demo, dan Postgres di server internal nanti. Yang berubah cuma alamat
koneksi lewat variabel lingkungan `DATABASE_URL`, kodenya tidak.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base

_ALAMAT_BAWAAN = f"sqlite:///{Path(__file__).resolve().parents[3] / 'dev.db'}"

_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def alamat_database() -> str:
    return os.getenv("DATABASE_URL", _ALAMAT_BAWAAN)


def alamat_database_tersamar() -> str:
    """Alamat database dengan sandinya disamarkan, untuk dicetak ke layar atau log.

    Log server tersimpan dan bisa dibaca orang lain, jadi alamat mentah tidak boleh ikut
    tercetak. Yang disamarkan cuma sandinya, sisanya dibiarkan supaya masih berguna untuk
    memastikan aplikasi menunjuk database yang benar.
    """
    alamat = alamat_database()
    pecah = urlsplit(alamat)
    if not pecah.password:
        return alamat
    pengguna = quote(pecah.username or "", safe="")
    induk = f"{pengguna}:***@{pecah.hostname or ''}"
    if pecah.port:
        induk += f":{pecah.port}"
    return urlunsplit(pecah._replace(netloc=induk))


def _nyalakan_kunci_asing(engine: Engine) -> None:
    """SQLite mengabaikan kunci asing kecuali dinyalakan per koneksi.

    Tanpa ini laptop menerima urutan hapus yang ditolak Postgres, dan kesalahannya baru
    terlihat setelah deployment.
    """
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _(koneksi, _rekaman):
        koneksi.execute("PRAGMA foreign_keys=ON")


def get_engine() -> Engine:
    global _engine, _Session
    if _engine is None:
        # Koneksi diperiksa dulu sebelum dipakai. Backend hidup terus sementara Postgres
        # memutus koneksi yang lama menganggur, jadi tanpa ini permintaan pertama sesudah
        # aplikasi lama tidak dipakai gagal sekali dengan pesan koneksi ditutup server.
        _engine = create_engine(alamat_database(), future=True, pool_pre_ping=True)
        _nyalakan_kunci_asing(_engine)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def buat_tabel(engine: Engine | None = None) -> None:
    Base.metadata.create_all(engine or get_engine())


@contextmanager
def sesi() -> Iterator[Session]:
    """Buka sesi, commit kalau sukses, rollback kalau ada error."""
    if _Session is None:
        get_engine()
    assert _Session is not None
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
