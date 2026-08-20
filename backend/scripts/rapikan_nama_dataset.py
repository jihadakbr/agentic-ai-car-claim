"""Samakan nama berkas dataset dengan isi foldernya.

Penerbit dataset memberi nama semua berkas "Car damages NNN", termasuk berkas di folder
bagian mobil. Foto yang sama muncul di dua folder dengan nama sama persis, dan saat membuka
salah satunya tidak ada petunjuk sedang melihat yang mana.

Yang diganti cuma folder bagian mobil, karena folder kerusakan namanya memang sudah benar.
Foldernya dikenali dari daftar kelas di meta.json, bukan dari namanya, supaya skrip ini tetap
benar meski foldernya pernah dinamai terbalik.

    uv run python scripts/rapikan_nama_dataset.py --periksa
    uv run python scripts/rapikan_nama_dataset.py
    uv run python scripts/rapikan_nama_dataset.py --kembalikan
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from app.core.aturan import KELAS_BAGIAN

SUMBER = Path(__file__).resolve().parent.parent / "data" / "kaggle"

AWALAN_LAMA = "Car damages "
AWALAN_BARU = "Car parts "

# Keempatnya memakai nama berkas yang sama persis, jadi harus diganti bersamaan. Mengganti
# img/ saja membuat anotasinya tidak lagi ketemu.
SUBFOLDER = ("img", "ann", "masks_human", "masks_machine")


class TidakBisaDilanjutkan(SystemExit):
    pass


def kelas_di_meta(folder: Path) -> set[str]:
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    return {k["title"] for k in meta["classes"]}


def folder_bagian() -> Path:
    """Cari folder dataset yang isinya kelas bagian mobil."""
    calon = sorted(p.parent for p in SUMBER.rglob("meta.json"))
    for folder in calon:
        if kelas_di_meta(folder) == set(KELAS_BAGIAN):
            return folder
    rincian = "\n".join(f"  {p.name}: {len(kelas_di_meta(p))} kelas" for p in calon)
    raise TidakBisaDilanjutkan(
        f"Tidak ada folder yang kelasnya cocok dengan kelas bagian mobil.\n{rincian}"
    )


def rencana(akar: Path, dari: str, ke: str) -> list[tuple[Path, Path]]:
    """Daftar penggantian nama yang akan dilakukan, urut supaya laporannya bisa dibaca."""
    hasil = []
    for sub in SUBFOLDER:
        folder = akar / sub
        if not folder.is_dir():
            continue
        for berkas in sorted(folder.iterdir()):
            if berkas.is_file() and berkas.name.startswith(dari):
                hasil.append((berkas, berkas.with_name(ke + berkas.name[len(dari):])))
    return hasil


def periksa_tujuan(langkah: list[tuple[Path, Path]]) -> None:
    """Pastikan tidak ada tujuan yang sudah terpakai, sebelum satu berkas pun disentuh."""
    bentrok = [b.name for _, b in langkah if b.exists()]
    if bentrok:
        raise TidakBisaDilanjutkan(
            f"{len(bentrok)} nama tujuan sudah terpakai, tidak ada yang diganti. "
            f"Contoh: {', '.join(bentrok[:3])}"
        )


def jalankan(langkah: list[tuple[Path, Path]]) -> None:
    for lama, baru in langkah:
        lama.rename(baru)


def laporkan(akar: Path, langkah: list[tuple[Path, Path]]) -> None:
    per_sub: dict[str, int] = {}
    for lama, _ in langkah:
        per_sub[lama.parent.name] = per_sub.get(lama.parent.name, 0) + 1
    print(f"Folder bagian mobil: {akar.parent.name}")
    for sub in SUBFOLDER:
        print(f"  {sub:<16} {per_sub.get(sub, 0)} berkas")
    if langkah:
        lama, baru = langkah[0]
        print(f"Contoh: {lama.name}  ->  {baru.name}")


def main() -> int:
    p = argparse.ArgumentParser(description="Samakan nama berkas dataset dengan isi foldernya")
    p.add_argument("--periksa", action="store_true", help="laporkan rencananya tanpa mengubah")
    p.add_argument("--kembalikan", action="store_true", help="kembalikan ke nama semula")
    args = p.parse_args()

    if not SUMBER.exists():
        print(f"Dataset tidak ada di {SUMBER}", file=sys.stderr)
        return 1

    akar = folder_bagian() / "File1"
    dari, ke = (AWALAN_BARU, AWALAN_LAMA) if args.kembalikan else (AWALAN_LAMA, AWALAN_BARU)

    langkah = rencana(akar, dari, ke)
    laporkan(akar, langkah)

    if not langkah:
        print("Tidak ada yang perlu diganti.")
        return 0
    if args.periksa:
        print(f"\n{len(langkah)} berkas akan diganti namanya. Belum ada yang disentuh.")
        return 0

    periksa_tujuan(langkah)
    jalankan(langkah)
    print(f"\n{len(langkah)} berkas selesai diganti namanya.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
