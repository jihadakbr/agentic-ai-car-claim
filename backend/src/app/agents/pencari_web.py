"""Alat pencari di internet, dipakai agent saat harga kendaraan tidak ada di katalog.

Dipisah jadi protokol karena tiga alasan:

- Uji tidak boleh menyentuh internet. Uji yang hasilnya bergantung mesin pencari akan gagal
  di waktu acak dan berhenti dipercaya.
- Produksi nanti dirancang berjalan tanpa cloud sama sekali. Penggantinya cukup satu kelas
  yang membaca sumber harga internal, tanpa menyentuh agent maupun pipeline.
- Mesin pencarinya bisa berubah tanpa mengubah kode lain.

DuckDuckGo dipilih karena tidak perlu mendaftar dan tidak perlu kunci API, jadi tetap nol
biaya. Konsekuensinya dia bisa membatasi kecepatan kalau dipanggil beruntun.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HasilCari:
    judul: str
    url: str
    cuplikan: str


class PencariWeb(Protocol):
    def cari(self, kueri: str, maksimal: int = 5) -> list[HasilCari]: ...


class PencariDuckDuckGo:
    """Pencari sungguhan. Pustakanya diimpor saat dipakai, bukan saat modul ini dimuat."""

    def cari(self, kueri: str, maksimal: int = 5) -> list[HasilCari]:
        try:
            from ddgs import DDGS

            hasil = DDGS().text(kueri, region="id-id", max_results=maksimal)
        except Exception:  # noqa: BLE001
            # Pustaka belum terpasang, tidak ada internet, atau kena pembatasan kecepatan.
            # Daftar kosong berujung ke "harga tidak diketahui" yang jujur, dan itu jauh
            # lebih baik daripada menghentikan klaim atau menebak harganya.
            _log.warning("pencarian web gagal untuk kueri: %s", kueri, exc_info=True)
            return []

        return [
            HasilCari(
                judul=str(r.get("title") or "").strip(),
                url=str(r.get("href") or "").strip(),
                cuplikan=str(r.get("body") or "").strip(),
            )
            for r in hasil or []
            if r.get("href")
        ]


class PencariMati:
    """Tidak mencari apa pun. Dipakai saat pencarian sengaja dimatikan."""

    def cari(self, kueri: str, maksimal: int = 5) -> list[HasilCari]:
        return []
