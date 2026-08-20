"""Lapisan pemanggil LLM beserta penjaga pemakaian token.

Kuota gratis Groq dan OpenRouter ketat, jadi menghemat token di sini bukan optimasi
tambahan tapi syarat supaya demonya bisa jalan. Aturan yang dipegang, dari yang paling
besar dampaknya:

1. **Gambar tidak pernah dikirim ke LLM.** Seluruh pekerjaan penglihatan dikerjakan model
   deteksi sendiri, dan LLM cuma menerima ringkasan berbentuk teks pendek. Ini sekaligus
   alasan sistem tetap bisa jalan di server internal yang tanpa GPU.
2. **Angka dan tabel disusun kode, bukan LLM.** LLM cuma menulis narasi.
3. **Ada penjaga anggaran.** Prompt yang kelewat panjang ditolak sebelum dikirim, bukan
   setelah kuota habis.
4. **Ada urutan cadangan.** Kalau satu penyedia kena batas, pindah ke berikutnya.

Pemanggilnya tidak pernah tahu penyedia mana yang dipakai. Itu yang membuat pindah dari
Groq ke Ollama di server internal cuma soal mengubah konfigurasi.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol


class LlmError(Exception):
    """Kegagalan umum saat memanggil LLM."""


class PenyediaTidakTersedia(LlmError):
    """Penyedia ini tidak bisa melayani sekarang, tapi penyedia lain mungkin bisa.

    Dipisah dari kegagalan lain karena inilah satu-satunya kondisi yang layak dijawab
    dengan pindah ke penyedia cadangan. Prompt yang salah bentuk akan gagal di semua
    penyedia, jadi mencobanya berulang cuma membuang waktu.
    """


class BatasKuota(PenyediaTidakTersedia):
    """Penyedia menolak karena kuota atau batas kecepatan."""


class ModelTidakAda(PenyediaTidakTersedia):
    """Nama model tidak dikenal penyedia ini.

    Penyedia gratis menghapus model tanpa pemberitahuan, jadi ini kejadian biasa dan
    harus berujung pindah penyedia, bukan menggagalkan klaim.
    """


class AnggaranTerlampaui(LlmError):
    """Perkiraan token melebihi jatah satu klaim."""


@dataclass
class Penggunaan:
    provider: str
    model: str
    token_masuk: int
    token_keluar: int

    @property
    def total(self) -> int:
        return self.token_masuk + self.token_keluar


@dataclass
class Jawaban:
    teks: str
    penggunaan: Penggunaan


class KlienLLM(Protocol):
    """Antarmuka minimum yang harus dipenuhi tiap penyedia."""

    nama: str

    def jawab(self, prompt: str, max_tokens: int) -> Jawaban: ...


# Perkiraan kasar jumlah token dari panjang teks. Bahasa Indonesia terpecah lebih boros
# dibanding Inggris, jadi angkanya sengaja dibuat pesimistis: lebih baik penjaga anggaran
# menolak prompt yang sebenarnya masih muat daripada kuota harian habis di tengah demo.
KARAKTER_PER_TOKEN = 3.0


def perkiraan_token(teks: str) -> int:
    return max(1, int(len(teks) / KARAKTER_PER_TOKEN))


@dataclass
class PenjagaAnggaran:
    """Batasi pemakaian token per klaim.

    Batas dihitung per klaim, bukan per panggilan, karena yang menentukan berapa klaim bisa
    diproses hari ini adalah totalnya. Satu panggilan yang boros tetap boleh lewat asal
    total klaimnya masih di bawah jatah.
    """

    batas_token_per_klaim: int = 6000
    terpakai: int = 0
    riwayat: list[Penggunaan] = field(default_factory=list)

    def sisa(self) -> int:
        return max(0, self.batas_token_per_klaim - self.terpakai)

    def periksa(self, prompt: str, max_tokens: int) -> None:
        perkiraan = perkiraan_token(prompt) + max_tokens
        if perkiraan > self.sisa():
            raise AnggaranTerlampaui(
                f"Perkiraan {perkiraan} token melebihi sisa jatah {self.sisa()} untuk klaim ini"
            )

    def catat(self, penggunaan: Penggunaan) -> None:
        self.terpakai += penggunaan.total
        self.riwayat.append(penggunaan)


class KlienBerjenjang:
    """Coba beberapa penyedia berurutan sampai ada yang berhasil.

    Cuma kegagalan di sisi penyedia yang memicu pindah. Prompt yang salah bentuk akan
    gagal di mana pun, jadi kalau itu penyebabnya, error-nya diteruskan apa adanya supaya
    ketahuan dan diperbaiki, bukan disamarkan jadi masalah penyedia.
    """

    def __init__(self, klien: list[KlienLLM]):
        if not klien:
            raise ValueError("Minimal satu klien LLM harus disediakan")
        self.klien = klien

    def jawab(self, prompt: str, max_tokens: int) -> Jawaban:
        kegagalan: list[str] = []
        for k in self.klien:
            try:
                return k.jawab(prompt, max_tokens)
            except PenyediaTidakTersedia as e:
                kegagalan.append(f"{k.nama}: {e}")
                continue
        raise PenyediaTidakTersedia("Tidak ada penyedia yang bisa dipakai. " + "; ".join(kegagalan))


def ambil_json(teks: str) -> dict[str, Any]:
    """Ambil objek JSON dari jawaban LLM.

    LLM sering membungkus JSON dengan kalimat pengantar atau pagar kode, meski sudah
    diminta menjawab JSON saja. Daripada berharap jawabannya selalu bersih, lebih aman
    mengambil objek pertama yang terlihat.
    """
    bersih = teks.strip()

    pagar = re.search(r"```(?:json)?\s*(.+?)```", bersih, re.DOTALL)
    if pagar:
        bersih = pagar.group(1).strip()

    try:
        hasil = json.loads(bersih)
    except json.JSONDecodeError:
        kurung = re.search(r"\{.*\}", bersih, re.DOTALL)
        if not kurung:
            raise LlmError(f"Jawaban LLM tidak memuat JSON: {teks[:200]}") from None
        try:
            hasil = json.loads(kurung.group(0))
        except json.JSONDecodeError as e:
            raise LlmError(f"JSON di jawaban LLM rusak: {e}") from e

    if not isinstance(hasil, dict):
        raise LlmError(f"JSON di jawaban LLM bukan objek, melainkan {type(hasil).__name__}")
    return hasil


def daftar_teks(nilai: Any) -> list[str]:
    """Paksa nilai jadi daftar teks.

    LLM kadang mengembalikan `null` untuk daftar kosong, atau satu teks untuk daftar berisi
    satu hal. Memaksa bentuknya di sini lebih andal daripada berharap LLM selalu patuh, dan
    jauh lebih baik daripada seluruh proses berhenti gara-gara bentuk yang meleset sedikit.
    """
    if nilai is None:
        return []
    if isinstance(nilai, str):
        return [nilai.strip()] if nilai.strip() else []
    if isinstance(nilai, list):
        return [str(v).strip() for v in nilai if str(v).strip()]
    return [str(nilai).strip()]


def teks_bersih(nilai: Any, bawaan: str = "") -> str:
    if nilai is None:
        return bawaan
    hasil = str(nilai).strip()
    return hasil or bawaan
