"""Penyedia LLM yang sungguhan, di balik antarmuka yang sama.

Groq, OpenRouter, dan Ollama sama-sama bicara protokol chat completions milik OpenAI, jadi
ketiganya cukup dilayani satu kelas yang bedanya hanya alamat, kunci, dan nama model.

Urutannya sengaja Groq dulu karena paling cepat mengeluarkan token, lalu OpenRouter, lalu
Ollama lokal yang tidak punya kuota sama sekali tapi paling lambat. Yang memicu pindah
penyedia hanya kegagalan kuota, ditangani di klien berjenjang.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.core.llm import (
    BatasKuota,
    Jawaban,
    KlienBerjenjang,
    KlienLLM,
    ModelTidakAda,
    Penggunaan,
)

# Alamat dan model bawaan tiap penyedia. Nama model bisa ditimpa lewat variabel lingkungan
# karena penyedia gratis kerap mengganti model yang tersedia tanpa pemberitahuan. Daftar
# model Groq yang masih hidup bisa dilihat lewat GET /openai/v1/models.
_GROQ = ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "MODEL_GROQ", "openai/gpt-oss-20b")
# Model gratis OpenRouter berganti-ganti dan sebagiannya diam-diam jadi berbayar, jadi
# periksa lagi nilai ini menjelang presentasi. Daftar terbarunya ada di
# https://openrouter.ai/api/v1/models, cari yang akhirannya ":free".
_OPENROUTER = (
    "https://openrouter.ai/api/v1",
    "OPENROUTER_API_KEY",
    "MODEL_OPENROUTER",
    "openai/gpt-oss-20b:free",
)


class KlienOpenAICompat:
    """Klien untuk penyedia mana pun yang memakai protokol chat completions OpenAI."""

    def __init__(self, nama: str, base_url: str, api_key: str, model: str, timeout: float = 30.0):
        from openai import OpenAI

        self.nama = nama
        self.model = model
        # Model bernalar menghabiskan jatah keluaran untuk berpikir dan menyisakan jawaban
        # kosong pada anggaran seketat ini, jadi nalarnya ditekan serendah mungkin.
        self._tambahan = {"reasoning_effort": "low"} if "gpt-oss" in model else {}
        self._klien = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=0)

    def jawab(self, prompt: str, max_tokens: int) -> Jawaban:
        from openai import APIStatusError, RateLimitError

        try:
            balasan = self._klien.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0,
                **self._tambahan,
            )
        except RateLimitError as e:
            raise BatasKuota(f"{self.nama} menolak karena kuota: {e}") from e
        except APIStatusError as e:
            # 402 muncul saat saldo habis dan 413 saat prompt melebihi batas penyedia.
            # Dua-duanya berarti penyedia ini tidak bisa dipakai sekarang, bukan promptnya salah.
            if e.status_code in (402, 413):
                raise BatasKuota(f"{self.nama} menolak: {e}") from e
            if e.status_code == 404:
                raise ModelTidakAda(f"{self.nama} tidak punya model {self.model}: {e}") from e
            raise

        pakai = balasan.usage
        return Jawaban(
            teks=balasan.choices[0].message.content or "",
            penggunaan=Penggunaan(
                provider=self.nama,
                model=self.model,
                token_masuk=pakai.prompt_tokens if pakai else 0,
                token_keluar=pakai.completion_tokens if pakai else 0,
            ),
        )


def _dari_lingkungan(nama: str, sumber: tuple[str, str, str, str]) -> KlienLLM | None:
    base_url, kunci_env, model_env, model_bawaan = sumber
    kunci = os.getenv(kunci_env)
    if not kunci:
        return None
    return KlienOpenAICompat(nama, base_url, kunci, os.getenv(model_env, model_bawaan))


def muat_env() -> None:
    """Baca berkas `.env` di folder backend kalau ada.

    Nilai yang sudah diatur di lingkungan tidak ditimpa, supaya pengaturan di server
    hosting tetap menang atas berkas yang kebetulan ikut terunggah.
    """
    berkas = Path(__file__).resolve().parents[3] / ".env"
    if not berkas.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(berkas, override=False)


def buat_klien() -> KlienLLM | None:
    """Susun klien berjenjang dari variabel lingkungan yang benar-benar terisi.

    Kembali None kalau tidak ada satu pun penyedia yang terpasang. Itu keadaan yang wajar:
    tanpa LLM, klaim tetap diproses penuh dan narasinya disusun kode, yang hilang hanya
    penilaian agent. Sistem tidak boleh berhenti cuma karena kunci API belum diisi.
    """
    muat_env()
    daftar: list[KlienLLM] = []

    for nama, sumber in (("groq", _GROQ), ("openrouter", _OPENROUTER)):
        klien = _dari_lingkungan(nama, sumber)
        if klien is not None:
            daftar.append(klien)

    alamat_ollama = os.getenv("OLLAMA_URL")
    if alamat_ollama:
        daftar.append(
            KlienOpenAICompat(
                "ollama",
                alamat_ollama.rstrip("/") + "/v1",
                # Ollama tidak memeriksa kunci, tapi pustaka klien menolak kunci kosong.
                "ollama",
                os.getenv("MODEL_OLLAMA", "qwen2.5:7b"),
                timeout=120.0,
            )
        )

    if not daftar:
        return None
    return KlienBerjenjang(daftar)
