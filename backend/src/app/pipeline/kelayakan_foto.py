"""Menentukan foto mana yang perlu difoto ulang, sebelum hasilnya dipakai memutuskan.

Yang menentukan cukup tidaknya bukti bukan berapa banyak fotonya, melainkan layak tidaknya
foto itu dibaca. Satu foto tajam lebih berguna daripada tiga foto buram.

Dua pemicu, dan keduanya sengaja dipisah karena masalahnya berbeda:

1. **Model tidak yakin.** Bagian mobil terdeteksi dengan keyakinan rendah, misalnya karena
   sudutnya menyerong, gelap, atau mobilnya cuma terlihat sebagian.
2. **Fotonya buram.** Dihitung langsung dari gambar tanpa model sama sekali. Ini menangkap
   yang luput dari pemicu pertama, sebab model bisa saja yakin pada foto yang manusianya
   sendiri tidak bisa membacanya.

Dinilai per foto, bukan per klaim. Satu foto bermasalah di antara foto yang bagus tetap
diminta ulang, karena foto itulah yang mungkin menyembunyikan kerusakan yang belum terhitung.

Pemicunya sengaja berupa aturan, bukan penilaian agent. Kalau bergantung pada model bahasa,
klaim yang sama bisa ditahan hari ini dan lolos besok. Yang boleh diserahkan ke agent cuma
kalimat permintaannya, dan itu terjadi di orkestrasi.
"""

from __future__ import annotations

from dataclasses import dataclass

# Ditetapkan dari pengukuran, bukan tebakan. Pada foto yang sudah diperkecil ke 1280 piksel
# sisi terpanjang, foto tajam dari bengkel maupun dataset bernilai 429 sampai 3123,
# sedangkan foto yang sama setelah diburamkan tipis bernilai 46 sampai 92.
AMBANG_KETAJAMAN = 100.0
AMBANG_KEYAKINAN = 0.50

BURAM = "buram"
TIDAK_YAKIN = "tidak_yakin"


@dataclass(frozen=True)
class FotoDinilai:
    """Satu foto beserta dua angka yang menentukan layak tidaknya dia dibaca."""

    urutan: int
    keyakinan_kendaraan: float
    ketajaman: float


@dataclass(frozen=True)
class FotoBermasalah:
    urutan: int
    sebab: str
    permintaan: str
    alasan: str

    @property
    def nomor(self) -> int:
        """Nomor foto seperti yang dilihat surveyor, dihitung mulai dari satu."""
        return self.urutan + 1


def periksa(
    foto: list[FotoDinilai],
    ambang_ketajaman: float = AMBANG_KETAJAMAN,
    ambang_keyakinan: float = AMBANG_KEYAKINAN,
) -> list[FotoBermasalah]:
    """Kembalikan foto yang perlu diulang. Daftar kosong berarti semuanya layak.

    Foto buram diperiksa lebih dulu karena itu sebab yang lebih mendasar: kalau fotonya
    buram, keyakinan model yang rendah cuma akibatnya, dan menyebut dua sebab sekaligus
    untuk satu foto cuma membingungkan yang harus memotretnya ulang.
    """
    hasil = []
    for f in foto:
        if f.ketajaman < ambang_ketajaman:
            hasil.append(
                FotoBermasalah(
                    urutan=f.urutan,
                    sebab=BURAM,
                    permintaan=f"Foto nomor {f.urutan + 1} buram/blur. Silahkan upload ulang",
                    alasan="",
                )
            )
        elif f.keyakinan_kendaraan < ambang_keyakinan:
            hasil.append(
                FotoBermasalah(
                    urutan=f.urutan,
                    sebab=TIDAK_YAKIN,
                    permintaan=(
                        f"Ulangi foto nomor {f.urutan + 1} dari jarak sekitar 2 meter, "
                        "seluruh badan mobil masuk bingkai"
                    ),
                    alasan=(
                        f"Di foto nomor {f.urutan + 1} sistem cuma "
                        f"{f.keyakinan_kendaraan:.0%} yakin melihat kendaraan, jadi "
                        "temuan dari foto ini belum layak dipakai"
                    ),
                )
            )
    return hasil


def ringkas_untuk_agent(masalah: list[FotoBermasalah], jumlah_foto: int) -> list[str]:
    """Baris pendek untuk prompt agent, supaya permintaannya bisa lebih spesifik.

    Agent tidak menentukan foto mana yang bermasalah, itu sudah diputuskan aturan. Yang
    ditambahkan agent cuma bagian mobil mana yang harus terlihat jelas di foto ulangnya.
    """
    if not masalah:
        return []
    label = {BURAM: "buram", TIDAK_YAKIN: "kendaraan tidak terbaca jelas"}
    return [
        f"Foto nomor {m.nomor} dari {jumlah_foto} {label[m.sebab]}, perlu difoto ulang"
        for m in masalah
    ]
