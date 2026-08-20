"""Pengisi data awal.

Semua harga di sini **data buatan**, bukan harga sparepart Toyota atau Daihatsu yang
sebenarnya. Yang dijaga kebenarannya adalah strukturnya, hubungan antar tabel, dan cara
menghitungnya, bukan nilai rupiahnya, dan itu disebutkan terus terang saat presentasi.

Avanza 1.3 G tahun 2013 sengaja dijadikan kendaraan acuan dan harganya dipakai sebagai
dasar uji perhitungan, jadi mengubahnya akan membuat test gagal. Kendaraan lain harganya
diturunkan dari acuan itu lewat satu faktor pengali, supaya katalognya konsisten dan tidak
terlihat seperti angka acak.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import izin
from app.core.aturan import (
    BAGIAN_BUKAN_KLAIM,
    JAM_STANDAR_BAWAAN,
    JAM_STANDAR_GANTI,
    KONFIGURASI,
    MATRIKS_PERBAIKAN,
    TARIF_PER_JAM,
)
from app.core.auth import ADJUSTER, ADMIN, SURVEYOR, garam_baru, hash_sandi, sandi_demo
from app.db.models import (
    AppUser,
    Config,
    LaborRate,
    PartCatalog,
    Policy,
    RepairMatrix,
    Role,
    RolePermission,
    VehicleModel,
)

# username, nama tampil, peran
PENGGUNA = [
    ("surveyor", "Rian Pratama", SURVEYOR),
    ("adjuster", "Doni Wijaya", ADJUSTER),
    ("admin", "Administrator", ADMIN),
]

# Harga acuan untuk Avanza 1.3 G 2013. Baris bertanda "acuan" dipakai di kasus uji
# perhitungan, jadi mengubahnya akan membuat test gagal.
#
# part_class: (nama, harga, terlihat_dari_luar)
HARGA_ACUAN: dict[str, tuple[str, int, bool]] = {
    # Terlihat dari luar, bisa dideteksi model
    "Front-bumper": ("Bumper depan", 2_850_000, True),  # acuan
    "Back-bumper": ("Bumper belakang", 2_650_000, True),
    "Hood": ("Kap mesin", 4_200_000, True),  # acuan
    "Trunk": ("Pintu bagasi", 3_900_000, True),
    "Roof": ("Atap", 7_800_000, True),
    "Fender": ("Fender depan", 2_100_000, True),  # acuan
    "Quarter-panel": ("Panel samping belakang", 4_600_000, True),
    "Rocker-panel": ("Panel samping bawah", 2_300_000, True),
    "Front-door": ("Pintu depan", 5_400_000, True),
    "Back-door": ("Pintu belakang", 5_100_000, True),
    "Windshield": ("Kaca depan", 2_950_000, True),  # acuan
    "Back-windshield": ("Kaca belakang", 2_400_000, True),
    "Front-window": ("Kaca pintu depan", 1_150_000, True),
    "Back-window": ("Kaca pintu belakang", 1_050_000, True),
    "Headlight": ("Headlamp", 3_750_000, True),  # acuan
    "Tail-light": ("Stoplamp", 1_450_000, True),
    "Grille": ("Grille", 1_650_000, True),  # acuan
    "Mirror": ("Spion", 1_250_000, True),
    "Front-wheel": ("Velg dan ban depan", 1_850_000, True),
    "Back-wheel": ("Velg dan ban belakang", 1_850_000, True),
    # Komponen di dalam kap mesin. Tidak akan pernah dideteksi model, masuk lewat aturan
    # yang dipicu tingkat keparahan benturan. Inilah bagian yang paling ingin dibuktikan
    # klien bisa dibaca AI suatu saat nanti, jadi daftarnya dibuat menyerupai isi estimasi
    # bengkel sungguhan, bukan sekadar dua tiga baris.
    "Radiator": ("Radiator", 2_400_000, False),  # acuan
    "Kondensor-AC": ("Kondensor AC", 3_100_000, False),  # acuan
    "Kipas-radiator": ("Kipas radiator dan sroud", 1_850_000, False),
    "Selang-radiator": ("Selang radiator atas dan bawah", 420_000, False),
    "Tabung-air-radiator": ("Tabung air radiator", 285_000, False),
    "Box-sekring": ("Box sekring ruang mesin", 2_150_000, False),
    "Aki": ("Aki", 1_450_000, False),
    "Tatakan-aki": ("Tatakan aki", 320_000, False),
    "Dinamo-ampere": ("Dinamo ampere", 3_450_000, False),
    "Kabel-mesin": ("Kabel bodi ruang mesin", 4_900_000, False),
    "Dudukan-mesin": ("Dudukan mesin", 890_000, False),
    "Tabung-oli-power-steering": ("Tabung oli power steering", 640_000, False),
    "Panel-bodi-depan": ("Panel bodi depan", 5_800_000, False),  # acuan
    "Airbag-pengemudi": ("Airbag pengemudi", 12_500_000, False),  # acuan
    "Airbag-penumpang": ("Airbag penumpang depan", 11_800_000, False),  # acuan
    "Modul-airbag": ("Modul kontrol airbag", 6_200_000, False),  # acuan
}

# merk, tipe, tahun, nama tampil, harga pasar bekas, faktor harga sparepart
KENDARAAN = [
    ("TOYOTA", "F601RM GMMFJJ", 2013, "Toyota Avanza 1.3 G", 95_000_000, 1.00),
    ("TOYOTA", "F653RM GMMFJJ", 2019, "Toyota Avanza 1.3 G", 150_000_000, 1.15),
    ("DAIHATSU", "F601RV GMDFJJ", 2015, "Daihatsu Xenia 1.3 X", 105_000_000, 0.95),
    ("HONDA", "DD4 15C1 MT", 2018, "Honda Brio Satya E", 125_000_000, 1.05),
    ("SUZUKI", "APV GL M/T", 2017, "Suzuki Ertiga GL", 135_000_000, 1.08),
    ("TOYOTA", "F800RE GMDFJJ", 2019, "Toyota Rush TRD Sportivo", 195_000_000, 1.30),
    ("MITSUBISHI", "DG3A GLX M/T", 2020, "Mitsubishi Xpander Ultimate", 215_000_000, 1.35),
    # Harga sengaja dikosongkan. Kendaraan ini yang memicu agent mencari harga pasar bekas
    # sendiri ke internet, sehingga jalur itu bisa didemokan dan diuji tanpa menunggu ada
    # kendaraan asing masuk. Katalog sparepartnya tetap terisi, jadi biayanya tetap
    # terhitung dan yang belum diketahui cuma penyebutnya.
    ("WULING", "AF12 LUX CVT", 2022, "Wuling Almaz RS", None, 1.20),
    # Kendaraan di foto contoh sungguhan dari klien, dipakai folder demo mobil riil. Tahunnya
    # mengikuti kode tahun di nomor rangka yang tercetak di estimasi bengkel aslinya.
    ("TOYOTA", "TGN416R GKMDKD", 2017, "Toyota Kijang Innova 2.4 G", 240_000_000, 1.45),
]

# nomor polis, nomor polisi, nomor rangka, nomor mesin, nama, alamat, indeks kendaraan
POLIS = [
    (
        "POL-2024-0037",
        "B 1234 XYZ",
        "MHKM1BA3JDK012345",
        "1NRF012345",
        "BUDI SANTOSO",
        "Jl. Kebon Jeruk Raya No. 27, Jakarta Barat",
        0,
    ),
    (
        "POL-2024-0112",
        "B 5678 ABC",
        "MHKM1BA3JKK098765",
        "1NRF098765",
        "SITI RAHMAWATI",
        "Jl. Margonda Raya No. 88, Depok",
        1,
    ),
    (
        "POL-2024-0245",
        "D 4411 KLM",
        "MHKF601RVFK044110",
        "3SZF044110",
        "AGUS PRASETYO",
        "Jl. Soekarno Hatta No. 190, Bandung",
        2,
    ),
    (
        "POL-2025-0008",
        "B 9090 PQR",
        "MHRDD4815JJ909090",
        "L15Z909090",
        "DEWI ANGGRAINI",
        "Jl. Boulevard Raya No. 12, Tangerang",
        3,
    ),
    # Polis untuk kendaraan yang harga pasar bekasnya belum ada di katalog.
    (
        "POL-2025-0141",
        "B 7712 WLG",
        "MHRAF12LXNJ771200",
        "L2BZ771200",
        "RAHMAT HIDAYAT",
        "Jl. Ahmad Yani No. 45, Bekasi",
        7,
    ),
    # Polis khusus skenario kerusakan lama. Dipisah dari polis lain supaya cek C7 cuma
    # menyala di folder yang memang menguji itu, tidak mengganggu skenario tetangganya.
    (
        "POL-2025-0203",
        "B 3388 NRA",
        "MHKM1BA3JDK033880",
        "1NRF033880",
        "NURAINI SAFITRI",
        "Jl. Raya Bogor No. 141, Jakarta Timur",
        0,
    ),
    # Polis untuk foto contoh sungguhan. Nomor polisinya mengikuti plat yang terbaca di
    # foto klien supaya pemeriksaan plat terhadap STNK punya bahan yang benar.
    (
        "POL-2025-0177",
        "H 1052 BA",
        "MHFJB8EMXH1025409",
        "2GD1052BA",
        "SLAMET WIDODO",
        "Jl. Pandanaran No. 78, Semarang",
        8,
    ),
]


def _bulatkan_harga(nilai: float) -> Decimal:
    """Bulatkan ke kelipatan 50,000 supaya harganya terlihat seperti harga katalog."""
    return Decimal(round(nilai / 50_000) * 50_000)


def isi_konfigurasi(s: Session) -> int:
    jumlah = 0
    for key, (value, keterangan) in KONFIGURASI.items():
        if s.get(Config, key) is None:
            s.add(Config(key=key, value=value, keterangan=keterangan))
            jumlah += 1
    return jumlah


def isi_peran(s: Session) -> tuple[int, int]:
    """Buat peran bawaan beserta haknya, dan lengkapi hak yang belum ada.

    Kembalikan jumlah peran baru dan jumlah hak yang ditambahkan.

    Hak yang sudah ada tidak pernah dicabut, supaya pencabutan lewat layar Manajemen Akses
    tidak dikembalikan diam-diam. Tapi hak bawaan yang belum ada **ditambahkan**, termasuk
    ke peran yang sudah lama berdiri. Tanpa itu, hak baru yang muncul di versi berikutnya
    tidak akan pernah sampai ke database yang sudah jalan, dan menu yang dijaga hak itu
    hilang tanpa penjelasan.

    Konsekuensinya, mencabut hak bawaan dari peran bawaan tidak bertahan: hak itu kembali
    saat server menyala. Untuk peran yang haknya benar-benar mau dibatasi, buat peran baru
    lewat layar Manajemen Akses, bukan mengurangi peran bawaan.
    """
    peran_baru = 0
    izin_baru = 0
    for p in izin.PERAN_BAWAAN:
        if s.scalar(select(Role).where(Role.kode == p["kode"])) is None:
            s.add(
                Role(kode=p["kode"], nama=p["nama"], keterangan=p["keterangan"], bawaan=True)
            )
            peran_baru += 1

        punya = set(
            s.scalars(
                select(RolePermission.izin).where(RolePermission.role_kode == p["kode"])
            )
        )
        for kode_izin in p["izin"]:
            if kode_izin not in punya:
                s.add(RolePermission(role_kode=p["kode"], izin=kode_izin))
                izin_baru += 1
    return peran_baru, izin_baru


def isi_pengguna(s: Session) -> int:
    """Buat tiga akun contoh. Garamnya berbeda tiap pengguna, jadi sandi sama tetap
    menghasilkan turunan yang berbeda di database."""
    jumlah = 0
    sandi = sandi_demo()
    for username, nama, peran in PENGGUNA:
        if s.scalar(select(AppUser).where(AppUser.username == username)) is not None:
            continue
        garam = garam_baru()
        s.add(
            AppUser(
                username=username,
                nama=nama,
                garam=garam,
                sandi_hash=hash_sandi(sandi, garam),
                peran=peran,
            )
        )
        jumlah += 1
    return jumlah


def isi_matriks_perbaikan(s: Session) -> int:
    if s.scalar(select(RepairMatrix).limit(1)) is not None:
        return 0
    for damage_class, lo, hi, operasi, ganti, keterangan in MATRIKS_PERBAIKAN:
        s.add(
            RepairMatrix(
                damage_class=damage_class,
                rasio_min=lo,
                rasio_max=hi,
                operasi=operasi,
                ganti_part=ganti,
                keterangan=keterangan,
            )
        )
    return len(MATRIKS_PERBAIKAN)


def isi_tarif_jasa(s: Session) -> int:
    if s.scalar(select(LaborRate).limit(1)) is not None:
        return 0
    jumlah = 0
    for operasi, jam in JAM_STANDAR_BAWAAN.items():
        s.add(
            LaborRate(
                operasi=operasi,
                part_class=None,
                jam_standar=jam,
                tarif_per_jam=Decimal(TARIF_PER_JAM),
            )
        )
        jumlah += 1
    for part_class, jam in JAM_STANDAR_GANTI.items():
        s.add(
            LaborRate(
                operasi="ganti part",
                part_class=part_class,
                jam_standar=jam,
                tarif_per_jam=Decimal(TARIF_PER_JAM),
            )
        )
        jumlah += 1
    return jumlah


def isi_kendaraan_dan_katalog(s: Session) -> tuple[int, int]:
    if s.scalar(select(VehicleModel).limit(1)) is not None:
        return 0, 0

    jumlah_part = 0
    for urut, (merk, tipe, tahun, nama, harga_pasar, faktor) in enumerate(KENDARAAN):
        kendaraan = VehicleModel(
            merk=merk,
            tipe=tipe,
            tahun=tahun,
            nama_tampil=nama,
            harga_pasar_bekas=None if harga_pasar is None else Decimal(harga_pasar),
        )
        s.add(kendaraan)
        s.flush()

        for part_class, (nama_part, harga_acuan, terlihat) in HARGA_ACUAN.items():
            if part_class in BAGIAN_BUKAN_KLAIM:
                continue
            # Kendaraan acuan memakai harga apa adanya supaya cocok dengan kasus uji.
            harga = (
                Decimal(harga_acuan) if faktor == 1.00 else _bulatkan_harga(harga_acuan * faktor)
            )
            s.add(
                PartCatalog(
                    vehicle_model_id=kendaraan.id,
                    part_class=part_class,
                    nama_part=nama_part,
                    nomor_part=f"{merk[:2]}{tahun}-{urut:02d}-{part_class[:6].upper()}",
                    asal="OEM",
                    harga=harga,
                    terlihat_dari_luar=terlihat,
                )
            )
            jumlah_part += 1

    return len(KENDARAAN), jumlah_part


def isi_polis(s: Session) -> int:
    if s.scalar(select(Policy).limit(1)) is not None:
        return 0

    kendaraan = list(s.scalars(select(VehicleModel).order_by(VehicleModel.tahun)))
    # Urutan hasil query belum tentu sama dengan urutan KENDARAAN, jadi dicari lewat kunci
    # merk, tipe, dan tahun supaya polis selalu menempel ke kendaraan yang benar.
    peta = {(k.merk, k.tipe, k.tahun): k for k in kendaraan}

    berlaku = datetime.now(UTC) + timedelta(days=180)
    for nomor_polis, nopol, rangka, mesin, nama, alamat, idx in POLIS:
        merk, tipe, tahun = KENDARAAN[idx][0], KENDARAAN[idx][1], KENDARAAN[idx][2]
        s.add(
            Policy(
                nomor_polis=nomor_polis,
                nomor_polisi=nopol,
                nomor_rangka=rangka,
                nomor_mesin=mesin,
                nama_pemegang=nama,
                alamat=alamat,
                vehicle_model_id=peta[(merk, tipe, tahun)].id,
                jenis_pertanggungan="comprehensive",
                berlaku_sampai=berlaku,
            )
        )
    return len(POLIS)


def isi_semua(s: Session) -> dict[str, int]:
    """Isi seluruh tabel master. Aman dijalankan berulang, yang sudah ada tidak digandakan."""
    peran, izin_peran = isi_peran(s)
    hasil = {
        "config": isi_konfigurasi(s),
        "role": peran,
        "role_permission": izin_peran,
        "app_user": isi_pengguna(s),
        "repair_matrix": isi_matriks_perbaikan(s),
        "labor_rate": isi_tarif_jasa(s),
    }
    kendaraan, part = isi_kendaraan_dan_katalog(s)
    hasil["vehicle_model"] = kendaraan
    hasil["part_catalog"] = part
    s.flush()
    hasil["policy"] = isi_polis(s)
    return hasil
