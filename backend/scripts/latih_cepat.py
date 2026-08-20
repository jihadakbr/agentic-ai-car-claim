"""Latih model deteksi seadanya di komputer sendiri, untuk membuktikan rantai bobotnya jalan.

**Ini bukan untuk akurasi.** Modelnya sengaja kecil, epochnya sedikit, resolusinya rendah,
dan gambarnya cuma sebagian. Hasilnya jelek dan memang tidak dipakai menilai klaim sungguhan.

Yang dibuktikan: berkas bobot bisa dimuat `DetektorYolo`, nama kelasnya lolos `periksa_kelas`,
mask-nya sampai ke overlay, dan biayanya terhitung. Tanpa langkah ini, bobot hasil Kaggle
nanti jadi yang pertama kali melewati rantai itu, dan kalau ada yang salah, ketahuannya
setelah menunggu training berjam-jam.

Logika pengubahan anotasi di sini sengaja berdiri sendiri, tidak diambil dari notebook
training. Notebook harus tetap utuh sendiri supaya bisa dijalankan di Kaggle tanpa mengunggah
repo, jadi ada sedikit logika yang sama di dua tempat.

Jalankan dari folder backend:

    uv run --extra ml python scripts/latih_cepat.py
    uv run --extra ml python scripts/latih_cepat.py --gambar 300 --epoch 10
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from app.core.aturan import KELAS_BAGIAN, KELAS_KERUSAKAN

AKAR = Path(__file__).resolve().parent.parent
SUMBER = AKAR / "data" / "kaggle"
KERJA = AKAR / "data" / "_latih-cepat"
MODEL = AKAR / "models"

GAMBAR = {".jpg", ".jpeg", ".png"}


def kelas_di_meta(folder: Path) -> list[str]:
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    return sorted(k["title"] for k in meta["classes"])


def pilih_folder(harapan: list[str], peran: str) -> Path:
    """Pilih folder dataset dari isi kelasnya, bukan dari namanya.

    Nama folder dan nama berkas bisa berubah, sedangkan daftar kelas di meta.json tidak.
    Memilih dari nama berisiko melatih model bagian pada kelas kerusakan.
    """
    calon = sorted(p.parent for p in SUMBER.rglob("meta.json"))
    for folder in calon:
        if set(kelas_di_meta(folder)) == set(harapan):
            return folder
    rincian = "\n".join(f"  {p.name}: {len(kelas_di_meta(p))} kelas" for p in calon)
    raise SystemExit(f"Tidak ada folder yang kelasnya cocok untuk {peran}.\n{rincian}")


def cari_anotasi(gambar: Path) -> Path | None:
    """Anotasi ada di folder ann/ yang sejajar img/, namanya memuat akhiran gambar lengkap."""
    for kandidat in (
        gambar.parent.parent / "ann" / f"{gambar.name}.json",
        gambar.parent.parent / "ann" / f"{gambar.stem}.json",
    ):
        if kandidat.exists():
            return kandidat
    return None


def daftar_gambar(folder: Path) -> list[Path]:
    # Folder masks_human dan masks_machine berisi gambar mask dengan nama berkas yang sama
    # persis dengan fotonya, jadi tanpa saringan ini tiap foto ikut tiga kali.
    return sorted(
        p
        for p in folder.rglob("*")
        if p.suffix.lower() in GAMBAR and not p.parent.name.lower().startswith("mask")
    )


def tulis_label(anotasi: Path, kelas: list[str], tujuan: Path) -> bool:
    """Ubah poligon Supervisely jadi satu baris YOLO per objek. False kalau tidak ada objek."""
    data = json.loads(anotasi.read_text(encoding="utf-8"))
    lebar = data["size"]["width"]
    tinggi = data["size"]["height"]
    if not lebar or not tinggi:
        return False

    baris = []
    for objek in data.get("objects", []):
        nama = objek.get("classTitle")
        titik = objek.get("points", {}).get("exterior") or []
        if nama not in kelas or len(titik) < 3:
            continue
        angka = []
        for x, y in titik:
            angka.append(f"{min(max(x / lebar, 0.0), 1.0):.6f}")
            angka.append(f"{min(max(y / tinggi, 0.0), 1.0):.6f}")
        baris.append(f"{kelas.index(nama)} " + " ".join(angka))

    if not baris:
        return False
    tujuan.write_text("\n".join(baris), encoding="utf-8")
    return True


def susun(folder: Path, kelas: list[str], nama: str, jumlah: int, rng: random.Random) -> Path:
    """Susun folder dataset yang dimengerti Ultralytics, kembalikan jalur data.yaml."""
    dasar = KERJA / nama
    if dasar.exists():
        shutil.rmtree(dasar)

    semua = daftar_gambar(folder)
    rng.shuffle(semua)

    pasangan = []
    for g in semua:
        anotasi = cari_anotasi(g)
        if anotasi is not None:
            pasangan.append((g, anotasi))
        if len(pasangan) >= jumlah:
            break

    if not pasangan:
        raise SystemExit(f"Tidak ada gambar beranotasi di {folder}")

    # Sedikit sekali gambar, jadi pembagiannya 80:20 dan validasinya memang tidak berarti.
    batas = max(1, int(len(pasangan) * 0.8))
    bagian = {"train": pasangan[:batas], "val": pasangan[batas:] or pasangan[:1]}

    for bagi, isi in bagian.items():
        (dasar / "images" / bagi).mkdir(parents=True, exist_ok=True)
        (dasar / "labels" / bagi).mkdir(parents=True, exist_ok=True)
        for g, anotasi in isi:
            label = dasar / "labels" / bagi / f"{g.stem}.txt"
            if not tulis_label(anotasi, kelas, label):
                continue
            shutil.copy(g, dasar / "images" / bagi / g.name)

    yaml = dasar / "data.yaml"
    isi_yaml = [f"path: {dasar.as_posix()}", "train: images/train", "val: images/val", "names:"]
    isi_yaml += [f"  {i}: {k}" for i, k in enumerate(kelas)]
    yaml.write_text("\n".join(isi_yaml), encoding="utf-8")

    print(f"{nama}: {len(bagian['train'])} latih, {len(bagian['val'])} validasi, "
          f"{len(kelas)} kelas, dari {folder.name}")
    return yaml


def latih(yaml: Path, nama: str, epoch: int, ukuran: int) -> None:
    from ultralytics import YOLO

    model = YOLO("yolo11n-seg.pt")
    model.train(
        data=str(yaml),
        epochs=epoch,
        imgsz=ukuran,
        batch=8,
        workers=0,
        project=str(KERJA / "hasil"),
        name=nama,
        exist_ok=True,
        verbose=False,
        plots=False,
        val=False,
    )
    MODEL.mkdir(parents=True, exist_ok=True)
    shutil.copy(KERJA / "hasil" / nama / "weights" / "best.pt", MODEL / f"{nama}.pt")
    print(f"{nama}.pt tersimpan di {MODEL}")


def main() -> int:
    p = argparse.ArgumentParser(description="Latihan pendek untuk membuktikan rantai bobot")
    p.add_argument("--gambar", type=int, default=150, help="jumlah gambar per model")
    p.add_argument("--epoch", type=int, default=5)
    p.add_argument("--ukuran", type=int, default=320, help="resolusi gambar saat latihan")
    p.add_argument("--seed", type=int, default=2026)
    args = p.parse_args()

    if not SUMBER.exists():
        print(f"Dataset tidak ada di {SUMBER}", file=sys.stderr)
        return 1

    rng = random.Random(args.seed)
    folder_part = pilih_folder(KELAS_BAGIAN, "bagian mobil")
    folder_damage = pilih_folder(KELAS_KERUSAKAN, "kerusakan")

    yaml_part = susun(folder_part, list(KELAS_BAGIAN), "part", args.gambar, rng)
    yaml_damage = susun(folder_damage, list(KELAS_KERUSAKAN), "damage", args.gambar, rng)

    latih(yaml_part, "part", args.epoch, args.ukuran)
    latih(yaml_damage, "damage", args.epoch, args.ukuran)

    print("\nSelesai. Nyalakan ulang backend, lalu pastikan bannernya menyebut DetektorYolo.")
    print("Modelnya sengaja jelek. Timpa dengan bobot hasil Kaggle kalau sudah jadi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
