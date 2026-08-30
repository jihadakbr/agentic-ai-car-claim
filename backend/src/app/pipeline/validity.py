"""Tujuh pemeriksaan anti-kecurangan.

Seluruh isi modul ini deterministik, tanpa LLM. Menolak klaim seseorang berdampak pada
uangnya dan bisa digugat, jadi pemeriksaannya harus bisa dijalankan ulang enam bulan
kemudian dan menghasilkan keputusan yang persis sama.

Hasilnya bukan satu skor, tapi tujuh baris terpisah yang masing-masing menyimpan alasannya
sendiri dalam bahasa manusia. Alasan itu muncul apa adanya di layar adjuster, jadi ditulis
untuk dibaca orang asuransi, bukan programmer.

Dua tingkat kegagalan:

- **Hard fail** membuat klaim berstatus tidak valid.
- **Soft flag** cuma menandai sesuatu yang perlu dilihat manusia.

Klaim yang tidak valid **tidak menghentikan** perhitungan biaya. Adjuster tetap butuh tahu
nilai kerusakannya, misalnya kalau ternyata platnya cuma tertutup lumpur dan setelah dicek
manual mobilnya memang benar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

HARD = "hard"
SOFT = "soft"

VALID = "valid"
PERLU_REVIEW = "perlu_review"
INVALID = "invalid"


@dataclass
class TemuanFoto:
    """Satu bagian rusak yang terdeteksi di satu foto."""

    part_class: str
    damage_class: str
    confidence: float
    sisi: str | None = None


@dataclass
class FotoKerusakan:
    """Satu foto kerusakan beserta seluruh hasil pemeriksaannya."""

    id: str
    phash: str | None = None
    confidence_kendaraan: float = 0.0
    temuan: list[TemuanFoto] = field(default_factory=list)
    plat_terbaca: str | None = None


@dataclass
class HasilStnk:
    """Hasil pembacaan foto STNK. Field yang gagal terbaca bernilai None."""

    merk: str | None = None
    tipe: str | None = None
    tahun: int | None = None
    nomor_polisi: str | None = None
    nomor_rangka: str | None = None
    nomor_mesin: str | None = None
    nama_pemilik: str | None = None


@dataclass
class TemuanKlaim:
    """Satu kerusakan pada klaim yang sedang diproses, sudah digabung dari semua fotonya."""

    part_class: str
    sisi: str | None
    damage_class: str | None
    rasio_luas: float


@dataclass
class TemuanRiwayat(TemuanKlaim):
    """Kerusakan yang sama bentuknya, tapi berasal dari klaim lain pada polis yang sama."""

    nomor_klaim: str
    status: str


@dataclass
class DataPolis:
    nomor_polisi: str
    nomor_rangka: str
    nomor_mesin: str
    nama_pemegang: str


@dataclass
class Ambang:
    # Keyakinan kendaraan tidak lagi dipakai pemeriksaan mana pun di sini. Ambangnya pindah
    # ke gerbang kelayakan foto, yang menjawabnya dengan minta foto ulang, bukan menolak.
    confidence_damage: float = 0.35
    phash_identik: int = 5
    min_foto_konsisten: int = 2
    ambang_foto_untuk_c3: int = 4
    kemiripan_nama_minimum: float = 0.85
    # Selisih rasio luas yang masih dianggap kerusakan yang sama persis. Kerusakan yang
    # tidak diperbaiki luasnya praktis tidak berubah dari tahun ke tahun.
    selisih_rasio_sama: float = 0.05


@dataclass
class HasilCek:
    kode: str
    nama: str
    lolos: bool
    tingkat: str | None
    alasan: str
    detail: dict = field(default_factory=dict)


FIELD_WAJIB_STNK = ("merk", "tipe", "tahun", "nomor_polisi", "nomor_rangka")


def normalkan_plat(plat: str | None) -> str:
    """Samakan bentuk plat sebelum dibandingkan.

    `B 1234 XYZ`, `b1234xyz`, dan `B-1234-XYZ` semuanya jadi `B1234XYZ`. Tanpa ini,
    perbedaan spasi saja sudah bikin pemeriksaan gagal padahal platnya sama.
    """
    if not plat:
        return ""
    return "".join(c for c in plat.upper() if c.isalnum())


def jarak_hamming_hex(a: str, b: str) -> int | None:
    """Hitung selisih bit antara dua sidik jari gambar.

    Mengembalikan None kalau salah satunya tidak bisa dibaca sebagai bilangan heksadesimal,
    yang berarti perbandingannya tidak bisa dilakukan, bukan berarti fotonya berbeda.
    """
    try:
        x, y = int(a, 16), int(b, 16)
    except (TypeError, ValueError):
        return None
    return (x ^ y).bit_count()


def kemiripan_nama(a: str, b: str) -> float:
    """Angka 0 sampai 1. Dipakai supaya salah baca satu huruf tidak menggagalkan klaim."""
    bersih_a = " ".join((a or "").upper().split())
    bersih_b = " ".join((b or "").upper().split())
    if not bersih_a or not bersih_b:
        return 0.0
    return SequenceMatcher(None, bersih_a, bersih_b).ratio()


def cek_c1_ada_kerusakan(foto: list[FotoKerusakan], ambang: Ambang) -> HasilCek:
    """Pastikan kerusakannya benar ada, bukan mobil mulus yang diajukan sebagai klaim."""
    jumlah = sum(
        1 for f in foto for t in f.temuan if t.confidence >= ambang.confidence_damage
    )
    if jumlah == 0:
        return HasilCek("C1", "Kerusakannya benar ada", False, HARD,
                        "Tidak ada kerusakan terdeteksi di satu pun foto")
    return HasilCek("C1", "Kerusakannya benar ada", True, None,
                    f"{jumlah} kerusakan terdeteksi di atas ambang keyakinan")


def cek_c2_foto_tidak_dipakai_ulang(
    foto: list[FotoKerusakan], phash_klaim_lain: dict[str, str], ambang: Ambang
) -> HasilCek:
    """Bandingkan sidik jari tiap foto ke seluruh foto klaim lain di database.

    Percobaan yang dicegah: mengambil foto klaim lama yang sudah dibayar, menyimpannya ulang
    supaya berkasnya berbeda, lalu mengajukannya sebagai klaim baru. Sidik jari isi gambar
    tetap mengenalinya karena yang dibandingkan gambarnya, bukan susunan berkasnya.
    """
    kembar: list[dict] = []
    for f in foto:
        if not f.phash:
            continue
        for phash_lain, klaim_lain in phash_klaim_lain.items():
            jarak = jarak_hamming_hex(f.phash, phash_lain)
            if jarak is not None and jarak <= ambang.phash_identik:
                kembar.append({"foto": f.id, "klaim_lain": klaim_lain, "jarak": jarak})

    if not kembar:
        return HasilCek("C2", "Foto tidak dipakai ulang", True, None,
                        "Tidak ada foto yang cocok dengan klaim mana pun sebelumnya")

    persis = [k for k in kembar if k["jarak"] == 0]
    if persis:
        daftar = ", ".join(sorted({k["klaim_lain"] for k in persis}))
        return HasilCek("C2", "Foto tidak dipakai ulang", False, HARD,
                        f"Ada foto yang identik dengan foto klaim {daftar}",
                        {"kembar": kembar})

    daftar = ", ".join(sorted({k["klaim_lain"] for k in kembar}))
    return HasilCek("C2", "Foto tidak dipakai ulang", False, SOFT,
                    f"Ada foto yang sangat mirip dengan foto klaim {daftar}, perlu dilihat manual",
                    {"kembar": kembar})


def cek_c3_konsisten_antar_sudut(foto: list[FotoKerusakan], ambang: Ambang) -> HasilCek:
    """Bagian yang rusak seharusnya terlihat di lebih dari satu sudut.

    Cuma dijalankan kalau fotonya cukup banyak. Untuk klaim dengan tiga foto, wajar kalau
    satu bagian cuma tertangkap sekali, jadi memeriksanya justru menghasilkan tuduhan palsu.
    """
    if len(foto) < ambang.ambang_foto_untuk_c3:
        return HasilCek("C3", "Konsisten antar sudut", True, None,
                        f"Cuma {len(foto)} foto, pemeriksaan antar sudut dilewati")

    hitung: dict[tuple[str, str | None], int] = {}
    for f in foto:
        terlihat = {(t.part_class, t.sisi) for t in f.temuan}
        for kunci in terlihat:
            hitung[kunci] = hitung.get(kunci, 0) + 1

    sendirian = [k for k, n in hitung.items() if n < ambang.min_foto_konsisten]
    if not sendirian:
        return HasilCek("C3", "Konsisten antar sudut", True, None,
                        f"Semua bagian rusak terlihat di minimal {ambang.min_foto_konsisten} foto")

    nama = ", ".join(
        f"{part}{f' sisi {sisi}' if sisi else ''}" for part, sisi in sorted(
            sendirian, key=lambda k: (k[0], k[1] or "")
        )
    )
    return HasilCek(
        "C3", "Konsisten antar sudut", False, SOFT,
        f"Kerusakan pada {nama} cuma terlihat di 1 dari {len(foto)} foto",
        {"bagian": [{"part_class": p, "sisi": s} for p, s in sendirian]},
    )


def cek_c4_plat_cocok_stnk(foto: list[FotoKerusakan], stnk: HasilStnk) -> HasilCek:
    """Cocokkan plat yang terbaca di bodi mobil dengan Nomor Registrasi di STNK.

    Selisih satu karakter dianggap salah baca, bukan kecurangan. Angka 8 dan huruf B, atau
    angka 0 dan huruf D, memang sering tertukar pada plat yang kotor. Menolak klaim gara-gara
    satu karakter jauh lebih merugikan daripada meminta manusia melihatnya sebentar.
    """
    plat_stnk = normalkan_plat(stnk.nomor_polisi)
    terbaca = [normalkan_plat(f.plat_terbaca) for f in foto if normalkan_plat(f.plat_terbaca)]

    if not plat_stnk:
        return HasilCek("C4", "Plat di bodi cocok STNK", False, SOFT,
                        "Nomor Registrasi di STNK tidak terbaca, pencocokan tidak bisa dilakukan")
    if not terbaca:
        return HasilCek("C4", "Plat di bodi cocok STNK", False, SOFT,
                        "Plat nomor tidak terbaca di satu pun foto, pencocokan dilewati")

    cocok = [p for p in terbaca if p == plat_stnk]
    if cocok:
        return HasilCek("C4", "Plat di bodi cocok STNK", True, None,
                        f"Plat di foto terbaca {plat_stnk} dan sama dengan STNK")

    # Ambil bacaan yang paling dekat, karena satu foto bisa terbaca lebih baik dari lainnya.
    terdekat = min(terbaca, key=lambda p: _selisih_karakter(p, plat_stnk))
    selisih = _selisih_karakter(terdekat, plat_stnk)

    if selisih <= 1:
        return HasilCek(
            "C4", "Plat di bodi cocok STNK", False, SOFT,
            f"Plat di foto terbaca {terdekat}, STNK menyebut {plat_stnk}. "
            "Bedanya cuma satu karakter, kemungkinan besar salah baca",
            {"terbaca": terbaca, "stnk": plat_stnk, "selisih": selisih},
        )
    return HasilCek(
        "C4", "Plat di bodi cocok STNK", False, HARD,
        f"Plat di foto terbaca {terdekat}, STNK menyebut {plat_stnk}. Keduanya jelas berbeda",
        {"terbaca": terbaca, "stnk": plat_stnk, "selisih": selisih},
    )


def _selisih_karakter(a: str, b: str) -> int:
    """Hitung berapa karakter yang berbeda, termasuk selisih panjang."""
    beda = sum(1 for x, y in zip(a, b, strict=False) if x != y)
    return beda + abs(len(a) - len(b))


def cek_c5_stnk_terbaca(stnk: HasilStnk) -> HasilCek:
    """Periksa kelengkapan field wajib dan kewajaran nomor rangka.

    Dipisah dari pencocokan ke polis (C6) dengan sengaja: C5 menjawab "STNK-nya terbaca dan
    masuk akal sendiri", C6 menjawab "STNK-nya milik kendaraan yang diasuransikan".
    """
    from app.core.vin import masalah_format, tahun_cocok

    kosong = [f for f in FIELD_WAJIB_STNK if not getattr(stnk, f)]
    if kosong:
        return HasilCek(
            "C5", "STNK terbaca dan masuk akal", False, HARD,
            f"Field wajib tidak terbaca: {', '.join(kosong)}",
            {"field_kosong": kosong},
        )

    masalah = masalah_format(stnk.nomor_rangka)
    if masalah:
        return HasilCek("C5", "STNK terbaca dan masuk akal", False, SOFT,
                        f"Nomor rangka janggal. {'. '.join(masalah)}",
                        {"masalah": masalah})

    cocok = tahun_cocok(stnk.nomor_rangka, stnk.tahun)
    if cocok is False:
        return HasilCek(
            "C5", "STNK terbaca dan masuk akal", False, SOFT,
            f"Kode tahun di nomor rangka tidak cocok dengan tahun pembuatan {stnk.tahun}. "
            "Pengkodean ini tidak wajib diikuti semua pabrikan, jadi perlu dicek manual",
            {"nomor_rangka": stnk.nomor_rangka, "tahun": stnk.tahun},
        )

    return HasilCek("C5", "STNK terbaca dan masuk akal", True, None,
                    "Field wajib lengkap dan nomor rangka berformat wajar")


def cek_c6_stnk_cocok_polis(stnk: HasilStnk, polis: DataPolis, ambang: Ambang) -> HasilCek:
    """Cocokkan STNK ke polis lewat nomor rangka, nomor polisi, dan nama pemegang.

    Nomor rangka jadi penentu utama karena itu penanda unik tiap mobil, dan nomor polisi bisa
    berubah kalau kendaraan pindah kepemilikan atau mutasi daerah.
    """
    rangka_stnk = (stnk.nomor_rangka or "").strip().upper()
    rangka_polis = (polis.nomor_rangka or "").strip().upper()

    if rangka_stnk and rangka_polis and rangka_stnk != rangka_polis:
        return HasilCek(
            "C6", "STNK cocok dengan polis", False, HARD,
            f"Nomor rangka di STNK ({rangka_stnk}) berbeda dengan yang tercatat di polis "
            f"({rangka_polis})",
            {"stnk": rangka_stnk, "polis": rangka_polis},
        )

    ringan: list[str] = []

    if normalkan_plat(stnk.nomor_polisi) != normalkan_plat(polis.nomor_polisi):
        ringan.append(
            f"nomor polisi berbeda, STNK {stnk.nomor_polisi} versus polis {polis.nomor_polisi}"
        )

    mirip = kemiripan_nama(stnk.nama_pemilik or "", polis.nama_pemegang)
    if stnk.nama_pemilik and mirip < ambang.kemiripan_nama_minimum:
        ringan.append(
            f"nama pemilik berbeda, STNK {stnk.nama_pemilik} versus polis {polis.nama_pemegang}"
        )

    if ringan:
        return HasilCek("C6", "STNK cocok dengan polis", False, SOFT,
                        "Nomor rangka cocok, tapi " + "; ".join(ringan),
                        {"kemiripan_nama": round(mirip, 3)})

    return HasilCek("C6", "STNK cocok dengan polis", True, None,
                    "Nomor rangka, nomor polisi, dan nama pemilik cocok dengan polis")


def cari_kerusakan_lama(
    temuan: TemuanKlaim, riwayat: list[TemuanRiwayat], selisih_maks: float
) -> TemuanRiwayat | None:
    """Cari kerusakan di klaim lama yang bentuknya sama persis dengan temuan ini.

    Dipakai dua kali dengan aturan yang sama: sekali oleh C7 untuk menilai klaimnya, sekali
    saat detail klaim dibaca untuk mengusulkan penilaian per baris. Satu fungsi supaya
    keduanya tidak mungkin berbeda jawaban.

    Yang dibandingkan bagian, sisi, jenis kerusakan, dan luasnya. Luas ikut karena bagian
    yang sudah diperbaiki lalu rusak lagi hampir selalu punya luas yang berbeda jauh.

    Sisi yang kosong di salah satu pihak cocok dengan sisi mana pun. Pemeriksaan ini
    bertugas menangkap kerusakan lama yang belum diperbaiki, dan melewatkannya lebih
    merugikan daripada menandainya untuk ditinjau adjuster.
    """
    kandidat = [
        r
        for r in riwayat
        if (r.part_class, r.damage_class) == (temuan.part_class, temuan.damage_class)
        and (r.sisi is None or temuan.sisi is None or r.sisi == temuan.sisi)
        and abs(r.rasio_luas - temuan.rasio_luas) <= selisih_maks
    ]
    if not kandidat:
        return None
    return min(kandidat, key=lambda r: abs(r.rasio_luas - temuan.rasio_luas))


def cek_c7_bagian_pernah_diklaim(
    temuan: list[TemuanKlaim], riwayat: list[TemuanRiwayat], ambang: Ambang
) -> HasilCek:
    """Tandai kerusakan yang sudah pernah muncul di klaim lain pada polis yang sama.

    Percobaan yang dicegah: mengajukan klaim, membiarkan sebagian kerusakannya tidak
    diperbaiki, lalu mengajukannya lagi tahun berikutnya seolah kerusakan baru.

    Selalu soft flag, tidak pernah membatalkan klaim. Kerusakan lama di satu bagian tidak
    membuat bagian lain di klaim yang sama ikut diragukan, dan bisa saja bagian itu memang
    rusak lagi oleh kejadian yang sekarang.
    """
    if not riwayat:
        return HasilCek("C7", "Bukan kerusakan lama", True, None,
                        "Polis ini belum punya klaim sebelumnya di sistem")

    cocok = []
    for t in temuan:
        r = cari_kerusakan_lama(t, riwayat, ambang.selisih_rasio_sama)
        if r is None:
            continue
        cocok.append({
            "part_class": t.part_class,
            "sisi": t.sisi,
            "damage_class": t.damage_class,
            "rasio_sekarang": round(t.rasio_luas, 4),
            "rasio_dulu": round(r.rasio_luas, 4),
            "klaim_lama": r.nomor_klaim,
            "status_klaim_lama": r.status,
        })

    if not cocok:
        return HasilCek("C7", "Bukan kerusakan lama", True, None,
                        "Tidak ada kerusakan yang cocok dengan klaim sebelumnya pada polis ini")

    rincian = "; ".join(
        f"{c['part_class']}{' sisi ' + c['sisi'] if c['sisi'] else ''} {c['damage_class']} "
        f"pernah diklaim di {c['klaim_lama']} (status {c['status_klaim_lama']}) "
        f"seluas {c['rasio_dulu']:.1%}, sekarang {c['rasio_sekarang']:.1%}"
        for c in cocok
    )
    return HasilCek("C7", "Bukan kerusakan lama", False, SOFT,
                    f"Ada kerusakan yang sudah ada sebelum kejadian ini: {rincian}",
                    {"cocok": cocok})


def tentukan_verdict(hasil: list[HasilCek]) -> str:
    """Satu hard fail sudah cukup membuat klaim tidak valid."""
    if any(h.tingkat == HARD for h in hasil):
        return INVALID
    if any(h.tingkat == SOFT for h in hasil):
        return PERLU_REVIEW
    return VALID


def jalankan_semua(
    foto: list[FotoKerusakan],
    stnk: HasilStnk,
    polis: DataPolis,
    phash_klaim_lain: dict[str, str],
    ambang: Ambang | None = None,
    temuan_klaim: list[TemuanKlaim] | None = None,
    riwayat_polis: list[TemuanRiwayat] | None = None,
    foto_belum_diperiksa: list[FotoKerusakan] | None = None,
) -> tuple[list[HasilCek], str]:
    """Jalankan seluruh pemeriksaan, kembalikan hasilnya beserta verdict akhir.

    Semuanya selalu dijalankan, tidak ada yang dilewati begitu ada yang gagal. Adjuster
    perlu melihat gambaran utuh, bukan cuma pemeriksaan pertama yang kebetulan gagal.

    Foto yang tidak terbaca tidak dinilai di sini. Itu ditangani gerbang kelayakan foto,
    yang menjawabnya dengan permintaan foto ulang, bukan dengan menolak klaim.

    C2 cuma menilai foto yang belum pernah diperiksa. Foto lama yang sudah ditandai kembar
    tetap tersimpan sebagai bukti, tapi menilainya lagi membuat tandanya tidak pernah bisa
    dijawab: berapa pun foto asli yang dikirim menyusul, foto lamanya tetap kembar.
    """
    a = ambang or Ambang()
    baru = foto if foto_belum_diperiksa is None else foto_belum_diperiksa
    hasil = [
        cek_c1_ada_kerusakan(foto, a),
        cek_c2_foto_tidak_dipakai_ulang(baru, phash_klaim_lain, a),
        cek_c3_konsisten_antar_sudut(foto, a),
        cek_c4_plat_cocok_stnk(foto, stnk),
        cek_c5_stnk_terbaca(stnk),
        cek_c6_stnk_cocok_polis(stnk, polis, a),
        cek_c7_bagian_pernah_diklaim(temuan_klaim or [], riwayat_polis or [], a),
    ]
    return hasil, tentukan_verdict(hasil)
