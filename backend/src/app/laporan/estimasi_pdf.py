"""Susun PDF estimasi perbaikan, mengikuti bentuk yang dipakai bengkel di lapangan.

Modul ini tidak menghitung apa pun dan tidak menyentuh database. Seluruh angka datang sudah
jadi dari estimasi yang tersimpan, supaya isi dokumen dan isi layar tidak mungkin berbeda.

Identitas bengkel di kop surat sengaja karangan. Dokumen acuan yang ditiru bentuknya memuat
nama, alamat, dan tanda tangan bengkel sungguhan, dan menerbitkan estimasi yang tampak
berasal dari mereka dengan angka yang bukan dari mereka bukan sesuatu yang pantas dikirim
sistem ini.
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

from app.laporan.dasar import GARIS, KEPALA, gaya, kop, rupiah, tanggal_wib

BENGKEL = {
    "nama": "KARYA PRIMA",
    "alamat": [
        "Jl. Merpati Raya No. 18, Jakarta Selatan",
        "Jl. Cendrawasih No. 4, Depok",
        "021-7788990 / 0811-2233-445",
        "estimasi@karyaprima.example",
    ],
}


def _blok_identitas(klaim: dict, alamat: str, g: dict) -> Table:
    stnk = klaim.get("stnk") or {}

    def dari_stnk(kunci: str, cadangan) -> str:
        """STNK adalah sumber utama karena itu yang benar-benar difoto di lapangan."""
        return str(stnk.get(kunci) or cadangan or "-")

    kiri = [
        ("No. Klaim", klaim.get("nomor_klaim") or "-"),
        ("No. Polis", klaim.get("nomor_polis") or "-"),
        ("Tertanggung", klaim.get("pemegang_polis") or "-"),
        ("Alamat Tertanggung", alamat or "-"),
    ]
    # Merk, tipe, nomor polisi, dan tahun diambil dari STNK yang difoto surveyor, bukan dari
    # polis, supaya dokumen ini memuat kendaraan yang benar-benar disurvei.
    kanan = [
        ("No. Rangka", dari_stnk("nomor_rangka", None)),
        ("Merk / Type", f"{dari_stnk('merk', None)} {dari_stnk('tipe', '')}".strip()),
        ("No. Pol", dari_stnk("nomor_polisi", None)),
        ("Tahun", dari_stnk("tahun", klaim.get("kendaraan"))),
    ]

    baris = [
        [
            Paragraph(a[0], g["sel"]), Paragraph(f": {a[1]}", g["sel"]),
            Paragraph(b[0], g["sel"]), Paragraph(f": {b[1]}", g["sel"]),
        ]
        for a, b in zip(kiri, kanan, strict=True)
    ]
    t = Table(baris, colWidths=[28 * mm, 62 * mm, 25 * mm, 65 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    return t


def _label_operasi(baris: dict) -> str:
    """Nama baris beserta sisinya, supaya fender kiri dan kanan tidak terbaca sama.

    Baris hasil deteksi memakai nama kelas model apa adanya, sama seperti di layar, supaya
    satu bagian tidak punya dua nama berbeda. Baris simulasi tidak ada di dataset, jadi
    tetap nama Indonesianya.
    """
    if baris.get("sumber") == "deteksi":
        nama = baris.get("part_class") or baris.get("nama_part") or "-"
    else:
        nama = baris.get("nama_part") or baris.get("part_class") or "-"
    sisi = baris.get("sisi")
    keterangan = f"{nama} {sisi}" if sisi else nama
    operasi = baris.get("operasi")
    return f"{keterangan} ({operasi})" if operasi else keterangan


def _tabel_rincian(baris_biaya: list[dict], biaya: dict, g: dict) -> Table:
    kepala = [Paragraph(t, g["kepala"]) for t in
              ("NO", "NAMA PART", "JASA", "NO. PART", "HARGA")]
    isi = [kepala]
    for i, b in enumerate(baris_biaya, start=1):
        isi.append([
            Paragraph(str(i), g["sel"]),
            Paragraph(_label_operasi(b), g["sel"]),
            Paragraph(rupiah(b.get("biaya_jasa")), g["sel"]),
            Paragraph(b.get("nomor_part") or "-", g["sel"]),
            Paragraph(rupiah(b.get("harga_part")), g["sel"]),
        ])

    isi.append([
        Paragraph("", g["sel"]),
        Paragraph("JUMLAH", g["kepala"]),
        Paragraph(rupiah(biaya.get("total_jasa")), g["kepala"]),
        Paragraph("", g["sel"]),
        Paragraph(rupiah(biaya.get("total_part")), g["kepala"]),
    ])

    t = Table(
        isi,
        colWidths=[9 * mm, 85 * mm, 28 * mm, 30 * mm, 28 * mm],
        repeatRows=1,
    )
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, GARIS),
        ("BACKGROUND", (0, 0), (-1, 0), KEPALA),
        ("BACKGROUND", (0, -1), (-1, -1), KEPALA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 1), (2, -1), "RIGHT"),
        ("ALIGN", (4, 1), (4, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    return t


def _blok_total(biaya: dict, g: dict) -> Table:
    """Blok total mengikuti bentuk dokumen acuan, tapi barisnya yang benar-benar dipakai.

    Baris cadangan 10% di dokumen acuan tidak ikut. Angka itu tidak ada di perhitungan mana
    pun di sistem ini dan tidak ikut menentukan keputusan total loss, jadi memunculkannya
    berarti menaruh angka yang tidak bisa ditelusuri asalnya.
    """
    rasio = biaya.get("total_loss_ratio")
    ambang = biaya.get("ambang_total_loss")

    baris = [
        ("Total Jasa", rupiah(biaya.get("total_jasa")), False),
        ("Total Sparepart", rupiah(biaya.get("total_part")), False),
        ("Total Estimasi", rupiah(biaya.get("total_biaya")), True),
        ("Own Risk (ditanggung tertanggung)", rupiah(biaya.get("own_risk")), False),
        ("Ditanggung Penanggung", rupiah(biaya.get("ditanggung_penanggung")), True),
    ]
    if rasio is not None and ambang is not None:
        baris.append((
            f"Rasio terhadap harga pasar bekas {rupiah(biaya.get('harga_pasar_bekas'))}",
            f"{rasio:.1%}, ambang total loss {ambang:.0%}",
            False,
        ))

    isi = [
        [
            Paragraph(f"<b>{nama}</b>" if tebal else nama, g["sel"]),
            Paragraph(f"<b>{nilai}</b>" if tebal else nilai, g["sel"]),
        ]
        for nama, nilai, tebal in baris
    ]
    t = Table(isi, colWidths=[75 * mm, 45 * mm], hAlign="RIGHT")
    t.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, 2), (-1, 2), 0.5, GARIS),
        ("LINEABOVE", (0, 4), (-1, 4), 0.5, GARIS),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _kaki(klaim: dict, g: dict) -> Table:
    tanggal = tanggal_wib(klaim.get("dibuat"))
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


def _catatan_harga(biaya: dict, klaim: dict, g: dict) -> list:
    """Sebutkan asal harga pasar bekas kalau bukan dari katalog.

    Dokumen ini yang keluar dari sistem dan ikut dibaca orang di luar layar, jadi asal
    angkanya harus ikut tercetak. Rasio total loss dan besar penawaran beli kendaraan
    dihitung dari harga ini, dan pembaca dokumen berhak tahu dari mana harganya datang.
    """
    sumber = biaya.get("harga_pasar_sumber", "")
    if sumber in ("", "database", "database_polis"):
        return []

    if sumber == "tidak_diketahui":
        kepala = "Harga pasar bekas kendaraan ini tidak ada di katalog dan belum diisi."
    elif sumber == "adjuster":
        kepala = (
            "Harga pasar bekas di dokumen ini diisi adjuster, bukan diambil dari katalog."
        )
    else:
        kepala = (
            "Harga pasar bekas di dokumen ini berasal dari pencarian AI di internet, "
            "bukan dari katalog harga. Sumbernya tercantum di bawah dan wajib diperiksa "
            "sebelum angka ini dipakai."
        )

    isi = [Paragraph(f"<b>{kepala}</b>", g["catatan"])]
    if biaya.get("harga_pasar_keterangan"):
        isi.append(Paragraph(biaya["harga_pasar_keterangan"], g["catatan"]))
    for r in biaya.get("harga_rujukan") or []:
        isi.append(Paragraph(f"Sumber: {r.get('judul', '')} &mdash; {r.get('url', '')}",
                             g["catatan"]))
    if biaya.get("harga_dikonfirmasi_oleh"):
        isi.append(Paragraph(f"Disahkan oleh {biaya['harga_dikonfirmasi_oleh']}.",
                             g["catatan"]))
    else:
        isi.append(Paragraph("Belum disahkan siapa pun.", g["catatan"]))

    isi.append(Spacer(1, 4 * mm))
    return isi


def susun_pdf(klaim: dict, alamat: str = "") -> bytes:
    """Rakit satu dokumen estimasi dari hasil klaim yang sudah tersimpan."""
    biaya = klaim.get("biaya") or {}
    baris_biaya = klaim.get("baris_biaya") or []

    penyangga = io.BytesIO()
    dok = SimpleDocTemplate(
        penyangga,
        pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Estimasi {klaim.get('nomor_klaim', '')}".strip(),
        author=BENGKEL["nama"],
    )

    g = gaya()
    isi = [
        kop(BENGKEL, g),
        Spacer(1, 5 * mm),
        Paragraph("ESTIMASI PERBAIKAN KENDARAAN", g["judul"]),
        Spacer(1, 4 * mm),
        _blok_identitas(klaim, alamat, g),
        Spacer(1, 4 * mm),
        _tabel_rincian(baris_biaya, biaya, g),
        Spacer(1, 5 * mm),
        # Blok total dan kaki dijaga tetap satu halaman. Total yang terpisah dari kolomnya
        # membuat pembaca harus membolak-balik halaman untuk tahu angka itu total dari apa.
        KeepTogether([_blok_total(biaya, g), Spacer(1, 8 * mm), _kaki(klaim, g)]),
        Spacer(1, 6 * mm),
        *_catatan_harga(biaya, klaim, g),
    ]

    dok.build(isi)
    return penyangga.getvalue()
