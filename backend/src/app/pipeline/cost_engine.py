"""Perhitungan biaya klaim dan keputusan total loss.

Seluruh isi modul ini sengaja deterministik, tanpa LLM. Dua klaim dengan temuan yang sama
wajib menghasilkan angka yang sama persis, dan setiap keputusan harus bisa ditunjuk ke
baris aturan yang dipakai. Itu sebabnya `BarisBiaya` menyimpan `alasan_aturan`.

Uang dihitung dengan Decimal, bukan float, supaya penjumlahan harga tidak kena pembulatan
biner. Selisih satu rupiah di total klaim sulit dijelaskan ke adjuster.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

# Rekomendasi yang menahan keputusan karena harga pasar bekasnya belum diketahui. Dibedakan
# dari "repair" supaya tidak ada klaim yang lolos jadi perbaikan cuma karena penyebutnya nol.
REKOMENDASI_HARGA_BELUM_ADA = "harga_belum_ada"

# Bagian muka mobil. Kerusakan di sini yang menandakan benturan depan.
BAGIAN_DEPAN = frozenset({"Front-bumper", "Hood", "Grille", "Headlight", "Fender"})

# Komponen di dalam kap mesin yang ikut rusak pada benturan depan, beserta jumlah bagian
# depan yang harus diganti sebelum komponen itu dianggap ikut rusak. Urutan lapisannya
# mengikuti letak fisiknya: pendinginan duduk tepat di belakang grille dan kena lebih dulu,
# kelistrikan ada di belakangnya, dudukan mesin dan kabel bodi paling dalam.
#
# Berbeda dengan matriks perbaikan yang ambangnya dibaca dari tabel, aturan ini masih di
# kode dan belum bisa diubah tanpa deploy ulang.
PEMICU_BAGIAN_TERSEMBUNYI = [
    (2, ("Radiator", "Kondensor-AC", "Kipas-radiator", "Selang-radiator")),
    (3, ("Tabung-air-radiator", "Box-sekring", "Aki", "Tatakan-aki", "Panel-bodi-depan")),
    (4, ("Dinamo-ampere", "Kabel-mesin", "Dudukan-mesin", "Tabung-oli-power-steering")),
    # Airbag bukan komponen ruang mesin, tapi tetap di sini karena benturan yang sudah
    # merusak empat bagian depan pasti sudah memicunya, dan harganya yang menentukan
    # klaim berakhir total loss atau tidak.
    (4, ("Airbag-pengemudi", "Airbag-penumpang", "Modul-airbag")),
]

# Prioritas operasi saat satu bagian punya lebih dari satu kerusakan. Angka lebih besar
# menang. Mengganti part mengalahkan semua operasi perbaikan, karena bagian yang sudah
# diganti tidak perlu dipoles atau diketok lagi.
PRIORITAS_OPERASI = {
    "touch-up cat": 10,
    "poles": 20,
    "perbaikan karat dan cat": 30,
    "ketok dan cat": 40,
    "cat ulang panel": 50,
    "ganti part": 100,
}


def _rupiah(nilai) -> Decimal:
    """Bulatkan ke rupiah utuh. Harga sparepart di Indonesia tidak mengenal sen."""
    return Decimal(str(nilai)).quantize(Decimal(1), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Temuan:
    """Satu hasil deteksi yang sudah digabung dari mask bagian dan mask kerusakan."""

    part_class: str
    damage_class: str
    rasio_luas: float
    sisi: str | None = None
    jumlah_foto: int = 1
    sumber: str = "deteksi"


@dataclass(frozen=True)
class AturanPerbaikan:
    """Satu baris `repair_matrix`. Rentangnya [rasio_min, rasio_max)."""

    damage_class: str
    rasio_min: float
    rasio_max: float
    operasi: str
    ganti_part: bool

    def cocok(self, damage_class: str, rasio: float) -> bool:
        if self.damage_class != damage_class:
            return False
        if rasio < self.rasio_min:
            return False
        # Batas atas 1.0 berarti "berapa pun luasnya", jadi dibuat inklusif. Kalau tidak,
        # kerusakan yang menutupi 100% bagian justru tidak cocok aturan mana pun.
        if self.rasio_max >= 1.0:
            return rasio <= 1.0
        return rasio < self.rasio_max


@dataclass(frozen=True)
class Part:
    part_class: str
    nama_part: str
    harga: Decimal
    terlihat_dari_luar: bool = True
    nomor_part: str = ""


@dataclass(frozen=True)
class Tarif:
    """Jam standar satu operasi. `part_class` kosong berarti nilai bawaan untuk operasi itu."""

    operasi: str
    jam_standar: float
    tarif_per_jam: Decimal
    part_class: str | None = None


def cari_tarif(operasi: str, part_class: str, daftar: list[Tarif]) -> Tarif:
    """Cari jam standar, utamakan aturan khusus untuk bagian itu sebelum nilai bawaan.

    Mengganti headlamp dan mengganti panel bodi depan sama-sama operasi ganti part, tapi
    lamanya jauh berbeda, jadi bagiannya ikut menentukan.
    """
    bawaan: Tarif | None = None
    for t in daftar:
        if t.operasi != operasi:
            continue
        if t.part_class == part_class:
            return t
        if t.part_class is None:
            bawaan = t
    if bawaan is not None:
        return bawaan
    raise AturanTidakDitemukan(
        f"Operasi '{operasi}' tidak punya jam standar di labor_rate, "
        f"baik khusus untuk '{part_class}' maupun sebagai nilai bawaan"
    )


@dataclass
class BarisBiaya:
    part_class: str
    nama_part: str
    nomor_part: str
    sisi: str | None
    damage_class: str | None
    rasio_luas: float
    operasi: str
    ganti_part: bool
    harga_part: Decimal
    jam_standar: float
    biaya_jasa: Decimal
    sumber: str
    alasan_aturan: str
    # Kerusakan lain di bagian yang sama, yang operasinya sudah tercakup operasi pemenang.
    # Disimpan supaya adjuster tidak menyangka kerusakan itu terlewat.
    kerusakan_lain: list[str] = field(default_factory=list)


@dataclass
class Estimasi:
    baris: list[BarisBiaya] = field(default_factory=list)
    total_part: Decimal = Decimal(0)
    total_jasa: Decimal = Decimal(0)
    total_biaya: Decimal = Decimal(0)
    harga_pasar_bekas: Decimal = Decimal(0)
    total_loss_ratio: float = 0.0
    ambang_total_loss: float = 0.75
    rekomendasi: str = "repair"
    own_risk: Decimal = Decimal(0)
    ditanggung_penanggung: Decimal = Decimal(0)
    harga_tawaran_salvage: Decimal | None = None
    part_tidak_ditemukan: list[str] = field(default_factory=list)


class AturanTidakDitemukan(Exception):
    """Jenis kerusakan tidak punya baris di repair_matrix.

    Sengaja dilempar, bukan diam-diam dilewati. Kerusakan yang tidak punya aturan berarti
    biayanya tidak terhitung, dan klaim yang nilainya kurang dari seharusnya lebih
    berbahaya daripada proses yang berhenti dengan pesan jelas.
    """


def pilih_aturan(
    damage_class: str, rasio_luas: float, matriks: list[AturanPerbaikan]
) -> AturanPerbaikan:
    """Cari satu baris aturan yang cocok untuk jenis kerusakan dan rasio luasnya."""
    for aturan in matriks:
        if aturan.cocok(damage_class, rasio_luas):
            return aturan
    raise AturanTidakDitemukan(
        f"Tidak ada aturan untuk kerusakan '{damage_class}' pada rasio luas {rasio_luas:.2f}"
    )


def gabungkan_temuan(temuan: list[Temuan]) -> list[Temuan]:
    """Ringkas temuan jadi satu baris per kombinasi bagian dan sisi.

    Satu bagian bisa muncul di beberapa foto dengan rasio berbeda karena sudut
    pengambilannya berbeda. Yang dipakai rasio tertinggi, dengan alasan sudut yang paling
    jelas memperlihatkan kerusakan adalah yang paling mendekati keadaan sebenarnya.

    Kalau satu bagian punya beberapa jenis kerusakan sekaligus, semuanya dipertahankan di
    tahap ini. Pemilihan operasi mana yang menang dikerjakan di `hitung_biaya`.
    """
    terkumpul: dict[tuple[str, str | None, str], Temuan] = {}
    jumlah_foto: dict[tuple[str, str | None, str], int] = {}

    for t in temuan:
        kunci = (t.part_class, t.sisi, t.damage_class)
        jumlah_foto[kunci] = jumlah_foto.get(kunci, 0) + t.jumlah_foto
        sebelumnya = terkumpul.get(kunci)
        if sebelumnya is None or t.rasio_luas > sebelumnya.rasio_luas:
            terkumpul[kunci] = t

    hasil = []
    for kunci, t in terkumpul.items():
        hasil.append(
            Temuan(
                part_class=t.part_class,
                damage_class=t.damage_class,
                rasio_luas=t.rasio_luas,
                sisi=t.sisi,
                jumlah_foto=jumlah_foto[kunci],
                sumber=t.sumber,
            )
        )
    hasil.sort(key=lambda t: (t.part_class, t.sisi or "", t.damage_class))
    return hasil


def hitung_biaya(
    temuan: list[Temuan],
    katalog: dict[str, Part],
    matriks: list[AturanPerbaikan],
    tarif: list[Tarif],
) -> tuple[list[BarisBiaya], list[str]]:
    """Ubah daftar temuan jadi baris biaya, satu baris per bagian.

    Kalau satu bagian punya beberapa kerusakan, yang menang adalah operasi dengan
    prioritas tertinggi. Contoh: bumper yang baret sekaligus retak akan diganti, dan
    biaya polesnya tidak ikut ditagihkan karena bagiannya memang sudah diganti.

    Mengembalikan daftar baris biaya dan daftar `part_class` yang tidak ada di katalog.
    Yang tidak ditemukan tidak dibuang diam-diam, tapi dikembalikan supaya pemanggil bisa
    meneruskannya ke pencari padanan.
    """
    per_bagian: dict[tuple[str, str | None], list[tuple[Temuan, AturanPerbaikan]]] = {}
    tidak_ditemukan: list[str] = []

    for t in gabungkan_temuan(temuan):
        if t.part_class not in katalog:
            if t.part_class not in tidak_ditemukan:
                tidak_ditemukan.append(t.part_class)
            continue
        aturan = pilih_aturan(t.damage_class, t.rasio_luas, matriks)
        per_bagian.setdefault((t.part_class, t.sisi), []).append((t, aturan))

    baris: list[BarisBiaya] = []
    for (part_class, sisi), pasangan in sorted(per_bagian.items(), key=lambda x: (x[0][0], x[0][1] or "")):
        temuan_menang, aturan_menang = max(
            pasangan, key=lambda p: PRIORITAS_OPERASI.get(p[1].operasi, 0)
        )
        part = katalog[part_class]
        t = cari_tarif(aturan_menang.operasi, part_class, tarif)

        harga_part = _rupiah(part.harga) if aturan_menang.ganti_part else Decimal(0)
        biaya_jasa = _rupiah(Decimal(str(t.jam_standar)) * t.tarif_per_jam)

        kerusakan_lain = sorted(
            {p[0].damage_class for p in pasangan if p[0] is not temuan_menang and p[0].damage_class}
        )
        alasan = susun_alasan(temuan_menang, aturan_menang)
        if kerusakan_lain:
            alasan += f". Kerusakan lain yang ditemukan ({', '.join(kerusakan_lain)}) tercakup operasi ini"

        baris.append(
            BarisBiaya(
                part_class=part_class,
                nama_part=part.nama_part,
                nomor_part=part.nomor_part,
                sisi=sisi,
                damage_class=temuan_menang.damage_class,
                rasio_luas=temuan_menang.rasio_luas,
                operasi=aturan_menang.operasi,
                ganti_part=aturan_menang.ganti_part,
                harga_part=harga_part,
                jam_standar=t.jam_standar,
                biaya_jasa=biaya_jasa,
                sumber=temuan_menang.sumber,
                alasan_aturan=alasan,
                kerusakan_lain=kerusakan_lain,
            )
        )

    baris += bagian_tersembunyi(baris, katalog, tarif)
    return baris, tidak_ditemukan


def bagian_tersembunyi(
    baris: list[BarisBiaya], katalog: dict[str, Part], tarif: list[Tarif]
) -> list[BarisBiaya]:
    """Tambahkan bagian yang ikut rusak tapi tidak terlihat kamera.

    Radiator, kondensor, rangka depan, dan airbag tidak akan pernah muncul di hasil deteksi
    karena tertutup bodi. Tanpa aturan ini, benturan depan berat selalu terhitung terlalu
    murah dan klaim yang seharusnya total loss lolos jadi perbaikan.

    Pemicunya jumlah bagian depan yang harus diganti, bukan luas kerusakan, karena bagian
    depan yang sampai harus diganti berarti benturannya menembus bodi.
    """
    diganti = {
        b.part_class for b in baris if b.ganti_part and b.part_class in BAGIAN_DEPAN
    }
    if not diganti:
        return []

    sudah_ada = {b.part_class for b in baris}
    tambahan: list[BarisBiaya] = []
    for ambang, bagian in PEMICU_BAGIAN_TERSEMBUNYI:
        if len(diganti) < ambang:
            continue
        for part_class in bagian:
            part = katalog.get(part_class)
            if part is None or part_class in sudah_ada:
                continue
            sudah_ada.add(part_class)
            t = cari_tarif("ganti part", part_class, tarif)
            tambahan.append(
                BarisBiaya(
                    part_class=part_class,
                    nama_part=part.nama_part,
                nomor_part=part.nomor_part,
                    sisi=None,
                    damage_class=None,
                    rasio_luas=0.0,
                    operasi="ganti part",
                    ganti_part=True,
                    harga_part=_rupiah(part.harga),
                    jam_standar=t.jam_standar,
                    biaya_jasa=_rupiah(Decimal(str(t.jam_standar)) * t.tarif_per_jam),
                    sumber="aturan",
                    alasan_aturan=(
                        f"Tidak terlihat kamera. Dimasukkan karena {len(diganti)} bagian depan "
                        f"harus diganti ({', '.join(sorted(diganti))}), ambang aturan {ambang}"
                    ),
                )
            )
    return tambahan


# Batas pelabelan luas kerusakan. Rasio luas dihitung di bidang foto, jadi ikut berubah
# mengikuti sudut dan jarak pemotretan. Angka pastinya tidak layak dibaca sebagai hasil ukur,
# yang bisa dipertanggungjawabkan cuma tingkatannya.
SEBARAN = ((0.15, "kecil"), (0.40, "sedang"), (1.01, "luas"))


def sebaran(rasio: float) -> str:
    """Ubah rasio luas jadi satu kata tingkatan yang boleh dibaca orang."""
    for batas, label in SEBARAN:
        if rasio < batas:
            return label
    return SEBARAN[-1][1]


def susun_alasan(temuan: Temuan, aturan: AturanPerbaikan) -> str:
    """Susun alasan operasi tanpa memajang rasio luas sebagai angka hasil ukur."""
    kata = f"kerusakan {sebaran(temuan.rasio_luas)}"
    if aturan.rasio_min <= 0.0 and aturan.rasio_max >= 1.0:
        dasar = "berapa pun luasnya"
    elif aturan.rasio_min > 0.0:
        dasar = f"{kata}, melewati batas {aturan.rasio_min:.0%} luas part"
    else:
        dasar = f"{kata}, masih di bawah batas {aturan.rasio_max:.0%} luas part"
    return f"{temuan.damage_class}, {dasar}, operasi {aturan.operasi}"


def susun_estimasi(
    baris: list[BarisBiaya],
    harga_pasar_bekas: Decimal | None,
    ambang_total_loss: float,
    own_risk: Decimal,
    faktor_salvage: float,
    part_tidak_ditemukan: list[str] | None = None,
) -> Estimasi:
    """Jumlahkan biaya, bandingkan ke harga pasar, lalu putuskan repair atau total loss.

    Ambang mengikuti definisi Constructive Total Loss di PSAKBI: biaya perbaikan yang
    **sama dengan atau lebih besar** dari 75% harga sebenarnya kendaraan. Perhatikan kata
    "sama dengan", jadi rasio tepat di ambang sudah dihitung total loss.

    `harga_pasar_bekas` boleh kosong kalau harganya memang tidak diketahui. Rasionya jadi
    tidak bisa dihitung, dan rekomendasinya ditahan jadi `harga_belum_ada`. Sebelumnya
    kasus ini menghasilkan rasio nol yang lolos jadi rekomendasi perbaikan, sehingga mobil
    yang seharusnya total loss lewat begitu saja tanpa ada yang tahu.
    """
    total_part = _rupiah(sum((b.harga_part for b in baris), Decimal(0)))
    total_jasa = _rupiah(sum((b.biaya_jasa for b in baris), Decimal(0)))
    total_biaya = total_part + total_jasa

    harga_pasar = _rupiah(harga_pasar_bekas) if harga_pasar_bekas is not None else Decimal(0)
    diketahui = harga_pasar > 0
    rasio = float(total_biaya / harga_pasar) if diketahui else 0.0

    est = Estimasi(
        baris=baris,
        total_part=total_part,
        total_jasa=total_jasa,
        total_biaya=total_biaya,
        harga_pasar_bekas=harga_pasar,
        total_loss_ratio=rasio,
        ambang_total_loss=ambang_total_loss,
        part_tidak_ditemukan=list(part_tidak_ditemukan or []),
    )

    if not diketahui:
        est.rekomendasi = REKOMENDASI_HARGA_BELUM_ADA
        est.own_risk = min(_rupiah(own_risk), total_biaya)
        est.ditanggung_penanggung = total_biaya - est.own_risk
    elif rasio >= ambang_total_loss:
        est.rekomendasi = "total_loss"
        est.harga_tawaran_salvage = _rupiah(harga_pasar * Decimal(str(faktor_salvage)))
        est.own_risk = Decimal(0)
        est.ditanggung_penanggung = Decimal(0)
    else:
        est.rekomendasi = "repair"
        # Own risk tidak boleh membuat tanggungan penanggung jadi negatif. Untuk klaim
        # yang biayanya di bawah own risk, tertanggung menanggung seluruhnya.
        est.own_risk = min(_rupiah(own_risk), total_biaya)
        est.ditanggung_penanggung = total_biaya - est.own_risk

    return est
