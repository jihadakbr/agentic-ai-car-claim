"""Siapkan data galeri untuk halaman Demo di frontend.

Halaman Demo tidak menjalankan model sama sekali. Yang disimpan di sini adalah bentuk
poligon tiap mask, bukan gambar overlay yang sudah jadi, supaya browser bisa mengatur
sendiri warna, tebal garis, dan lapisan mana yang tampil. Overlay yang dibakar di server
sudah jadi piksel, jadi lapisannya tidak bisa dimatikan lagi.

Jalankan dari folder backend:

    uv run python scripts/siapkan_galeri_demo.py
    uv run python scripts/siapkan_galeri_demo.py --nilai-minimal 0.7
    uv run python scripts/siapkan_galeri_demo.py --batas 20
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from app.core.aturan import GABUNG_KERUSAKAN
from app.pipeline.detektor import DetektorYolo

AKAR = Path(__file__).resolve().parent.parent
PERINGKAT = AKAR / "data/foto-klaim-n-stnk/hasil-inference/peringkat-lengkap-801-foto.json"
SKENARIO = AKAR / "data/foto-klaim-n-stnk"
TUJUAN = AKAR.parent / "frontend/public/demo"
SISI_MAKS = 1024

# Poligon dari Ultralytics bisa memuat ratusan titik per mask. Diringkas supaya galeri.json
# tidak membengkak, tanpa mengubah bentuk yang terlihat di layar.
TITIK_MAKS = 120


def nama_berkas(asal: Path) -> str:
    """Nama yang aman dipakai di URL. Nama aslinya memuat spasi dan huruf besar."""
    return re.sub(r"[^a-z0-9]+", "-", asal.stem.lower()).strip("-") + ".jpg"


def bentuk(hasil, ambang: float, lebar: int, tinggi: int, gabung=None) -> list[dict]:
    """Ubah keluaran Ultralytics jadi daftar poligon yang dinormalkan ke 0 sampai 1.

    Poligonnya diambil dari `masks.xy`, yaitu kontur asli tiap mask, bukan dihitung ulang
    dari petak boolean. Koordinatnya dinormalkan supaya tetap benar setelah fotonya
    dikecilkan.
    """
    if not hasil or hasil[0].masks is None:
        return []

    r = hasil[0]
    keluaran = []
    for titik, kotak in zip(r.masks.xy, r.boxes, strict=False):
        keyakinan = float(kotak.conf)
        if keyakinan < ambang or len(titik) < 3:
            continue
        langkah = max(1, len(titik) // TITIK_MAKS)
        kelas = r.names[int(kotak.cls)]
        keluaran.append({
            "kelas": gabung.get(kelas, kelas) if gabung else kelas,
            "keyakinan": round(keyakinan, 3),
            "titik": [[round(float(x) / lebar, 4), round(float(y) / tinggi, 4)]
                      for x, y in titik[::langkah]],
        })
    return keluaran


def foto_skenario() -> dict[str, str]:
    """Sidik jari foto yang sedang terpasang di folder skenario, supaya bisa ditandai."""
    peta = {}
    for f in sorted(SKENARIO.glob("*/kerusakan-*")):
        if f.parent.name.startswith(("hasil", "uji")):
            continue
        peta[hashlib.sha256(f.read_bytes()).hexdigest()] = f"{f.parent.name}/{f.name}"
    return peta


def main() -> int:
    p = argparse.ArgumentParser(description="Siapkan data galeri halaman Demo")
    p.add_argument("--nilai-minimal", type=float, default=0.8,
                   help="ambang nilai kebenaran deteksi, 0 sampai 1")
    p.add_argument("--batas", type=int, default=0, help="batasi jumlah foto, 0 berarti semua")
    args = p.parse_args()

    if not PERINGKAT.exists():
        print(f"Berkas peringkat tidak ada di {PERINGKAT}", file=sys.stderr)
        return 1

    peringkat = json.loads(PERINGKAT.read_text(encoding="utf-8"))
    for r in peringkat:
        r["nilai"] = r["iou"] * (1 - r["palsu"])
    dipilih = sorted((r for r in peringkat if r["nilai"] >= args.nilai_minimal),
                     key=lambda r: -r["nilai"])
    if args.batas:
        dipilih = dipilih[: args.batas]

    terpasang = foto_skenario()
    print(f"{len(dipilih)} foto lolos ambang {args.nilai_minimal}", flush=True)

    (TUJUAN / "foto").mkdir(parents=True, exist_ok=True)
    for f in (TUJUAN / "foto").glob("*.jpg"):
        f.unlink()

    d = DetektorYolo(AKAR / "models/part.pt", AKAR / "models/damage.pt")
    galeri = []

    for i, r in enumerate(dipilih, 1):
        asal = Path(r["berkas"])
        if not asal.is_absolute():
            asal = AKAR / asal
        if not asal.exists():
            continue

        foto = Image.open(asal).convert("RGB")
        lebar, tinggi = foto.size

        # Dipanggil langsung ke kedua model, bukan lewat `deteksi`, karena yang dibutuhkan
        # poligonnya dan `deteksi` cuma mengembalikan petak boolean.
        h_part = d.part.predict(foto, imgsz=d.imgsz_part, verbose=False)
        h_damage = d.damage.predict(foto, imgsz=d.imgsz_damage, verbose=False)

        kecil = foto.copy()
        kecil.thumbnail((SISI_MAKS, SISI_MAKS), Image.LANCZOS)
        nama = nama_berkas(asal)
        kecil.save(TUJUAN / "foto" / nama, "JPEG", quality=85)

        galeri.append({
            "berkas": nama,
            "asal": asal.relative_to(AKAR).as_posix(),
            "dipakai_di": terpasang.get(hashlib.sha256(asal.read_bytes()).hexdigest()),
            "lebar": kecil.width,
            "tinggi": kecil.height,
            "nilai": round(r["nilai"], 3),
            "iou": r["iou"],
            "salah_tandai": r["palsu"],
            "tertutup": r["tertutup"],
            "part": bentuk(h_part, d.ambang_part, lebar, tinggi),
            "damage": bentuk(h_damage, d.ambang_damage, lebar, tinggi, GABUNG_KERUSAKAN),
        })
        if i % 20 == 0:
            print(f"  {i}/{len(dipilih)}", flush=True)

    (TUJUAN / "galeri.json").write_text(
        json.dumps({"foto": galeri}, ensure_ascii=False), encoding="utf-8")

    ukuran = sum(f.stat().st_size for f in (TUJUAN / "foto").glob("*.jpg"))
    print(f"\n{len(galeri)} foto ditulis ke {TUJUAN}")
    print(f"gambar {ukuran / 1_048_576:.1f} MB, "
          f"galeri.json {(TUJUAN / 'galeri.json').stat().st_size / 1_048_576:.1f} MB")
    print(f"foto yang sedang dipakai di folder skenario: "
          f"{sum(1 for g in galeri if g['dipakai_di'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
