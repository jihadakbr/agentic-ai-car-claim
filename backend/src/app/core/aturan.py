"""Nilai awal untuk tabel aturan dan konfigurasi.

Isi modul ini dipakai sekali saat mengisi database, bukan dibaca langsung saat sistem
berjalan. Sistem selalu membaca dari tabel, supaya ambang bisa diubah tanpa deploy ulang
dan perubahannya tercatat di audit log.

Kelas kerusakan dan kelas bagian mengikuti dataset Car Parts and Car Damages dari
Humans in the Loop, dan namanya harus sama persis dengan keluaran model deteksi.
"""

# 21 kelas bagian dari model deteksi. `License-plate` ikut karena area plat dipakai untuk
# pemeriksaan kecocokan dengan STNK, bukan sebagai bagian yang bisa diklaim.
KELAS_BAGIAN = [
    "Windshield",
    "Back-windshield",
    "Front-window",
    "Back-window",
    "Front-door",
    "Back-door",
    "Front-wheel",
    "Back-wheel",
    "Front-bumper",
    "Back-bumper",
    "Headlight",
    "Tail-light",
    "Hood",
    "Trunk",
    "License-plate",
    "Mirror",
    "Roof",
    "Grille",
    "Rocker-panel",
    "Quarter-panel",
    "Fender",
]

# Bagian yang tidak pernah masuk perhitungan biaya klaim.
BAGIAN_BUKAN_KLAIM = {"License-plate"}

# Kelas kerusakan yang dipakai sistem. Lebih sedikit daripada yang dikeluarkan model,
# lihat GABUNG_KERUSAKAN.
KELAS_KERUSAKAN = [
    "Dent",
    "Scratch",
    "Broken part",
    "Missing part",
]

# Nama kelas dari model deteksi ke nama yang dipakai sistem.
#
# Empat kelas permukaan digabung karena model tidak bisa membedakannya: mAP50-nya berturut
# 0,001 sampai 0,052, sementara manusia pun sulit memisahkan cat terkelupas dari baret di
# foto. Cracked digabung ke Broken part karena aturan biayanya sudah identik, ganti part
# tanpa ambang luas, jadi penggabungannya tidak mengubah satu rupiah pun.
#
# Kelas yang bertahan memetakan ke dirinya sendiri, supaya peta ini tetap benar kalau suatu
# saat bobotnya memang cuma punya empat kelas.
GABUNG_KERUSAKAN = {
    "Dent": "Dent",
    "Scratch": "Scratch",
    "Paint chip": "Scratch",
    "Flaking": "Scratch",
    "Corrosion": "Scratch",
    "Broken part": "Broken part",
    "Cracked": "Broken part",
    "Missing part": "Missing part",
}

# Matriks ganti-atau-perbaiki. Rentang rasio ditulis [min, max), kecuali max 1.0 yang
# berarti "berapa pun luasnya".
#
# Ambang di sini adalah titik awal yang masuk akal, bukan hasil kalibrasi dari data. Nilai
# sebenarnya disetel setelah model dilatih dan sebaran rasio luas bisa diamati dari hasil
# deteksi sungguhan.
MATRIKS_PERBAIKAN = [
    # damage_class, rasio_min, rasio_max, operasi, ganti_part, keterangan
    ("Scratch", 0.0, 0.05, "touch-up cat", False, "Cat tergores setempat, ditambal"),
    ("Scratch", 0.05, 0.15, "poles", False, "Baret tipis, cukup dipoles"),
    ("Scratch", 0.15, 1.0, "cat ulang panel", False, "Baret luas, panel dicat ulang"),
    ("Dent", 0.0, 0.25, "ketok dan cat", False, "Penyok masih layak diketok"),
    ("Dent", 0.25, 1.0, "ganti part", True, "Penyok terlalu luas untuk diketok"),
    ("Broken part", 0.0, 1.0, "ganti part", True, "Pecah, patah, atau retak"),
    ("Missing part", 0.0, 1.0, "ganti part", True, "Bagian hilang setelah benturan"),
]

# Jam standar bawaan per operasi, dipakai kalau bagiannya tidak punya aturan khusus.
# Tarif per jam sama untuk semua operasi karena mengikuti satu tarif bengkel rekanan.
TARIF_PER_JAM = 350_000
JAM_STANDAR_BAWAAN = {
    "touch-up cat": 0.5,
    "poles": 2.0,
    "perbaikan karat dan cat": 3.0,
    "ketok dan cat": 3.0,
    "cat ulang panel": 4.0,
    "ganti part": 2.5,
}

# Jam standar khusus untuk mengganti bagian tertentu. Mengganti headlamp jauh lebih cepat
# daripada mengganti panel bodi depan, jadi jam seragam akan salah jauh.
JAM_STANDAR_GANTI = {
    "Front-bumper": 2.0,
    "Back-bumper": 2.0,
    "Hood": 2.0,
    "Fender": 2.5,
    "Headlight": 0.8,
    "Tail-light": 0.8,
    "Grille": 0.5,
    "Windshield": 2.5,
    "Back-windshield": 2.5,
    "Front-window": 1.5,
    "Back-window": 1.5,
    "Front-door": 3.0,
    "Back-door": 3.0,
    "Mirror": 0.6,
    "Roof": 8.0,
    "Trunk": 2.0,
    "Rocker-panel": 4.0,
    "Quarter-panel": 6.0,
    "Front-wheel": 0.5,
    "Back-wheel": 0.5,
    # Komponen di dalam kap mesin. Tidak terlihat dari luar, jadi masuk lewat aturan bukan
    # lewat deteksi. Jam bongkar pasangnya lebih besar daripada part bodi dengan harga
    # setara, karena harus melepas komponen lain dulu untuk mencapainya.
    "Radiator": 2.0,
    "Kondensor-AC": 2.5,
    "Kipas-radiator": 1.5,
    "Selang-radiator": 0.8,
    "Tabung-air-radiator": 0.5,
    "Box-sekring": 1.5,
    "Aki": 0.3,
    "Tatakan-aki": 0.6,
    "Dinamo-ampere": 1.5,
    "Kabel-mesin": 6.0,
    "Dudukan-mesin": 2.0,
    "Tabung-oli-power-steering": 1.0,
    "Panel-bodi-depan": 5.0,
    "Airbag-pengemudi": 1.0,
    "Airbag-penumpang": 1.5,
    "Modul-airbag": 0.4,
}

# Konfigurasi bisnis. Nilai disimpan sebagai teks di tabel `config`, sesuai bentuk
# penyimpanannya, dan diubah ke angka saat dibaca.
KONFIGURASI = {
    "ambang_total_loss": (
        "0.75",
        (
            "Batas Constructive Total Loss menurut PSAKBI: biaya perbaikan sama dengan "
            "atau lebih besar dari 75% harga sebenarnya kendaraan sesaat sebelum kejadian"
        ),
    ),
    "own_risk": (
        "300000",
        "Risiko sendiri per kejadian yang ditanggung tertanggung, mengikuti ketentuan OJK",
    ),
    "faktor_salvage": (
        "0.30",
        (
            "Pengali harga pasar bekas untuk menghitung harga penawaran beli kendaraan "
            "yang dinyatakan total loss"
        ),
    ),
    "ambang_confidence_part": ("0.35", "Batas keyakinan minimum untuk menerima mask bagian"),
    "ambang_confidence_damage": (
        "0.35",
        "Batas keyakinan minimum untuk menerima mask kerusakan",
    ),
    "ambang_confidence_kendaraan": (
        "0.50",
        (
            "Di bawah ini, foto dianggap belum layak dibaca dan surveyor diminta "
            "memotretnya ulang. Bukan penolakan klaim"
        ),
    ),
    "ambang_ketajaman_foto": (
        "100",
        (
            "Di bawah ini, foto dianggap buram dan diminta ulang. Diukur dari sebaran "
            "perubahan terang antar piksel setelah foto diperkecil, tanpa model"
        ),
    ),
    "ambang_irisan_kerusakan": (
        "0.30",
        (
            "Bagian luas kerusakan yang harus berada di dalam satu mask bagian sebelum "
            "kerusakan itu dianggap milik bagian tersebut"
        ),
    ),
    "ambang_part_tertutup": (
        "0.15",
        (
            "Bagian luas part yang tertutup kerusakan, sebagai syarat alternatif kalau "
            "syarat ambang_irisan_kerusakan tidak terpenuhi. Dibutuhkan untuk benturan "
            "besar yang menyapu banyak bagian sekaligus"
        ),
    ),
    "ambang_phash_identik": (
        "5",
        "Jarak Hamming maksimum antara dua sidik jari foto yang masih dianggap foto sama",
    ),
    "ambang_selisih_rasio_sama": (
        "0.05",
        (
            "Selisih rasio luas yang masih dianggap kerusakan yang sama persis pada cek C7. "
            "Di bawah nilai ini, kerusakan dianggap belum pernah diperbaiki sejak klaim "
            "sebelumnya, bukan kerusakan baru di bagian yang sama"
        ),
    ),
    "min_foto_kerusakan": ("1", "Jumlah minimum foto kerusakan per klaim"),
    "max_foto_kerusakan": ("6", "Jumlah maksimum foto kerusakan per klaim"),
    "max_foto_pelengkap": (
        "12",
        (
            "Jumlah maksimum foto pelengkap per klaim. Foto pelengkap tidak ikut dideteksi "
            "dan tidak memengaruhi biaya, batasnya cuma menahan unggahan berlebihan"
        ),
    ),
    "min_foto_konsisten": (
        "2",
        (
            "Berapa foto minimal yang harus memperlihatkan satu bagian rusak sebelum "
            "cek C3 dianggap lolos"
        ),
    ),
    "min_foto_bagian_diganti": (
        "1",
        (
            "Berapa foto minimal yang harus memperlihatkan satu bagian sebelum bagian itu "
            "boleh diganti. Kurang dari ini, fotonya diminta ulang ke surveyor. Nilainya "
            "menempel ke min_foto_kerusakan: kalau satu foto per klaim diterima, menuntut "
            "dua foto bukti berarti menahan setiap klaim"
        ),
    ),
    "tarif_bengkel_per_jam": (str(TARIF_PER_JAM), "Tarif jasa bengkel rekanan per jam"),
}
