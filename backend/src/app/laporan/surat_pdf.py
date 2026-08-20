"""Susun surat yang terbit setelah adjuster menyetujui klaim.

Ada dua bentuk, dan keduanya memakai kerangka yang sama: surat perintah kerja ke bengkel
untuk klaim perbaikan, dan penawaran pembelian kendaraan ke tertanggung untuk klaim total
loss. Sama seperti dokumen estimasi, modul ini tidak menghitung apa pun dan tidak menyentuh
database. Seluruh angka datang sudah jadi dari surat yang tersimpan.

Identitas penanggung di kop sengaja karangan, karena surat yang tampak terbit dari
perusahaan asuransi sungguhan tidak pantas keluar dari sistem contoh.
"""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.laporan.dasar import GARIS, gaya, kop, rupiah, tanggal_wib

PENANGGUNG = {
    "nama": "NUSA ARTHA INSURANCE",
    "alamat": [
        "Jl. Kenanga Raya No. 22, Jakarta Pusat",
        "021-5566778 / 0812-3344-556",
        "klaim@nusaartha.example",
    ],
}


def _blok_kepada(tujuan: str, alamat: str, g: dict) -> list:
    baris = [Paragraph("<b>Kepada</b>", g["isi"]), Paragraph(tujuan or "-", g["isi"])]
    if alamat:
        baris.append(Paragraph(alamat, g["isi"]))
    return baris


def _blok_identitas(klaim: dict, g: dict) -> Table:
    """Identitas kendaraan diambil dari STNK yang difoto surveyor, bukan dari polis."""
    stnk = klaim.get("stnk") or {}

    def dari_stnk(kunci: str, cadangan=None) -> str:
        return str(stnk.get(kunci) or cadangan or "-")

    kiri = [
        ("No. Klaim", klaim.get("nomor_klaim") or "-"),
        ("No. Polis", klaim.get("nomor_polis") or "-"),
        ("Tertanggung", klaim.get("pemegang_polis") or "-"),
    ]
    kanan = [
        ("Merk / Type", f"{dari_stnk('merk')} {dari_stnk('tipe', '')}".strip()),
        ("No. Pol", dari_stnk("nomor_polisi")),
        ("No. Rangka", dari_stnk("nomor_rangka")),
    ]

    baris = [
        [
            Paragraph(a[0], g["sel"]), Paragraph(f": {a[1]}", g["sel"]),
            Paragraph(b[0], g["sel"]), Paragraph(f": {b[1]}", g["sel"]),
        ]
        for a, b in zip(kiri, kanan, strict=True)
    ]
    t = Table(baris, colWidths=[25 * mm, 65 * mm, 25 * mm, 65 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    return t


def _blok_nilai(baris: list[tuple[str, str, bool]], g: dict) -> Table:
    isi = [
        [
            Paragraph(f"<b>{nama}</b>" if tebal else nama, g["sel"]),
            Paragraph(f"<b>{nilai}</b>" if tebal else nilai, g["sel"]),
        ]
        for nama, nilai, tebal in baris
    ]
    t = Table(isi, colWidths=[95 * mm, 45 * mm], hAlign="RIGHT")
    t.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, GARIS),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _tanda_tangan(keputusan: dict, g: dict) -> Table:
    """Yang dicetak waktu keputusan, bukan waktu dokumen ini dibuka.

    Surat boleh dicetak ulang kapan saja, dan tanggalnya harus tetap menunjuk saat
    keputusan itu benar-benar diambil. Nama penanda tangan diisi tangan setelah dicetak.
    """
    tanggal = tanggal_wib(keputusan.get("waktu"))
    isi = [
        [Paragraph("", g["kaki"]), Paragraph(f"Jakarta, {tanggal}", g["kaki"])],
        [Paragraph("", g["kaki"]), Paragraph("<br/><br/><br/>", g["kaki"])],
        [Paragraph("", g["kaki"]), Paragraph("", g["kaki"])],
    ]
    t = Table(isi, colWidths=[135 * mm, 45 * mm])
    t.setStyle(TableStyle([
        ("LINEABOVE", (1, 2), (1, 2), 0.5, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t


def _rakit(klaim: dict, alamat: str, judul: str, nomor: str, kepada: str,
           isi_surat: list[str], nilai: list[tuple[str, str, bool]]) -> bytes:
    keputusan = (klaim.get("keputusan") or [{}])[-1]
    g = gaya()

    penyangga = io.BytesIO()
    dok = SimpleDocTemplate(
        penyangga,
        pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"{judul} {klaim.get('nomor_klaim', '')}".strip(),
        author=PENANGGUNG["nama"],
    )

    blok = [
        kop(PENANGGUNG, g),
        Spacer(1, 5 * mm),
        Paragraph(judul, g["judul"]),
        Paragraph(nomor, g["kepala"]),
        Spacer(1, 5 * mm),
        *_blok_kepada(kepada, alamat, g),
        Spacer(1, 4 * mm),
        _blok_identitas(klaim, g),
        Spacer(1, 4 * mm),
        *[Paragraph(t, g["isi"]) for t in isi_surat],
        Spacer(1, 4 * mm),
        # Angka dan tanda tangan dijaga satu halaman, supaya tidak ada lembar bertanda tangan
        # yang terpisah dari nilai yang ditandatanganinya.
        KeepTogether([
            _blok_nilai(nilai, g),
            Spacer(1, 8 * mm),
            _tanda_tangan(keputusan, g),
        ]),
        Spacer(1, 6 * mm),
    ]
    # Catatan adjuster sengaja tidak dicetak. Isinya catatan kerja internal, sedangkan surat
    # ini keluar ke bengkel dan ke pemegang polis. Catatannya tetap tersimpan di database
    # dan tampil di layar keputusan.
    dok.build(blok)
    return penyangga.getvalue()


def susun_spk(klaim: dict, surat: dict, alamat: str = "") -> bytes:
    """Surat perintah kerja ke bengkel rekanan untuk klaim yang diputus perbaikan."""
    biaya = klaim.get("biaya") or {}
    nilai = [
        ("Total estimasi perbaikan", rupiah(biaya.get("total_biaya")), False),
        ("Own risk, ditagih ke tertanggung", rupiah(biaya.get("own_risk")), False),
        ("Nilai disetujui, dibayar penanggung", rupiah(surat.get("nilai")), True),
    ]
    isi_surat = [
        ("Dengan surat ini bengkel diberi perintah mengerjakan perbaikan kendaraan di atas "
         "sesuai estimasi yang telah disetujui."),
        ("Pekerjaan di luar estimasi tidak ditanggung sebelum ada persetujuan tertulis "
         "berikutnya dari penanggung."),
    ]
    return _rakit(
        klaim, alamat,
        judul="SURAT PERINTAH KERJA",
        nomor=f"Nomor: {surat.get('nomor') or '-'}",
        kepada=surat.get("tujuan") or "-",
        isi_surat=isi_surat,
        nilai=nilai,
    )


def susun_penawaran(klaim: dict, surat: dict, alamat: str = "") -> bytes:
    """Penawaran pembelian kendaraan ke tertanggung untuk klaim yang diputus total loss."""
    biaya = klaim.get("biaya") or {}
    rasio = biaya.get("total_loss_ratio")
    ambang = biaya.get("ambang_total_loss")

    nilai = [
        ("Harga pasar bekas kendaraan", rupiah(surat.get("harga_pasar_bekas")), False),
        ("Faktor salvage", f"{float(surat.get('faktor_salvage') or 0):.0%}", False),
        ("Harga penawaran", rupiah(surat.get("nilai")), True),
    ]
    isi_surat = [
        ("Biaya perbaikan kendaraan di atas melewati ambang total loss, jadi memperbaikinya "
         "tidak lagi masuk akal secara nilai."),
    ]
    if rasio is not None and ambang is not None:
        isi_surat.append(
            f"Total estimasi perbaikan {rupiah(biaya.get('total_biaya'))} setara "
            f"{rasio:.1%} dari harga pasar bekas, sedangkan ambang total loss {ambang:.0%}."
        )
    isi_surat.append(
        "Sebagai gantinya penanggung menawarkan pembelian kendaraan dengan harga di bawah "
        "ini. Penawaran berlaku setelah tertanggung menyatakan setuju secara tertulis."
    )

    return _rakit(
        klaim, alamat,
        judul="PENAWARAN PEMBELIAN KENDARAAN",
        nomor=f"Untuk klaim: {klaim.get('nomor_klaim') or '-'}",
        kepada=surat.get("tujuan") or "-",
        isi_surat=isi_surat,
        nilai=nilai,
    )
