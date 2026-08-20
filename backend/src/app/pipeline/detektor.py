"""Antarmuka model deteksi, beserta dua penerapannya.

Dipisah jadi antarmuka karena tiga alasan:

- Sisa pipeline bisa dibangun dan diuji sebelum modelnya selesai dilatih.
- Mengganti model tidak menyentuh cost engine, cek validitas, maupun agent. Kalau nanti
  lisensi model yang dipakai jadi masalah, penggantinya cukup satu berkas.
- Uji otomatis bisa jalan tanpa mengunduh bobot model ratusan megabita.

`DetektorContoh` menghasilkan mask buatan yang bentuknya masuk akal, dipakai untuk menguji
sambungan antar bagian. `DetektorYolo` yang benar-benar menjalankan model, dan sengaja
memuat pustaka beratnya saat dipanggil, bukan saat modul ini diimpor.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

from app.core.aturan import GABUNG_KERUSAKAN, KELAS_BAGIAN
from app.pipeline.overlay import MaskDeteksi

# Kelas kendaraan pada model deteksi objek umum, dipakai gerbang "fotonya benar mobil".
KELAS_KENDARAAN = {"car", "truck", "bus", "motorcycle"}

# Inferensi selalu di prosesor, tidak pernah di GPU. Terbukti di Hugging Face ZeroGPU:
# bobot dikemas ke jalur GPU saat penyalaan, tapi inferensinya berjalan di thread latar yang
# tidak pernah mendapat alokasi GPU sungguhan, sehingga model mengembalikan nol mask tanpa
# melempar galat sama sekali. Kegagalan diam seperti itu jauh lebih mahal daripada selisih
# kecepatannya: model ini kecil, dan satu foto terukur 0.37 detik di prosesor, jadi klaim
# empat foto selesai sekitar 1.5 detik.
PERANGKAT = "cpu"


def _pinjam_gpu(fungsi):
    """Tandai fungsi ini sebagai fungsi ber-GPU, meski isinya berjalan di prosesor.

    Bukan demi kecepatan, tapi demi bisa menyala. Paket gratis Hugging Face cuma menyediakan
    hardware ZeroGPU untuk Gradio Space, dan ZeroGPU menolak menyala dengan pesan "No
    @spaces.GPU function detected during startup" kalau tidak ada satu pun fungsi bertanda
    ini. CPU basic terkunci di balik langganan berbayar.

    Di luar ZeroGPU pustakanya tidak ada dan fungsinya dikembalikan apa adanya, sehingga uji
    di laptop maupun pemasangan di server internal tidak butuh pustaka khusus Hugging Face.
    """
    try:
        import spaces
    except ImportError:
        return fungsi
    return spaces.GPU(fungsi)


@dataclass
class HasilDeteksi:
    part: list[MaskDeteksi]
    damage: list[MaskDeteksi]
    confidence_kendaraan: float


@_pinjam_gpu
def _deteksi_berurutan(detektor, gambar: Sequence[Image.Image]) -> list[HasilDeteksi]:
    """Jalankan model atas seluruh foto satu klaim.

    Dipisah jadi fungsi sendiri supaya seluruh foto melewati satu pintu, sehingga perangkat
    dan urutan pemanggilannya tidak tersebar di banyak tempat. Fungsi inilah yang ditandai
    ber-GPU, meski isinya memakai prosesor.
    """
    return [detektor.deteksi(g) for g in gambar]


class Detektor(Protocol):
    def deteksi(self, gambar: Image.Image) -> HasilDeteksi: ...

    def deteksi_banyak(self, gambar: Sequence[Image.Image]) -> list[HasilDeteksi]: ...


def _benih(gambar: Image.Image) -> int:
    """Benih acak yang diturunkan dari isi gambar.

    Dengan begitu foto yang sama selalu menghasilkan deteksi contoh yang sama, sehingga
    demo dan uji bisa diulang persis. Deteksi contoh yang berubah tiap dijalankan akan
    membuat uji sambungan antar bagian jadi tidak berarti.
    """
    kecil = gambar.convert("L").resize((32, 32))
    return int(hashlib.sha256(kecil.tobytes()).hexdigest()[:8], 16)


@dataclass
class DetektorContoh:
    """Detektor buatan untuk menguji sambungan, bukan untuk menilai klaim sungguhan.

    Mask-nya berupa kotak-kotak yang diletakkan seperti tata letak mobil tampak depan.
    Bentuknya sengaja sederhana supaya luas dan rasionya bisa dihitung tangan saat menguji.
    """

    kerusakan: str = "Dent"
    # Bagian tinggi muka mobil yang tertutup kerusakan, dihitung dari atas kap mesin. Nilai
    # kecil cuma menyentuh kap mesin, nilai mendekati satu menjalar sampai bumper sehingga
    # bisa dipakai mensimulasikan benturan depan berat yang berujung total loss.
    rasio_kerusakan: float = 0.45
    confidence_kendaraan: float = 0.94

    def deteksi(self, gambar: Image.Image) -> HasilDeteksi:
        lebar, tinggi = gambar.size
        rng = np.random.default_rng(_benih(gambar))

        def kotak(x0f, y0f, x1f, y1f) -> np.ndarray:
            """Segi delapan di dalam kotak yang diminta, sudutnya dipangkas.

            Bukan persegi, supaya gambar demo tidak terlihat seperti keluaran bounding box
            padahal model sungguhannya menghasilkan mask. Pangkasannya kecil dan cuma di
            sudut, jadi bagian yang saling beririsan antar bentuk tidak berubah.
            """
            y0, y1 = int(tinggi * y0f), int(tinggi * y1f)
            x0, x1 = int(lebar * x0f), int(lebar * x1f)
            m = np.zeros((tinggi, lebar), dtype=bool)
            m[y0:y1, x0:x1] = True

            potong = max(1, int(min(y1 - y0, x1 - x0) * 0.08))
            for i in range(potong):
                sisa = potong - i
                m[y0 + i, x0:x0 + sisa] = False
                m[y0 + i, x1 - sisa:x1] = False
                m[y1 - 1 - i, x0:x0 + sisa] = False
                m[y1 - 1 - i, x1 - sisa:x1] = False
            return m

        part = [
            MaskDeteksi("Windshield", 0.90, kotak(0.28, 0.00, 0.72, 0.10)),
            MaskDeteksi("Hood", 0.93, kotak(0.25, 0.10, 0.75, 0.45)),
            MaskDeteksi("Fender", 0.86, kotak(0.12, 0.15, 0.28, 0.55)),
            MaskDeteksi("Fender", 0.86, kotak(0.72, 0.15, 0.88, 0.55)),
            MaskDeteksi("Front-bumper", 0.91, kotak(0.22, 0.60, 0.78, 0.85)),
            MaskDeteksi("Headlight", 0.88, kotak(0.25, 0.45, 0.38, 0.60)),
            MaskDeteksi("Headlight", 0.87, kotak(0.62, 0.45, 0.75, 0.60)),
            MaskDeteksi("Grille", 0.85, kotak(0.40, 0.47, 0.60, 0.60)),
            MaskDeteksi("License-plate", 0.82, kotak(0.45, 0.68, 0.55, 0.76)),
        ]

        # Muka mobil membentang dari atas kap mesin sampai bawah bumper. Kerusakan menjalar
        # dari atas ke bawah sebanding rasionya, jadi bagian yang ikut kena bertambah
        # seiring parahnya benturan.
        atas, bawah = 0.10, 0.85
        tinggi_rusak = atas + (bawah - atas) * self.rasio_kerusakan
        damage = [
            MaskDeteksi(
                self.kerusakan,
                float(0.85 + rng.random() * 0.1),
                kotak(0.22, atas, 0.78, tinggi_rusak),
            )
        ]

        # Benturan yang meremukkan hampir seluruh muka mobil ikut memecahkan kaca depan.
        if self.rasio_kerusakan >= 0.9:
            damage.append(MaskDeteksi("Broken part", 0.89, kotak(0.28, 0.00, 0.72, 0.10)))

        return HasilDeteksi(part, damage, self.confidence_kendaraan)

    def deteksi_banyak(self, gambar: Sequence[Image.Image]) -> list[HasilDeteksi]:
        return [self.deteksi(g) for g in gambar]


class KelasModelTidakCocok(RuntimeError):
    """Bobot yang dimuat mengenali kelas yang bukan kelas project ini."""


def periksa_kelas(
    nama_model: dict[int, str], diharapkan: Sequence[str], peran: str, jalur: Path
) -> None:
    """Pastikan bobotnya mengenali kelas yang sama dengan aturan biaya.

    Berhenti di sini, bukan diteruskan dengan peringatan. Model yang kelasnya meleset tidak
    membuat pipeline gagal, dia membuatnya menghasilkan harga yang salah tanpa ada yang tahu.
    Kedua bobot dilatih di sesi yang sama dan namanya cuma beda satu kata, jadi tertukar saat
    disalin adalah kekeliruan yang benar-benar mungkin terjadi.
    """
    punya = set(nama_model.values())
    kurang = sorted(set(diharapkan) - punya)
    lebih = sorted(punya - set(diharapkan))
    if not kurang and not lebih:
        return
    raise KelasModelTidakCocok(
        f"Bobot {peran} di {jalur} mengenali kelas yang tidak cocok. "
        f"Tidak ada di bobot: {kurang or 'tidak ada'}. "
        f"Ada di bobot tapi bukan kelas {peran}: {lebih or 'tidak ada'}."
    )


# Kontur dari model bisa memuat ratusan titik. Diringkas supaya jawaban API tidak
# membengkak, tanpa mengubah bentuk yang terlihat di layar.
TITIK_POLIGON_MAKS = 120


def ringkas_poligon(titik, ukuran: tuple[int, int]) -> list[list[float]]:
    """Kontur mask, dinormalkan ke 0 sampai 1 supaya tidak terikat ukuran foto."""
    if titik is None or len(titik) < 3:
        return []
    lebar, tinggi = ukuran
    langkah = max(1, len(titik) // TITIK_POLIGON_MAKS)
    return [
        [round(float(x) / lebar, 4), round(float(y) / tinggi, 4)]
        for x, y in titik[::langkah]
    ]


def ukuran_latih(model, bawaan: int = 640) -> int:
    """Ukuran gambar saat bobot ini dilatih, dibaca dari bobotnya sendiri.

    Deteksi harus jalan di ukuran yang sama dengan saat latihan, dan kedua model di sini
    tidak dilatih di ukuran yang sama. Membacanya dari bobot, bukan dari konfigurasi
    terpisah, membuat keduanya tidak bisa melenceng saat bobotnya diganti.
    """
    args = getattr(getattr(model, "model", None), "args", None) or {}
    nilai = args.get("imgsz", bawaan)
    return int(nilai) if isinstance(nilai, (int, float)) else bawaan


class DetektorYolo:
    """Menjalankan dua model segmentasi sungguhan.

    Bobot dimuat sekali saat objek ini dibuat, bukan tiap kali deteksi dipanggil. Di
    lingkungan yang GPU-nya dialokasikan sesaat, waktu memuat model ikut terhitung sebagai
    pemakaian, jadi memuatnya berulang membuang kuota.
    """

    def __init__(
        self,
        model_part: Path,
        model_damage: Path,
        ambang_part: float = 0.35,
        # Disetel dari pengukuran, bukan disamakan dengan bagian mobil. Sasarannya IoU piksel
        # area rusak, karena itu yang dipakai mesin biaya. Menaikkannya menukar cakupan
        # dengan presisi, dan di atas nilai ini kerusakan yang benar mulai ikut terbuang.
        ambang_damage: float = 0.10,
    ):
        from ultralytics import YOLO  # diimpor di sini supaya pustaka berat tidak selalu dimuat

        self.part = YOLO(str(model_part))
        self.damage = YOLO(str(model_damage))
        self.ambang_part = ambang_part
        self.ambang_damage = ambang_damage

        self.imgsz_part = ukuran_latih(self.part)
        self.imgsz_damage = ukuran_latih(self.damage)

        periksa_kelas(self.part.names, KELAS_BAGIAN, "bagian mobil", model_part)
        # Dicocokkan ke kunci peta penggabungan, bukan ke KELAS_KERUSAKAN, karena bobotnya
        # mengeluarkan nama sebelum digabung.
        periksa_kelas(self.damage.names, list(GABUNG_KERUSAKAN), "kerusakan", model_damage)

    @staticmethod
    def _ambil_mask(
        hasil, ambang: float, ukuran: tuple[int, int], gabung: dict[str, str] | None = None
    ) -> list[MaskDeteksi]:
        keluaran: list[MaskDeteksi] = []
        if not hasil or hasil[0].masks is None:
            return keluaran

        r = hasil[0]
        nama = r.names
        # `masks.xy` adalah kontur tiap mask dalam koordinat foto asli. Diambil sekalian di
        # sini supaya layar yang menggambar overlaynya sendiri tidak perlu menelusuri tepi
        # dari petak boolean.
        tepi = list(getattr(r.masks, "xy", []) or [])
        for i, (mask, kotak) in enumerate(zip(r.masks.data, r.boxes, strict=False)):
            confidence = float(kotak.conf)
            if confidence < ambang:
                continue
            arr = mask.cpu().numpy().astype(bool)
            if arr.shape != (ukuran[1], ukuran[0]):
                gambar = Image.fromarray(arr.astype("uint8") * 255).resize(ukuran, Image.NEAREST)
                arr = np.asarray(gambar) > 127
            kelas = nama[int(kotak.cls)]
            keluaran.append(
                MaskDeteksi(
                    gabung.get(kelas, kelas) if gabung else kelas,
                    confidence,
                    arr,
                    ringkas_poligon(tepi[i], ukuran) if i < len(tepi) else [],
                )
            )
        return keluaran

    def deteksi(self, gambar: Image.Image) -> HasilDeteksi:
        ukuran = gambar.size
        hasil_part = self.part.predict(
            gambar, imgsz=self.imgsz_part, device=PERANGKAT, verbose=False
        )
        hasil_damage = self.damage.predict(
            gambar, imgsz=self.imgsz_damage, device=PERANGKAT, verbose=False
        )

        part = self._ambil_mask(hasil_part, self.ambang_part, ukuran)
        damage = self._ambil_mask(hasil_damage, self.ambang_damage, ukuran, GABUNG_KERUSAKAN)

        # Model bagian mobil hanya dilatih pada foto mobil, jadi keyakinan tertingginya
        # dipakai sebagai penanda "ada kendaraan di foto ini". Foto tanpa mobil tidak akan
        # menghasilkan mask bagian dengan keyakinan tinggi.
        confidence_kendaraan = max((p.confidence for p in part), default=0.0)
        return HasilDeteksi(part, damage, confidence_kendaraan)

    def deteksi_banyak(self, gambar: Sequence[Image.Image]) -> list[HasilDeteksi]:
        return _deteksi_berurutan(self, gambar)
