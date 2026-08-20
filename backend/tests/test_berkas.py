"""Uji lapisan penyimpanan foto.

Yang diuji cuma penyimpan folder. `PenyimpanSupabase` butuh akun sungguhan, jadi tidak
diuji di sini dan memang ditandai belum teruji di kodenya. Yang penting dijamin di berkas
ini: gambar yang disimpan bisa dibuka kembali utuh, dan pemilihan penyimpan mengikuti
variabel lingkungan.
"""

from PIL import Image

from app.core.berkas import PenyimpanFolder, PenyimpanSupabase, buat_penyimpan


def gambar_uji(warna=(200, 40, 60), ukuran=(160, 120)) -> Image.Image:
    return Image.new("RGB", ukuran, warna)


def test_simpan_lalu_buka_menghasilkan_gambar_yang_sama(tmp_path):
    penyimpan = PenyimpanFolder(tmp_path / "foto")
    lokasi = penyimpan.simpan("KLM-2026-0001-00.jpg", gambar_uji())

    dibuka = penyimpan.buka(lokasi)
    assert dibuka.size == (160, 120)
    # JPEG memampatkan dengan kehilangan, jadi warnanya dibandingkan longgar, bukan persis.
    assert all(abs(a - b) < 12 for a, b in zip(dibuka.getpixel((80, 60)), (200, 40, 60)))


def test_folder_dibuat_sendiri_kalau_belum_ada(tmp_path):
    folder = tmp_path / "belum" / "ada"
    PenyimpanFolder(folder)
    assert folder.is_dir()


def test_gambar_transparan_tetap_bisa_disimpan(tmp_path):
    """PNG dengan lapisan alfa tidak bisa langsung ditulis jadi JPEG."""
    penyimpan = PenyimpanFolder(tmp_path)
    lokasi = penyimpan.simpan("alfa.jpg", Image.new("RGBA", (40, 40), (10, 20, 30, 128)))
    assert penyimpan.buka(lokasi).mode == "RGB"


def test_nama_berbeda_tidak_saling_menimpa(tmp_path):
    penyimpan = PenyimpanFolder(tmp_path)
    satu = penyimpan.simpan("a.jpg", gambar_uji((255, 0, 0)))
    dua = penyimpan.simpan("b.jpg", gambar_uji((0, 0, 255)))

    assert satu != dua
    assert penyimpan.buka(satu).getpixel((10, 10))[0] > 200
    assert penyimpan.buka(dua).getpixel((10, 10))[2] > 200


def test_tanpa_pengaturan_supabase_memakai_folder(tmp_path, monkeypatch):
    for kunci in ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_BUCKET"):
        monkeypatch.delenv(kunci, raising=False)
    assert isinstance(buat_penyimpan(tmp_path), PenyimpanFolder)


def test_pengaturan_supabase_lengkap_memakai_supabase(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://contoh.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "kunci-contoh")
    monkeypatch.setenv("SUPABASE_BUCKET", "foto-klaim")
    assert isinstance(buat_penyimpan(tmp_path), PenyimpanSupabase)


def test_pengaturan_supabase_setengah_tetap_memakai_folder(tmp_path, monkeypatch):
    """Pengaturan yang tidak lengkap harus jatuh ke folder, bukan gagal saat klaim masuk."""
    monkeypatch.setenv("SUPABASE_URL", "https://contoh.supabase.co")
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_BUCKET", raising=False)
    assert isinstance(buat_penyimpan(tmp_path), PenyimpanFolder)
