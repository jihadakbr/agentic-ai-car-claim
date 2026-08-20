"""Uji lapisan HTTP dari sisi pemanggil.

Memakai detektor contoh dan database SQLite sementara, jadi uji ini jalan tanpa bobot model
dan tanpa layanan luar apa pun. Yang diuji: bentuk jawaban yang diterima frontend, kode
kesalahan untuk masukan yang salah, dan apakah surat resmi cuma terbit setelah ada keputusan
manusia.
"""

import io
from contextlib import contextmanager

import pytest
from PIL import Image, ImageDraw

gradio = pytest.importorskip("gradio", reason="butuh dependensi opsional serve")
from fastapi.testclient import TestClient

from app.db import session as sesi_modul


def foto_bytes(warna: int = 120, ukuran=(800, 600)) -> bytes:
    """Foto uji bercorak, bukan bidang polos.

    Bidang polos tidak punya tepi sama sekali, sehingga ketajamannya nol dan gerbang
    kelayakan foto menganggapnya buram. Coraknya ditentukan `warna`, jadi nilai yang sama
    tetap menghasilkan berkas yang sama persis, dan pemeriksaan foto dipakai ulang tetap
    punya bahan yang benar-benar kembar.
    """
    img = Image.new("RGB", ukuran, (warna, warna, warna))
    gambar = ImageDraw.Draw(img)
    gelap = max(0, warna - 90)
    for i in range(0, ukuran[0], 24):
        gambar.line([(i, 0), (i, ukuran[1])], fill=(gelap, gelap, gelap), width=4)
    for j in range(0, ukuran[1], 24):
        gambar.line([(0, j), (ukuran[0], j)], fill=(gelap, gelap, gelap), width=4)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def foto_bercorak(geser: int, ukuran=(800, 600)) -> bytes:
    """Foto dengan corak, supaya sidik jarinya benar-benar berbeda.

    Gambar polos selalu menghasilkan sidik jari yang sama berapa pun warnanya, jadi dua
    klaim yang memakainya selalu dianggap memakai foto yang sama.
    """
    img = Image.new("RGB", ukuran, (210, 210, 210))
    x = geser * 37 % 400
    y = geser * 29 % 300
    ImageDraw.Draw(img).rectangle([x, y, x + 260, y + 180], fill=(30, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def berkas_foto(
    jumlah: int = 4, dengan_stnk: bool = True, pelengkap: int = 0, corak: int | None = None
):
    berkas = [
        (
            "foto",
            (
                f"f{i}.jpg",
                foto_bytes(100 + i * 20) if corak is None else foto_bercorak(corak * 9 + i),
                "image/jpeg",
            ),
        )
        for i in range(jumlah)
    ]
    if dengan_stnk:
        berkas.append(("foto_stnk", ("stnk.jpg", foto_bytes(200), "image/jpeg")))
    berkas += [
        ("foto_pelengkap", (f"p{i}.jpg", foto_bytes(30 + i * 5), "image/jpeg"))
        for i in range(pelengkap)
    ]
    return berkas


def kirim_klaim(klien, nomor_polis: str = "POL-2024-0037", **kwargs) -> dict:
    """Kirim klaim lalu kembalikan rinciannya yang sudah lengkap.

    Pengiriman sekarang menjawab sebelum pipeline jalan, jadi rinciannya diambil terpisah.
    TestClient menuntaskan tugas latarnya sebelum permintaan dianggap selesai, jadi saat
    baris ini jalan hasilnya sudah pasti ada.
    """
    r = klien.post("/api/klaim", params={"nomor_polis": nomor_polis},
                   files=berkas_foto(**kwargs))
    assert r.status_code == 202, r.text
    return klien.get(f"/api/klaim/{r.json()['id']}").json()


FIELD_STNK = ("merk", "tipe", "tahun", "nomor_polisi", "nomor_rangka", "nama_pemilik")


def lengkapi_review(klien, klaim: dict) -> dict:
    """Nilai seluruh temuan dan field STNK sebagai benar, lalu kembalikan detail terbarunya.

    Klaim tidak boleh diputuskan sebelum keduanya dinilai, jadi uji yang fokusnya pada
    keputusan memakai penolong ini supaya tidak mengulang langkah yang sama di tiap berkas.
    """
    temuan = [t for f in klaim.get("foto", []) for t in f["temuan"]]
    if temuan:
        r = klien.post(
            f"/api/klaim/{klaim['id']}/review-deteksi",
            json={"penilaian": [
                {"temuan_id": t["id"], "benar": True, "alasan": None} for t in temuan
            ]},
        )
        assert r.status_code == 200, r.text

    stnk = klaim.get("stnk") or {}
    field = [f for f in FIELD_STNK if stnk.get(f)]
    if field:
        r = klien.post(
            f"/api/klaim/{klaim['id']}/review-stnk",
            json={"penilaian": [
                {"field": f, "benar": True, "nilai_benar": None} for f in field
            ]},
        )
        assert r.status_code == 200, r.text

    return klien.get(f"/api/klaim/{klaim['id']}").json()


class PembacaPalsu:
    """Pembaca STNK tiruan, mengembalikan kotak teks tetap tanpa memuat model OCR.

    Nilainya sengaja dibuat cocok dengan polis di data awal supaya pemeriksaan C5 dan C6
    lolos, sehingga uji lain bisa fokus ke hal yang sedang diujinya.
    """

    def __init__(self, **timpa: str):
        self.field = {
            "No. Registrasi": "B 1234 XYZ",
            "Nama Pemilik": "BUDI SANTOSO",
            "Merk": "TOYOTA",
            "Type": "AVANZA 1.3 G",
            "Tahun Pembuatan": "2013",
            "No. Rangka": "MHKM1BA3JDK012345",
            "No. Mesin": "1NRF012345",
            **timpa,
        }

    def baca(self, gambar):
        from app.pipeline.stnk_ocr import KotakTeks

        kotak = []
        for i, (label, nilai) in enumerate(self.field.items()):
            y = 100.0 + i * 58
            kotak.append(KotakTeks(teks=label, x=40.0, y=y))
            kotak.append(KotakTeks(teks=nilai, x=185.0, y=y))
        return kotak


class KlienLLMPalsu:
    """Klien LLM tiruan dengan jawaban yang sudah ditentukan, tidak menyentuh kuota."""

    def __init__(self, *jawaban: str):
        self.antrean = list(jawaban)
        self.prompt: list[str] = []

    def jawab(self, prompt, max_tokens):
        from app.core.llm import Jawaban, Penggunaan

        self.prompt.append(prompt)
        teks = self.antrean.pop(0) if self.antrean else "{}"
        return Jawaban(
            teks=teks,
            penggunaan=Penggunaan(provider="palsu", model="palsu", token_masuk=10, token_keluar=5),
        )


@contextmanager
def server_uji(tmp_path, monkeypatch, nama_db="uji.db", masuk_sebagai="admin", **timpa):
    """Server dengan database dan folder foto sendiri, bersih tiap uji.

    Sudah masuk sebagai admin secara bawaan, karena hampir semua uji di sini menguji alur
    klaim, bukan pembagian peran. Uji peran menyebut `masuk_sebagai` sendiri.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / nama_db}")
    monkeypatch.setenv("FOLDER_FOTO", str(tmp_path / "foto"))

    # Kunci dikosongkan supaya uji tidak pernah memanggil layanan sungguhan. Tanpa ini,
    # berkas `.env` terbaca dan setiap kali uji dijalankan kuota ikut terpakai.
    for kunci in (
        "GROQ_API_KEY", "OPENROUTER_API_KEY", "OLLAMA_URL",
        "SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_BUCKET",
    ):
        monkeypatch.setenv(kunci, "")

    # Modul koneksi menyimpan engine-nya, jadi harus dilepas supaya alamat baru terbaca.
    monkeypatch.setattr(sesi_modul, "_engine", None)
    monkeypatch.setattr(sesi_modul, "_Session", None)

    from app.agents.pencari_web import PencariMati
    from app.api.server import buat_server
    from app.db.seed import isi_semua
    from app.pipeline.detektor import DetektorContoh

    monkeypatch.setattr("app.api.server.FOLDER_FOTO", tmp_path / "foto", raising=False)

    # Pencari dimatikan secara bawaan. Uji yang hasilnya bergantung mesin pencari akan
    # gagal di waktu acak dan berhenti dipercaya, jadi tidak boleh ada satu pun uji yang
    # diam-diam menyentuh internet.
    pengaturan = {
        "detektor": DetektorContoh(),
        "pembaca": PembacaPalsu(),
        "pencari": PencariMati(),
        **timpa,
    }
    app = buat_server(**pengaturan)
    with sesi_modul.sesi() as s:
        isi_semua(s)

    with TestClient(app) as c:
        if masuk_sebagai:
            r = c.post(
                "/api/login", json={"username": masuk_sebagai, "password": SANDI}
            )
            assert r.status_code == 200, r.text
            c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c


SANDI = "Kijang@2026"


@pytest.fixture
def klien(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch) as c:
        yield c


def test_kesehatan_melaporkan_kesiapan(klien):
    r = klien.get("/api/kesehatan")
    assert r.status_code == 200
    data = r.json()
    assert data["siap"] is True
    assert data["detektor"] == "DetektorContoh"


def test_lihat_polis_yang_ada(klien):
    r = klien.get("/api/polis/POL-2024-0037")
    assert r.status_code == 200
    assert r.json()["pemegang"] == "BUDI SANTOSO"
    assert r.json()["kendaraan"] == "Toyota Avanza 1.3 G"


def test_polis_tidak_ada_balas_404(klien):
    assert klien.get("/api/polis/POL-TIDAK-ADA").status_code == 404


def test_pengiriman_dijawab_sebelum_pipeline_jalan(klien):
    """Surveyor masih di lokasi, jadi dia tidak boleh menunggu OCR dan deteksi selesai."""
    r = klien.post(
        "/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto()
    )
    assert r.status_code == 202, r.text
    data = r.json()

    assert data["nomor_klaim"].startswith("KLM-")
    assert data["status"] == "diproses"
    # Jawabannya sengaja tipis: tidak ada biaya, temuan, maupun hasil pemeriksaan.
    assert set(data) == {"id", "nomor_klaim", "status"}


def test_pipeline_latar_menghasilkan_hasil_lengkap(klien):
    data = kirim_klaim(klien)

    assert data["status"] == "siap_review"
    assert len(data["cek"]) == 7
    assert data["biaya"]["total_biaya"] != "0"
    assert data["baris_biaya"]
    assert data["stnk"]["merk"] == "TOYOTA"
    assert all(f["ada_overlay"] for f in data["foto"])


def test_harga_penawaran_terlihat_sebelum_adjuster_memutuskan(tmp_path, monkeypatch):
    """Adjuster tidak boleh menyetujui penawaran beli tanpa tahu lebih dulu angkanya."""
    from app.pipeline.detektor import DetektorContoh

    berat = DetektorContoh(kerusakan="Dent", rasio_kerusakan=0.95)
    with server_uji(tmp_path, monkeypatch, "salvage.db", detektor=berat) as c:
        kirim = kirim_klaim(c)

        assert kirim["biaya"]["rekomendasi"] == "total_loss"
        tawaran = kirim["biaya"]["harga_tawaran_salvage"]
        assert tawaran and tawaran != "0"

        lengkapi_review(c, kirim)
        hasil = c.post(
            f"/api/klaim/{kirim['id']}/keputusan",
            json={"keputusan": "setuju"},
        ).json()

    # Angka yang terbit harus sama persis dengan yang tadi dilihat, bukan hitungan ulang.
    assert hasil["surat"] == "penawaran_beli"
    assert hasil["harga_tawaran"] == tawaran


def test_klaim_perbaikan_tidak_punya_harga_penawaran(klien):
    kirim = kirim_klaim(klien)
    assert kirim["biaya"]["rekomendasi"] == "repair"
    assert kirim["biaya"]["harga_tawaran_salvage"] is None
    assert kirim["biaya"]["own_risk"] != "0"


def test_klaim_tanpa_foto_stnk_ditolak(klien):
    r = klien.post(
        "/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto(dengan_stnk=False)
    )
    assert r.status_code == 422


def test_nomor_rangka_berbeda_dari_polis_menggagalkan_klaim(tmp_path, monkeypatch):
    """Ini yang tidak mungkin ketahuan selama field STNK diisi dari data polis sendiri."""
    pembaca = PembacaPalsu(**{"No. Rangka": "MHKM1BA3JEK999999"})
    with server_uji(tmp_path, monkeypatch, "beda.db", pembaca=pembaca) as c:
        data = kirim_klaim(c)

    c6 = next(x for x in data["cek"] if x["kode"] == "C6")
    assert c6["lolos"] is False
    assert data["verdict_validitas"] == "invalid"


def test_narasi_tersimpan_dan_terbaca_lagi(klien):
    """Narasi ikut disimpan, kalau tidak layar adjuster kehilangannya saat halaman dibuka ulang."""
    kirim = kirim_klaim(klien)
    assert kirim["narasi"]

    ulang = klien.get(f"/api/klaim/{kirim['id']}").json()
    assert ulang["narasi"] == kirim["narasi"]


def test_klaim_tanpa_foto_kerusakan_ditolak(klien):
    r = klien.post(
        "/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto(0)
    )
    assert r.status_code == 400
    assert "foto kerusakan" in r.json()["detail"]


def test_foto_lebih_dari_batas_ditolak(klien):
    r = klien.post(
        "/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto(7)
    )
    assert r.status_code == 400
    assert "foto kerusakan" in r.json()["detail"]


def test_satu_foto_kerusakan_sudah_cukup(klien):
    """Satu foto diterima supaya satu klaim demo bisa benar-benar satu mobil."""
    klaim = kirim_klaim(klien, jumlah=1)

    assert len(klaim["foto"]) == 1
    assert klaim["biaya"] is not None
    assert klaim["status"] == "siap_review"


def test_format_berkas_salah_ditolak(klien):
    berkas = berkas_foto(3) + [("foto", ("catatan.txt", b"bukan gambar", "text/plain"))]
    r = klien.post("/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas)
    assert r.status_code == 400
    assert "tidak didukung" in r.json()["detail"]


def test_klaim_dengan_polis_tak_dikenal_ditolak(klien):
    r = klien.post("/api/klaim", params={"nomor_polis": "POL-XXX"}, files=berkas_foto())
    assert r.status_code == 404


def test_daftar_klaim_terisi_setelah_pengiriman(klien):
    klien.post("/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto())
    r = klien.get("/api/klaim")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["pemegang_polis"] == "BUDI SANTOSO"


def test_foto_dipakai_ulang_terdeteksi_di_klaim_kedua(klien):
    """Klaim kedua memakai foto yang sama persis, dan harus ketahuan."""
    klien.post("/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto())
    data = kirim_klaim(klien)

    c2 = next(c for c in data["cek"] if c["kode"] == "C2")
    assert c2["lolos"] is False
    assert data["verdict_validitas"] == "invalid"


def test_klaim_pertama_tidak_menuduh_dirinya_sendiri(klien):
    """Foto milik klaim yang sedang diproses harus dikecualikan dari perbandingan."""
    data = kirim_klaim(klien)
    c2 = next(c for c in data["cek"] if c["kode"] == "C2")
    assert c2["lolos"] is True


def test_surat_baru_terbit_setelah_adjuster_memutuskan(klien):
    kirim = kirim_klaim(klien)

    # Sebelum ada keputusan, belum ada surat apa pun.
    assert kirim["keputusan"] == []

    lengkapi_review(klien, kirim)
    r = klien.post(
        f"/api/klaim/{kirim['id']}/keputusan",
        json={"keputusan": "setuju", "catatan": "Sesuai temuan"},
    )
    assert r.status_code == 200
    hasil = r.json()
    assert hasil["status"] == "disetujui"
    assert hasil["surat"] in {"spk", "penawaran_beli"}


def test_keputusan_ditandatangani_akun_yang_sedang_masuk(klien):
    """Nama pengambil keputusan tidak bisa diketik, diambil dari token."""
    kirim = kirim_klaim(klien)
    lengkapi_review(klien, kirim)

    klien.post(
        f"/api/klaim/{kirim['id']}/keputusan",
        json={"keputusan": "setuju", "catatan": "", "oleh": "Orang Lain"},
    )

    detail = klien.get(f"/api/klaim/{kirim['id']}").json()
    assert detail["keputusan"][0]["oleh"] == "admin"


def test_keputusan_tak_dikenal_ditolak(klien):
    kirim = kirim_klaim(klien)

    r = klien.post(
        f"/api/klaim/{kirim['id']}/keputusan",
        json={"keputusan": "mungkin"},
    )
    assert r.status_code == 400


def test_keputusan_tercatat_di_detail_klaim(klien):
    kirim = kirim_klaim(klien)
    lengkapi_review(klien, kirim)
    klien.post(
        f"/api/klaim/{kirim['id']}/keputusan",
        json={"keputusan": "tolak", "catatan": "Bukti kurang"},
    )

    detail = klien.get(f"/api/klaim/{kirim['id']}").json()
    assert detail["status"] == "ditolak"
    assert detail["keputusan"][0]["oleh"] == "admin"
    assert detail["keputusan"][0]["catatan"] == "Bukti kurang"


def test_keputusan_bisa_dibatalkan_lalu_diputuskan_ulang(klien):
    """Pembatalan menarik suratnya dan mengembalikan klaim ke antrean adjuster."""
    kirim = kirim_klaim(klien)
    lengkapi_review(klien, kirim)
    klien.post(f"/api/klaim/{kirim['id']}/keputusan", json={"keputusan": "setuju"})

    r = klien.delete(f"/api/klaim/{kirim['id']}/keputusan")
    assert r.status_code == 200
    assert r.json()["surat_ditarik"] is True

    detail = klien.get(f"/api/klaim/{kirim['id']}").json()
    assert detail["keputusan"] == []
    assert detail["status"] == "siap_review"

    # Surat yang lama sudah hilang, jadi keputusan berikutnya bisa menerbitkan yang baru.
    ulang = klien.post(f"/api/klaim/{kirim['id']}/keputusan", json={"keputusan": "setuju"})
    assert ulang.status_code == 200
    assert ulang.json()["surat"] in {"spk", "penawaran_beli"}


def test_c7_tidak_menuduh_klaim_yang_lebih_dulu_masuk(klien):
    """Klaim pertama tidak boleh ditandai mengulang kerusakan dari klaim yang menyusul.

    Riwayat dibaca ulang tiap kali rincian klaim dibuka, jadi tanpa batas waktu klaim lama
    ikut melihat klaim baru dan menuduhnya sebagai kerusakan yang pernah diklaim.
    """
    pertama = kirim_klaim(klien)
    kedua = kirim_klaim(klien)

    def usulan(klaim):
        rinci = klien.get(f"/api/klaim/{klaim['id']}").json()
        return [t["usulan"] for f in rinci["foto"] for t in f["temuan"] if t["usulan"]]

    assert usulan(pertama) == []
    # Yang menyusul boleh ditandai, karena riwayatnya memang sudah ada saat dia masuk.
    assert all(u["klaim_lama"] == pertama["nomor_klaim"] for u in usulan(kedua))


def test_revisi_wajib_pakai_catatan(klien):
    kirim = kirim_klaim(klien)
    lengkapi_review(klien, kirim)
    r = klien.post(f"/api/klaim/{kirim['id']}/keputusan",
                   json={"keputusan": "revisi", "catatan": "   "})
    assert r.status_code == 400
    assert "harus diperbaiki" in r.json()["detail"]

    # Setuju dan tolak tidak dibebani syarat yang sama, karena keduanya menutup klaim.
    assert klien.post(f"/api/klaim/{kirim['id']}/keputusan",
                      json={"keputusan": "tolak"}).status_code == 200


def test_revisi_mengembalikan_klaim_ke_surveyor_lalu_kiriman_lama_dibuang(klien):
    """Alur penuh revisi: adjuster mengembalikan klaim, surveyor mengirim ulang semuanya."""
    kirim = kirim_klaim(klien, jumlah=2)
    lengkapi_review(klien, kirim)
    sebelum = klien.get(f"/api/klaim/{kirim['id']}").json()
    foto_lama = {f["urutan"] for f in sebelum["foto"]}

    catatan = "Foto sisi kanan terlalu jauh, ambil ulang dari jarak 2 meter"
    r = klien.post(f"/api/klaim/{kirim['id']}/keputusan",
                   json={"keputusan": "revisi", "catatan": catatan})
    assert r.status_code == 200
    assert r.json()["status"] == "menunggu_foto_tambahan"

    lacak = klien.get("/api/klaim/saya").json()
    minta = next(k for k in lacak if k["id"] == kirim["id"])["permintaan_foto"]
    assert [p for p in minta if p["sumber"] == "adjuster" and not p["dipenuhi"]]
    assert minta[-1]["permintaan"] == catatan

    ulang = klien.post(
        f"/api/klaim/{kirim['id']}/kirim-ulang",
        files=[
            ("foto", ("revisi-1.jpg", foto_bytes(150), "image/jpeg")),
            ("foto", ("revisi-2.jpg", foto_bytes(200), "image/jpeg")),
            ("foto", ("revisi-3.jpg", foto_bytes(230), "image/jpeg")),
            ("foto_stnk", ("stnk-baru.jpg", foto_bytes(120), "image/jpeg")),
        ],
    )
    assert ulang.status_code == 202, ulang.text

    sesudah = klien.get(f"/api/klaim/{kirim['id']}").json()
    assert sesudah["status"] == "siap_review"
    assert [f["urutan"] for f in sesudah["foto"]] == [0, 1, 2]
    assert foto_lama != {f["urutan"] for f in sesudah["foto"]}
    # Keputusan revisinya ditarik, jadi klaim tidak membawa dua keputusan sekaligus.
    assert sesudah["keputusan"] == []
    # Penilaian adjuster ikut hilang, karena temuannya dihitung ulang dari foto baru.
    assert all(t["review"] is None for f in sesudah["foto"] for t in f["temuan"])
    assert sesudah["review_kurang"]


def test_kirim_ulang_wajib_menyertakan_stnk(klien):
    kirim = kirim_klaim(klien)
    lengkapi_review(klien, kirim)
    klien.post(f"/api/klaim/{kirim['id']}/keputusan",
               json={"keputusan": "revisi", "catatan": "Ambil ulang semuanya"})
    r = klien.post(
        f"/api/klaim/{kirim['id']}/kirim-ulang",
        files=[("foto", ("a.jpg", foto_bytes(150), "image/jpeg"))],
    )
    assert r.status_code == 400
    assert "STNK" in r.json()["detail"]


def test_batal_ditolak_kalau_klaim_belum_diputuskan(klien):
    kirim = kirim_klaim(klien)
    r = klien.delete(f"/api/klaim/{kirim['id']}/keputusan")
    assert r.status_code == 400


MINTA_FOTO = (
    '{"cukup_bukti": false, "permintaan_foto": ["Foto kap mesin dari sisi kiri, jarak 2 meter"],'
    ' "rekomendasi": "repair", "alasan": "Kerusakan kap mesin cuma terlihat di satu foto"}'
)
CUKUP_BUKTI = (
    '{"cukup_bukti": true, "permintaan_foto": [], "rekomendasi": "repair",'
    ' "alasan": "Bukti sudah cukup setelah foto tambahan masuk"}'
)


def test_agent_bisa_menahan_klaim_lalu_melanjutkannya_setelah_foto_masuk(tmp_path, monkeypatch):
    """Alur penuh permintaan foto tambahan, dari agent menahan sampai klaim siap direview."""
    otak = KlienLLMPalsu(MINTA_FOTO, CUKUP_BUKTI)
    with server_uji(tmp_path, monkeypatch, "tambahan.db", klien_llm=otak) as c:
        kirim = kirim_klaim(c)

        assert kirim["status"] == "menunggu_foto_tambahan"
        assert kirim["permintaan_foto"][0]["dipenuhi"] is False
        # Narasi sengaja tidak disusun selama klaim masih menunggu, supaya token tidak
        # terpakai untuk ringkasan yang langsung tidak berlaku.
        assert kirim["narasi"] == ""

        lanjut = c.post(
            f"/api/klaim/{kirim['id']}/kirim-ulang",
            files=[
                ("foto", ("ulang-1.jpg", foto_bytes(210), "image/jpeg")),
                ("foto_stnk", ("stnk-baru.jpg", foto_bytes(120), "image/jpeg")),
            ],
        )
        assert lanjut.status_code == 202, lanjut.text
        data = c.get(f"/api/klaim/{kirim['id']}").json()

    assert data["status"] == "siap_review"
    assert data["permintaan_foto"][0]["dipenuhi"] is True
    assert data["narasi"]
    assert data["penilaian_agent"]["alasan"].startswith("Bukti sudah cukup")


def test_kirim_ulang_berkali_kali_tetap_menomori_foto_dari_nol(tmp_path, monkeypatch):
    """Tiap kiriman ulang menggantikan yang lama, jadi nomor fotonya selalu mulai dari nol.

    Foto STNK dan overlay punya deret nomornya sendiri. Kalau ikut terhitung, foto baru
    dapat nomor yang tidak dipakai overlay maupun temuan, sehingga adjuster tetap melihat
    hasil deteksi foto lama.
    """
    otak = KlienLLMPalsu(MINTA_FOTO, MINTA_FOTO, CUKUP_BUKTI)
    with server_uji(tmp_path, monkeypatch, "urutan.db", klien_llm=otak) as c:
        kirim = kirim_klaim(c)
        for nama in ("ulang-1.jpg", "ulang-2.jpg"):
            lanjut = c.post(
                f"/api/klaim/{kirim['id']}/kirim-ulang",
                files=[
                    ("foto", (nama, foto_bytes(210), "image/jpeg")),
                    ("foto_stnk", ("stnk-baru.jpg", foto_bytes(120), "image/jpeg")),
                ],
            )
            assert lanjut.status_code == 202, lanjut.text
        data = c.get(f"/api/klaim/{kirim['id']}").json()

    foto = data["foto"]
    assert [f["urutan"] for f in foto] == list(range(len(foto)))
    assert all(f["ada_overlay"] for f in foto)
    assert data["status"] == "siap_review"


def test_kirim_ulang_ditolak_kalau_klaim_tidak_menunggu(klien):
    kirim = kirim_klaim(klien)
    r = klien.post(
        f"/api/klaim/{kirim['id']}/kirim-ulang",
        files=[
            ("foto", ("t.jpg", foto_bytes(210), "image/jpeg")),
            ("foto_stnk", ("s.jpg", foto_bytes(120), "image/jpeg")),
        ],
    )
    assert r.status_code == 400
    assert "tidak sedang menunggu" in r.json()["detail"]


def test_kirim_ulang_untuk_klaim_tidak_ada_balas_404(klien):
    r = klien.post(
        "/api/klaim/bukan-id/kirim-ulang",
        files=[
            ("foto", ("t.jpg", foto_bytes(210), "image/jpeg")),
            ("foto_stnk", ("s.jpg", foto_bytes(120), "image/jpeg")),
        ],
    )
    assert r.status_code == 404


def test_klaim_tidak_ada_balas_404(klien):
    assert klien.get("/api/klaim/bukan-id").status_code == 404


def test_foto_tersimpan_ke_folder(klien, tmp_path):
    klien.post("/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto())
    tersimpan = list((tmp_path / "foto").glob("*.jpg"))
    # 4 foto kerusakan, 4 pasangan overlay-nya, dan 1 foto STNK.
    assert len(tersimpan) == 9
    assert sum(1 for p in tersimpan if p.name.endswith("-stnk.jpg")) == 1
    assert sum(1 for p in tersimpan if p.name.endswith("-overlay.jpg")) == 4


def test_foto_bisa_diambil_beserta_overlaynya(klien):
    """Adjuster harus bisa melihat foto asal dan foto berlapis hasil deteksi."""
    kirim = kirim_klaim(klien)

    for jenis in ("kerusakan", "overlay"):
        r = klien.get(f"/api/klaim/{kirim['id']}/foto/0", params={"jenis": jenis})
        assert r.status_code == 200, jenis
        assert r.headers["content-type"] == "image/jpeg"
        assert Image.open(io.BytesIO(r.content)).size[0] > 0


def test_foto_yang_tidak_ada_balas_404(klien):
    kirim = kirim_klaim(klien)
    assert klien.get(f"/api/klaim/{kirim['id']}/foto/99").status_code == 404


def test_daftar_foto_membawa_temuan_tiap_foto(klien):
    """Angka biaya harus bisa ditelusuri balik ke foto mana yang jadi dasarnya."""
    kirim = kirim_klaim(klien)

    assert len(kirim["foto"]) == 4
    assert all(f["ada_overlay"] for f in kirim["foto"])
    assert any(f["temuan"] for f in kirim["foto"])

    temuan = next(t for f in kirim["foto"] for t in f["temuan"])
    assert temuan["part_class"]
    assert 0 <= temuan["rasio_luas"] <= 1
    assert 0 <= temuan["confidence_part"] <= 1
    # Layar menampilkan kata ini di samping rasionya, karena rasio sendirian gampang
    # dibaca sebagai hasil ukur padahal ikut berubah mengikuti sudut foto.
    assert temuan["sebaran"] in ("kecil", "sedang", "luas")


def test_ringkasan_menghitung_seluruh_klaim(klien):
    for _ in range(2):
        klien.post("/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto())

    r = klien.get("/api/overview")
    assert r.status_code == 200
    data = r.json()

    assert data["total_klaim"] == 2
    assert data["klaim_dinilai"] == 2
    assert sum(data["per_status"].values()) == 2
    assert data["total_nilai_klaim"] != "0"
    assert len(data["terbaru"]) == 2
    # Klaim kedua memakai foto yang sama, jadi pemeriksaan foto dipakai ulang harus gagal.
    assert data["gagal_cek"].get("C2") == 1


def test_ringkasan_pada_database_kosong_bernilai_nol(klien):
    data = klien.get("/api/overview").json()
    assert data["total_klaim"] == 0
    assert data["rata_rasio"] == 0.0
    assert data["gagal_cek"] == {}
    assert data["terbaru"] == []
    assert data["deteksi"]["akurasi"] is None


def _klaim_dengan_temuan(klien) -> tuple[str, list[dict]]:
    kirim = kirim_klaim(klien)
    temuan = [t for f in kirim["foto"] for t in f["temuan"]]
    return kirim["id"], temuan


def test_review_deteksi_tersimpan_dan_terbaca_lagi(klien):
    klaim_id, temuan = _klaim_dengan_temuan(klien)

    r = klien.post(
        f"/api/klaim/{klaim_id}/review-deteksi",
        json={
            "penilaian": [
                {"temuan_id": temuan[0]["id"], "benar": False, "alasan": "bagian_salah"},
                *[{"temuan_id": t["id"], "benar": True} for t in temuan[1:]],
            ]
        },
    )
    assert r.status_code == 200
    assert r.json()["dinilai"] == len(temuan)

    dinilai = {
        t["id"]: t["review"]
        for f in klien.get(f"/api/klaim/{klaim_id}").json()["foto"]
        for t in f["temuan"]
    }
    assert dinilai[temuan[0]["id"]]["benar"] is False
    assert dinilai[temuan[0]["id"]]["alasan"] == "bagian_salah"
    # Penilainya diambil dari akun yang masuk, bukan dari isian yang bisa diketik bebas.
    assert dinilai[temuan[0]["id"]]["oleh"] == "admin"
    assert dinilai[temuan[1]["id"]]["benar"] is True


def test_menilai_ulang_menimpa_bukan_menumpuk(klien):
    """Kalau menumpuk, angka akurasi di halaman Overview terhitung ganda."""
    klaim_id, temuan = _klaim_dengan_temuan(klien)
    satu = [{"temuan_id": temuan[0]["id"], "benar": False, "alasan": "kerusakan_lama"}]

    klien.post(f"/api/klaim/{klaim_id}/review-deteksi", json={"penilaian": satu})
    klien.post(
        f"/api/klaim/{klaim_id}/review-deteksi",
        json={"penilaian": [{"temuan_id": temuan[0]["id"], "benar": True}]},
    )

    deteksi = klien.get("/api/overview").json()["deteksi"]
    assert deteksi["dinilai"] == 1
    assert deteksi["benar"] == 1
    assert deteksi["akurasi"] == 1.0
    assert deteksi["alasan_salah"] == {}


def test_akurasi_hanya_menghitung_temuan_yang_sudah_dinilai(klien):
    klaim_id, temuan = _klaim_dengan_temuan(klien)
    assert len(temuan) >= 2

    klien.post(
        f"/api/klaim/{klaim_id}/review-deteksi",
        json={
            "penilaian": [
                {"temuan_id": temuan[0]["id"], "benar": True},
                {"temuan_id": temuan[1]["id"], "benar": False, "alasan": "luas_terlalu_besar"},
            ]
        },
    )

    deteksi = klien.get("/api/overview").json()["deteksi"]
    assert deteksi["total_temuan"] == len(temuan)
    assert deteksi["dinilai"] == 2
    assert deteksi["akurasi"] == 0.5
    assert deteksi["alasan_salah"] == {"luas_terlalu_besar": 1}


def test_hapus_klaim_membuang_seluruh_jejaknya(klien):
    klaim_id, temuan = _klaim_dengan_temuan(klien)
    klien.post(
        f"/api/klaim/{klaim_id}/review-deteksi",
        json={"penilaian": [{"temuan_id": temuan[0]["id"], "benar": True}]},
    )

    r = klien.delete(f"/api/klaim/{klaim_id}")
    assert r.status_code == 200
    assert r.json()["foto_dihapus"] > 0

    assert klien.get(f"/api/klaim/{klaim_id}").status_code == 404
    ringkas = klien.get("/api/overview").json()
    assert ringkas["total_klaim"] == 0
    assert ringkas["gagal_cek"] == {}
    assert ringkas["deteksi"]["total_temuan"] == 0
    assert ringkas["deteksi"]["dinilai"] == 0


def test_menghapus_klaim_lama_tidak_membuat_nomor_baru_menabrak(klien):
    """Nomor diambil dari yang tertinggi, bukan dari jumlah baris yang tersisa."""
    pertama = kirim_klaim(klien)
    kedua = kirim_klaim(klien)
    assert klien.delete(f"/api/klaim/{pertama['id']}").status_code == 200

    ketiga = kirim_klaim(klien)

    assert ketiga["nomor_klaim"] not in (pertama["nomor_klaim"], kedua["nomor_klaim"])


def test_hapus_klaim_tidak_meninggalkan_berkas_foto(tmp_path, monkeypatch):
    """Overlay hasil deteksi ikut jadi berkas, dan itu paling gampang tertinggal."""
    folder = tmp_path / "foto"
    with server_uji(tmp_path, monkeypatch, "hapusberkas.db") as c:
        klaim = kirim_klaim(c)
        assert list(folder.rglob("*.jpg")), "tidak ada berkas yang bisa diuji"

        c.delete(f"/api/klaim/{klaim['id']}")

    assert [p.name for p in folder.rglob("*.jpg")] == []


def test_sidik_jari_foto_terisi_setelah_pipeline_selesai(klien):
    """Baris fotonya ditulis sebelum pipeline jalan, sidik jarinya menyusul."""
    from sqlalchemy import select

    from app.db import session as sesi_modul
    from app.db.models import ClaimPhoto

    kirim_klaim(klien)
    with sesi_modul.sesi() as s:
        kerusakan = list(
            s.scalars(select(ClaimPhoto).where(ClaimPhoto.jenis == "kerusakan"))
        )
    assert len(kerusakan) == 4
    assert all(f.phash for f in kerusakan)


def test_status_klaim_membawa_permintaan_foto(tmp_path, monkeypatch):
    otak = KlienLLMPalsu(MINTA_FOTO)
    with server_uji(tmp_path, monkeypatch, "statusfoto.db", klien_llm=otak) as c:
        kirim = kirim_klaim(c)
        data = c.get(f"/api/klaim/{kirim['id']}/status").json()

    assert data["status"] == "menunggu_foto_tambahan"
    assert data["permintaan_foto"][0]["dipenuhi"] is False
    # Sengaja tipis: surveyor tidak perlu tahu biaya maupun hasil pemeriksaannya.
    assert set(data) == {"id", "nomor_klaim", "status", "permintaan_foto"}


def test_pipeline_yang_gagal_menandai_klaim_gagal(tmp_path, monkeypatch):
    """Klaim yang tertinggal selamanya di status diproses tidak bisa ditelusuri siapa pun."""

    class DetektorRusak:
        nama = "DetektorRusak"

        def deteksi(self, gambar):
            raise RuntimeError("bobot model tidak bisa dibaca")

    with server_uji(tmp_path, monkeypatch, "gagal.db", detektor=DetektorRusak()) as c:
        r = c.post(
            "/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas_foto()
        )
        assert r.status_code == 202
        data = c.get(f"/api/klaim/{r.json()['id']}").json()

    assert data["status"] == "gagal"


def test_hapus_klaim_yang_tidak_ada_dijawab_404(klien):
    assert klien.delete("/api/klaim/bukan-id").status_code == 404


def test_review_menolak_alasan_dan_temuan_yang_tidak_dikenal(klien):
    klaim_id, temuan = _klaim_dengan_temuan(klien)

    salah_alasan = klien.post(
        f"/api/klaim/{klaim_id}/review-deteksi",
        json={"penilaian": [{"temuan_id": temuan[0]["id"], "benar": False, "alasan": "ngawur"}]},
    )
    assert salah_alasan.status_code == 400

    # Temuan milik klaim lain tidak boleh bisa dinilai lewat klaim ini.
    lain_id, lain_temuan = _klaim_dengan_temuan(klien)
    bukan_miliknya = klien.post(
        f"/api/klaim/{klaim_id}/review-deteksi",
        json={"penilaian": [{"temuan_id": lain_temuan[0]["id"], "benar": True}]},
    )
    assert bukan_miliknya.status_code == 400
    assert lain_id != klaim_id


def test_c7_lolos_untuk_klaim_pertama_pada_satu_polis(klien):
    """Kendaraan yang baru pertama kali diklaim tidak punya riwayat untuk dicurigai."""
    data = kirim_klaim(klien, corak=1)

    c7 = next(c for c in data["cek"] if c["kode"] == "C7")
    assert c7["lolos"]
    assert all(t["usulan"] is None for f in data["foto"] for t in f["temuan"])


def test_c7_menandai_kerusakan_yang_pernah_diklaim_di_polis_yang_sama(klien):
    """Kerusakan yang tidak diperbaiki lalu diajukan lagi harus ketahuan dari riwayatnya.

    Foto kedua klaim sengaja dibuat bercorak berbeda supaya C2 tidak ikut menyalak. Yang
    diuji di sini kemampuan mengenali kerusakan yang sama dari sudut yang berbeda, bukan
    kemampuan mengenali berkas foto yang sama.
    """
    lama = kirim_klaim(klien, corak=1)
    baru = kirim_klaim(klien, corak=2)

    c2 = next(c for c in baru["cek"] if c["kode"] == "C2")
    assert c2["lolos"], "fotonya berbeda, C2 tidak boleh ikut menyalak"

    c7 = next(c for c in baru["cek"] if c["kode"] == "C7")
    assert not c7["lolos"]
    assert c7["tingkat"] == "soft"
    assert lama["nomor_klaim"] in c7["alasan"]

    usulan = [t["usulan"] for f in baru["foto"] for t in f["temuan"]]
    assert any(u and u["alasan"] == "kerusakan_lama" for u in usulan)


def test_c7_tidak_mengubah_angka_biaya(klien):
    """Pemeriksaan ini menandai, bukan mengurangi. Angkanya harus persis sama."""
    lama = kirim_klaim(klien, corak=1)
    baru = kirim_klaim(klien, corak=2)

    assert not next(c for c in baru["cek"] if c["kode"] == "C7")["lolos"]
    assert baru["biaya"]["total_biaya"] == lama["biaya"]["total_biaya"]
    assert baru["biaya"]["rekomendasi"] == lama["biaya"]["rekomendasi"]


def test_penilaian_adjuster_menang_atas_usulan_sistem(klien):
    """Adjuster yang sudah menjawab tidak boleh ditimpa usulan tiap halaman dimuat ulang."""
    kirim_klaim(klien, corak=1)
    baru = kirim_klaim(klien, corak=2)

    temuan = next(
        t for f in baru["foto"] for t in f["temuan"] if t["usulan"] is not None
    )
    r = klien.post(
        f"/api/klaim/{baru['id']}/review-deteksi",
        json={"penilaian": [{"temuan_id": temuan["id"], "benar": True, "alasan": None}]},
    )
    assert r.status_code == 200, r.text

    lagi = klien.get(f"/api/klaim/{baru['id']}").json()
    dinilai = next(
        t for f in lagi["foto"] for t in f["temuan"] if t["id"] == temuan["id"]
    )
    assert dinilai["review"]["benar"] is True


def test_keputusan_ditahan_sebelum_temuan_dinilai(klien):
    """Menandatangani keputusan berarti menandatangani angka yang sudah diperiksa."""
    klaim = kirim_klaim(klien)
    assert klaim["review_kurang"], "klaim baru seharusnya belum lengkap penilaiannya"

    r = klien.post(f"/api/klaim/{klaim['id']}/keputusan", json={"keputusan": "setuju"})
    assert r.status_code == 400
    assert "belum dinilai" in r.json()["detail"]


def test_menolak_pun_ditahan_sebelum_dinilai(klien):
    """Menolak klaim orang juga keputusan, jadi dasarnya harus sudah diperiksa."""
    klaim = kirim_klaim(klien)

    r = klien.post(f"/api/klaim/{klaim['id']}/keputusan", json={"keputusan": "tolak"})
    assert r.status_code == 400


def test_stnk_yang_belum_dinilai_menahan_keputusan(klien):
    """Temuan sudah dinilai belum cukup, hasil baca STNK juga harus diperiksa."""
    klaim = kirim_klaim(klien)
    temuan = [t for f in klaim["foto"] for t in f["temuan"]]
    klien.post(
        f"/api/klaim/{klaim['id']}/review-deteksi",
        json={"penilaian": [
            {"temuan_id": t["id"], "benar": True, "alasan": None} for t in temuan
        ]},
    )

    r = klien.post(f"/api/klaim/{klaim['id']}/keputusan", json={"keputusan": "setuju"})
    assert r.status_code == 400
    assert "STNK" in r.json()["detail"]


def test_keputusan_terbuka_setelah_keduanya_dinilai(klien):
    klaim = lengkapi_review(klien, kirim_klaim(klien))
    assert klaim["review_kurang"] is None

    r = klien.post(f"/api/klaim/{klaim['id']}/keputusan", json={"keputusan": "setuju"})
    assert r.status_code == 200, r.text


def test_penilaian_bisa_dibatalkan_lalu_menutup_lagi_tombol_keputusan(klien):
    """Membatalkan penilaian harus mengembalikan penjagaannya, bukan cuma membuka layar."""
    klaim = lengkapi_review(klien, kirim_klaim(klien))

    batal = klien.delete(f"/api/klaim/{klaim['id']}/review-deteksi")
    assert batal.status_code == 200, batal.text
    assert batal.json()["review_kurang"]

    r = klien.post(f"/api/klaim/{klaim['id']}/keputusan", json={"keputusan": "setuju"})
    assert r.status_code == 400


def test_penilaian_tidak_bisa_dibatalkan_setelah_klaim_diputuskan(klien):
    """Penilaian itu dasar keputusannya, jadi keputusannya dibatalkan lebih dulu."""
    klaim = lengkapi_review(klien, kirim_klaim(klien))
    klien.post(f"/api/klaim/{klaim['id']}/keputusan", json={"keputusan": "setuju"})

    assert klien.delete(f"/api/klaim/{klaim['id']}/review-deteksi").status_code == 400
    assert klien.delete(f"/api/klaim/{klaim['id']}/review-stnk").status_code == 400

    klien.delete(f"/api/klaim/{klaim['id']}/keputusan")
    assert klien.delete(f"/api/klaim/{klaim['id']}/review-deteksi").status_code == 200


def test_batal_ditolak_kalau_belum_pernah_dinilai(klien):
    klaim = kirim_klaim(klien)
    assert klien.delete(f"/api/klaim/{klaim['id']}/review-deteksi").status_code == 400


def test_overview_memisahkan_ketepatan_deteksi_dan_baca_stnk(klien):
    """Dua kemampuan berbeda, jadi angkanya tidak boleh digabung jadi satu.

    Satu mengenali bentuk kerusakan, satu membaca tulisan di STNK. Satu angka gabungan
    menyembunyikan mana yang sebenarnya bermasalah.
    """
    klaim = kirim_klaim(klien)

    awal = klien.get("/api/overview").json()
    assert awal["deteksi"]["akurasi"] is None
    assert awal["stnk"]["akurasi"] is None

    lengkapi_review(klien, klaim)

    hasil = klien.get("/api/overview").json()
    assert hasil["deteksi"]["akurasi"] == 1.0
    assert hasil["deteksi"]["dinilai"] > 0
    assert hasil["stnk"]["akurasi"] == 1.0
    assert hasil["stnk"]["benar"] == hasil["stnk"]["dinilai"] > 0


def test_field_stnk_yang_ditandai_salah_menurunkan_ketepatannya(klien):
    """Angkanya harus ikut turun, kalau tidak kartu itu cuma hiasan."""
    klaim = kirim_klaim(klien)
    klien.post(
        f"/api/klaim/{klaim['id']}/review-stnk",
        json={"penilaian": [
            {"field": "merk", "benar": True, "nilai_benar": None},
            {"field": "tipe", "benar": False, "nilai_benar": "AVANZA 1.3 G"},
        ]},
    )

    hasil = klien.get("/api/overview").json()["stnk"]
    assert hasil["dinilai"] == 2
    assert hasil["benar"] == 1
    assert hasil["akurasi"] == 0.5
    assert hasil["salah_per_field"] == {"tipe": 1}


def test_target_demo_kosong_kalau_bahan_demonya_tidak_ada(klien, monkeypatch, tmp_path):
    """Di server, folder bahan demo memang tidak ikut diunggah.

    Keadaan itu harus dijawab daftar kosong, bukan galat, karena layar memakainya untuk
    mematikan sendiri tombol pemasangan. Galat 500 di sini membuat halaman Demo terlihat
    rusak padahal galerinya berfungsi penuh.
    """
    from app.api import demo

    monkeypatch.setattr(demo, "SKENARIO", tmp_path / "tidak-ada")
    r = klien.get("/api/demo/target")
    assert r.status_code == 200
    assert r.json() == []
