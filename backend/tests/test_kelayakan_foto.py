"""Uji gerbang kelayakan foto, pemicu permintaan foto ulang.

Yang dijaga di sini: pemicunya deterministik dan per foto. Klaim yang sama harus selalu
menghasilkan permintaan yang sama, dan satu foto bermasalah di antara foto yang bagus tetap
diminta ulang, karena foto itulah yang mungkin menyembunyikan kerusakan yang belum terhitung.
"""

import pytest
from PIL import Image, ImageDraw, ImageFilter

from app.pipeline import kelayakan_foto
from app.pipeline.kelayakan_foto import BURAM, TIDAK_YAKIN, FotoDinilai, periksa
from app.pipeline.pra_proses import ketajaman, siapkan

TAJAM = 900.0
YAKIN = 0.94


def foto(urutan=0, keyakinan=YAKIN, tajam=TAJAM) -> FotoDinilai:
    return FotoDinilai(urutan=urutan, keyakinan_kendaraan=keyakinan, ketajaman=tajam)


def gambar_bercorak(ukuran=(900, 600)) -> Image.Image:
    """Gambar dengan banyak tepi, supaya ketajamannya jelas tinggi sebelum diburamkan."""
    img = Image.new("RGB", ukuran, (220, 220, 220))
    d = ImageDraw.Draw(img)
    for i in range(0, ukuran[0], 25):
        d.line([(i, 0), (i, ukuran[1])], fill=(20, 20, 20), width=3)
    for j in range(0, ukuran[1], 25):
        d.line([(0, j), (ukuran[0], j)], fill=(60, 60, 60), width=3)
    return img


def test_semua_foto_layak_tidak_menghasilkan_permintaan():
    assert periksa([foto(0), foto(1), foto(2)]) == []


def test_foto_buram_diminta_ulang():
    hasil = periksa([foto(0, tajam=20.0)])

    assert len(hasil) == 1
    assert hasil[0].sebab == BURAM
    assert "nomor 1" in hasil[0].permintaan


def test_foto_yang_keyakinannya_rendah_diminta_ulang():
    hasil = periksa([foto(0, keyakinan=0.31)])

    assert len(hasil) == 1
    assert hasil[0].sebab == TIDAK_YAKIN
    assert "31%" in hasil[0].alasan


def test_buram_didahulukan_saat_dua_duanya_bermasalah():
    """Buram itu sebabnya, keyakinan rendah cuma akibatnya. Menyebut dua-duanya membingungkan."""
    hasil = periksa([foto(0, keyakinan=0.20, tajam=15.0)])

    assert len(hasil) == 1
    assert hasil[0].sebab == BURAM


def test_satu_foto_buram_di_antara_foto_bagus_tetap_diminta():
    hasil = periksa([foto(0), foto(1, tajam=18.0), foto(2)])

    assert [h.urutan for h in hasil] == [1]
    assert "nomor 2" in hasil[0].permintaan


def test_nomor_foto_dihitung_mulai_dari_satu():
    """Surveyor melihat Foto 1 sampai Foto n di layar, bukan indeks nol."""
    hasil = periksa([foto(0, tajam=10.0), foto(1, tajam=10.0)])

    assert [h.nomor for h in hasil] == [1, 2]


def test_tepat_di_ambang_masih_dianggap_layak():
    ambang = kelayakan_foto.AMBANG_KETAJAMAN

    assert periksa([foto(0, tajam=ambang)]) == []
    assert periksa([foto(0, tajam=ambang - 1)])[0].sebab == BURAM


def test_alasan_selalu_menyebut_nomor_fotonya():
    """Tanpa nomor foto, surveyor tidak tahu foto mana yang harus diulang."""
    hasil = periksa([foto(0, tajam=5.0), foto(1, keyakinan=0.2)])

    for h in hasil:
        assert f"nomor {h.nomor}" in h.permintaan
        if h.alasan:
            assert f"nomor {h.nomor}" in h.alasan


def test_ringkasan_untuk_agent_kosong_kalau_semuanya_layak():
    assert kelayakan_foto.ringkas_untuk_agent([], 4) == []


def test_ringkasan_untuk_agent_menyebut_nomor_dan_sebabnya():
    baris = kelayakan_foto.ringkas_untuk_agent(periksa([foto(0), foto(1, tajam=9.0)]), 2)

    assert len(baris) == 1
    assert "nomor 2 dari 2" in baris[0]
    assert "buram" in baris[0]


@pytest.mark.parametrize("radius", [1.0, 2.0, 4.0])
def test_ketajaman_turun_tajam_saat_gambar_diburamkan(radius):
    """Yang diuji pemisahannya, bukan angka pastinya."""
    asli = gambar_bercorak()
    buram = asli.filter(ImageFilter.GaussianBlur(radius))

    assert ketajaman(asli) > kelayakan_foto.AMBANG_KETAJAMAN
    assert ketajaman(buram) < ketajaman(asli)


def test_ketajaman_ikut_terisi_saat_foto_disiapkan():
    siap = siapkan(gambar_bercorak())

    assert siap.ketajaman > 0


def test_ketajaman_gambar_sangat_kecil_tidak_meledak():
    assert ketajaman(Image.new("RGB", (1, 1), (0, 0, 0))) == 0.0


gradio = pytest.importorskip("gradio", reason="butuh dependensi opsional serve")

from tests.test_api import berkas_foto, foto_bytes, kirim_klaim, server_uji


def foto_buram_bytes() -> bytes:
    import io

    with Image.open(io.BytesIO(foto_bytes(140))) as img:
        buf = io.BytesIO()
        img.filter(ImageFilter.GaussianBlur(4)).save(buf, format="JPEG")
        return buf.getvalue()


def test_klaim_berfoto_buram_ditahan_untuk_difoto_ulang(tmp_path, monkeypatch):
    """Ujung ke ujung: foto buram berujung minta foto ulang, bukan klaim ditolak."""
    with server_uji(tmp_path, monkeypatch, nama_db="buram.db") as c:
        berkas = berkas_foto(jumlah=1)
        berkas.append(("foto", ("buram.jpg", foto_buram_bytes(), "image/jpeg")))

        r = c.post("/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas)
        assert r.status_code == 202, r.text
        klaim = c.get(f"/api/klaim/{r.json()['id']}").json()

    assert klaim["status"] == "menunggu_foto_tambahan"
    assert klaim["verdict_validitas"] != "invalid"
    # Biayanya tetap dihitung penuh, adjuster tidak menunggu foto ulang untuk melihat angka.
    assert klaim["biaya"]["total_biaya"]

    permintaan = klaim["permintaan_foto"]
    assert len(permintaan) == 1
    assert "nomor 2" in permintaan[0]["permintaan"]
    assert permintaan[0]["sumber"] == "aturan"


def test_klaim_berfoto_tajam_tidak_ditahan(tmp_path, monkeypatch):
    with server_uji(tmp_path, monkeypatch, nama_db="tajam.db") as c:
        klaim = kirim_klaim(c, jumlah=2)

    assert klaim["status"] == "siap_review"
    assert klaim["permintaan_foto"] == []


def test_kiriman_ulang_membuang_foto_buram_dan_melepas_status_menunggu(tmp_path, monkeypatch):
    """Foto buram diminta diganti, jadi kirim ulang harus benar-benar membuangnya.

    Kalau cuma ditambahi, foto buram itu tetap jadi foto pertama yang dilihat adjuster dan
    tetap ikut menghitung biaya, padahal sistem sendiri sudah menyatakannya tidak layak.
    """
    with server_uji(tmp_path, monkeypatch, nama_db="pengganti.db") as c:
        berkas = berkas_foto(jumlah=1)
        berkas.append(("foto", ("buram.jpg", foto_buram_bytes(), "image/jpeg")))
        klaim_id = c.post(
            "/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas
        ).json()["id"]
        assert c.get(f"/api/klaim/{klaim_id}").json()["status"] == "menunggu_foto_tambahan"

        r = c.post(
            f"/api/klaim/{klaim_id}/kirim-ulang",
            files=[
                ("foto", ("baru-1.jpg", foto_bytes(170), "image/jpeg")),
                ("foto", ("baru-2.jpg", foto_bytes(190), "image/jpeg")),
                ("foto_stnk", ("stnk-baru.jpg", foto_bytes(120), "image/jpeg")),
            ],
        )
        assert r.status_code == 202, r.text
        sesudah = c.get(f"/api/klaim/{klaim_id}").json()

    assert sesudah["status"] == "siap_review"
    assert len(sesudah["foto"]) == 2
    assert [f["urutan"] for f in sesudah["foto"]] == [0, 1]
    assert all(f["ada_overlay"] for f in sesudah["foto"])
    assert all(p["dipenuhi"] for p in sesudah["permintaan_foto"])


MINTA_SUDUT_LAIN = (
    '{"cukup_bukti": false,'
    ' "permintaan_foto": [{"foto": "Foto fender sisi kiri dari jarak 2 meter",'
    ' "alasan": "Kondisi fender belum terlihat jelas"}],'
    ' "rekomendasi": "repair", "alasan": "Bukti belum cukup"}'
)


def test_foto_buram_tidak_ditumpuki_usulan_agent(tmp_path, monkeypatch):
    """Foto yang harus diulang cukup diminta sekali.

    Agent menyusun kalimatnya sendiri, jadi kalau usulannya tetap dipakai, surveyor menerima
    dua permintaan yang menyuruh hal yang sama dengan kata yang berbeda.
    """
    from tests.test_api import KlienLLMPalsu

    otak = KlienLLMPalsu(MINTA_SUDUT_LAIN, MINTA_SUDUT_LAIN)
    with server_uji(tmp_path, monkeypatch, nama_db="buramagent.db", klien_llm=otak) as c:
        berkas = berkas_foto(jumlah=1)
        berkas.append(("foto", ("buram.jpg", foto_buram_bytes(), "image/jpeg")))

        r = c.post("/api/klaim", params={"nomor_polis": "POL-2024-0037"}, files=berkas)
        assert r.status_code == 202, r.text
        klaim = c.get(f"/api/klaim/{r.json()['id']}").json()

    permintaan = klaim["permintaan_foto"]
    assert [p["sumber"] for p in permintaan] == ["aturan"]
    assert "nomor 2" in permintaan[0]["permintaan"]


def test_usulan_agent_tetap_dipakai_kalau_semua_fotonya_layak(tmp_path, monkeypatch):
    """Pembatasnya khusus foto yang harus diulang, bukan mematikan usulan agent seluruhnya."""
    from tests.test_api import KlienLLMPalsu

    otak = KlienLLMPalsu(MINTA_SUDUT_LAIN, MINTA_SUDUT_LAIN)
    with server_uji(tmp_path, monkeypatch, nama_db="tajamagent.db", klien_llm=otak) as c:
        klaim = kirim_klaim(c, jumlah=2)

    permintaan = klaim["permintaan_foto"]
    assert [p["sumber"] for p in permintaan] == ["agent"]
    assert "fender" in permintaan[0]["permintaan"]
