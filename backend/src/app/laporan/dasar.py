"""Bagian PDF yang dipakai lebih dari satu dokumen: format angka, tanggal, gaya, dan kop.

Yang ditaruh di sini hanya bentuk, bukan isi. Identitas penerbit dikirim sebagai argumen
supaya satu kop bisa dipakai dokumen bengkel maupun dokumen penanggung.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

WIB = timedelta(hours=7)

ABU = colors.Color(0.42, 0.42, 0.45)
GARIS = colors.Color(0.72, 0.72, 0.75)
KEPALA = colors.Color(0.93, 0.93, 0.95)


def rupiah(nilai) -> str:
    """Ubah nilai rupiah jadi teks berpemisah ribuan, kosong kalau nilainya tidak ada."""
    if nilai in (None, ""):
        return ""
    try:
        angka = Decimal(str(nilai))
    except InvalidOperation:
        return str(nilai)
    return f"Rp {angka:,.0f}"


def tanggal_wib(iso: str | None) -> str:
    """Tanggal terbit dokumen, dibaca dalam waktu Jakarta.

    Waktu di database disimpan UTC tanpa penanda zona, jadi zonanya dipasang dulu. Tanpa itu
    klaim yang masuk malam hari tercetak tanggal kemarin.
    """
    if iso:
        waktu = datetime.fromisoformat(iso)
        if waktu.tzinfo is None:
            waktu = waktu.replace(tzinfo=UTC)
    else:
        waktu = datetime.now(UTC)
    lokal = waktu.astimezone(UTC) + WIB
    bulan = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
             "September", "Oktober", "November", "Desember"][lokal.month - 1]
    return f"{lokal.day} {bulan} {lokal.year}"


def gaya() -> dict[str, ParagraphStyle]:
    dasar = getSampleStyleSheet()["Normal"]
    return {
        "sel": ParagraphStyle("sel", parent=dasar, fontSize=7.5, leading=9.5),
        "kepala": ParagraphStyle("kepala", parent=dasar, fontSize=7.5, leading=9.5,
                                 fontName="Helvetica-Bold", alignment=TA_CENTER),
        "judul": ParagraphStyle("judul", parent=dasar, fontSize=10.5, leading=13,
                                fontName="Helvetica-Bold", alignment=TA_CENTER),
        "nama_kop": ParagraphStyle("nama_kop", parent=dasar, fontSize=19, leading=21,
                                   fontName="Helvetica-Bold"),
        "sub_kop": ParagraphStyle("sub_kop", parent=dasar, fontSize=7.5, leading=10,
                                  textColor=ABU),
        "alamat": ParagraphStyle("alamat", parent=dasar, fontSize=7.5, leading=10.5,
                                 alignment=TA_RIGHT),
        "isi": ParagraphStyle("isi", parent=dasar, fontSize=8.5, leading=12),
        "catatan": ParagraphStyle("catatan", parent=dasar, fontSize=7, leading=9.5,
                                  textColor=ABU),
        "kaki": ParagraphStyle("kaki", parent=dasar, fontSize=8, leading=11,
                               alignment=TA_CENTER),
    }


def kop(identitas: dict, g: dict) -> Table:
    """Kop surat penerbit dokumen: nama dan sub di kiri, alamat dan kontak di kanan."""
    kiri = [Paragraph(identitas["nama"], g["nama_kop"])]
    if identitas.get("sub"):
        kiri.append(Paragraph(identitas["sub"], g["sub_kop"]))
    kanan = [Paragraph(b, g["alamat"]) for b in identitas["alamat"]]
    t = Table([[kiri, kanan]], colWidths=[85 * mm, 95 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, -1), 0.9, colors.black),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t
