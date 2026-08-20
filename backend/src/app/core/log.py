"""Membersihkan keluaran terminal dari kebisingan yang bukan kesalahan program."""

import logging

_DIREDAM = (ConnectionResetError, ConnectionAbortedError)


class _SaringGalatKoneksi(logging.Filter):
    """Buang catatan yang isinya cuma koneksi diputus browser.

    Browser boleh memutus koneksi kapan saja, misalnya saat halaman pindah atau gambar
    sudah cukup dimuat. Di Windows, asyncio tetap memanggil shutdown pada soket yang sudah
    mati, lalu penangan bawaannya mencetak traceback penuh. Tidak ada permintaan yang
    gagal, tapi terminal jadi penuh sehingga log yang sungguhan sulit dicari.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        galat = record.exc_info[1] if record.exc_info else None
        return not isinstance(galat, _DIREDAM)


def redam_galat_koneksi() -> None:
    """Pasang saringannya. Cuma satu jenis pengecualian yang dibuang, sisanya tetap muncul."""
    logging.getLogger("asyncio").addFilter(_SaringGalatKoneksi())
