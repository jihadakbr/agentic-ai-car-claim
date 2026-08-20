// Bentuk tipe di sini menyalin persis bentuk jawaban backend. Nilai rupiah dikirim sebagai
// string, bukan number, supaya tidak kena pembulatan biner saat melewati JSON.

import { ambilSesi, hapusSesi, type Sesi } from "@/lib/auth";

export const ALAMAT_API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:7860";

export type Polis = {
  nomor_polis: string;
  nomor_polisi: string;
  pemegang: string;
  kendaraan: string;
  tahun: number;
};

export type Cek = {
  kode: string;
  nama: string;
  lolos: boolean;
  tingkat: string | null;
  alasan: string;
};

export type BarisBiaya = {
  part_class: string;
  sisi: string | null;
  nama_part: string;
  nomor_part: string;
  damage_class: string | null;
  kerusakan_lain: string;
  rasio_luas: number;
  operasi: string;
  ganti_part: boolean;
  harga_part: string;
  jam_standar: number;
  biaya_jasa: string;
  sumber: string;
};

export type Biaya = {
  total_part: string;
  total_jasa: string;
  total_biaya: string;
  harga_pasar_bekas: string;
  total_loss_ratio: number;
  ambang_total_loss: number;
  own_risk: string;
  ditanggung_penanggung: string;
  harga_tawaran_salvage: string | null;
  rekomendasi: string;
  /** "database", "database_polis", "pencarian_ai", "adjuster", atau "tidak_diketahui". */
  harga_pasar_sumber: string;
  harga_pasar_keterangan: string;
  harga_dikonfirmasi_oleh: string | null;
  harga_rujukan: RujukanHarga[];
};

export type RujukanHarga = { judul: string; url: string; cuplikan: string };

/** Sahkan harga pasar, boleh sekalian mengoreksinya. Kembalikan blok biaya yang sudah
 *  dihitung ulang. */
export function konfirmasiHarga(id: string, hargaDikoreksi?: string) {
  return minta<Biaya>(`/api/klaim/${id}/konfirmasi-harga`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ harga_dikoreksi: hargaDikoreksi ?? null }),
  });
}

/** Tarik pengesahan harga, supaya angkanya bisa diperiksa ulang. Angka hasil koreksi
 *  tetap dipakai, yang hilang cuma tanda tangannya. */
export function batalkanKonfirmasiHarga(id: string) {
  return minta<Biaya>(`/api/klaim/${id}/konfirmasi-harga`, { method: "DELETE" });
}

export type AlasanSalah =
  | "bagian_salah"
  | "jenis_kerusakan_salah"
  | "kerusakan_tidak_ada"
  | "luas_terlalu_besar"
  | "luas_terlalu_kecil"
  | "kerusakan_lama";

export type TemuanFoto = {
  id: string;
  part_class: string;
  sisi: string | null;
  damage_class: string | null;
  rasio_luas: number;
  sebaran?: string;
  confidence_part: number;
  confidence_damage: number;
  /** Nomor mask asalnya di foto ini. Kosong untuk klaim yang diproses versi lama. */
  part_urutan?: number | null;
  damage_urutan?: number | null;
  review: { benar: boolean; alasan: AlasanSalah | null; oleh: string } | null;
  /** Usulan penilaian dari cek riwayat klaim. Mengisi pilihan awal, bukan keputusan. */
  usulan?: {
    alasan: AlasanSalah;
    klaim_lama: string;
    status_klaim_lama: string;
    rasio_dulu: number;
  } | null;
};

export type FotoKlaim = {
  urutan: number;
  ada_overlay: boolean;
  urutan_overlay?: number | null;
  /** Bentuk tiap mask, untuk pratinjau yang menggambar overlaynya sendiri. Kosong untuk
   *  klaim lama, dan pratinjaunya jatuh ke gambar overlay biasa. */
  bentuk?: { part?: BentukMask[]; damage?: BentukMask[] };
  temuan: TemuanFoto[];
};

export type BentukMask = {
  kelas: string;
  keyakinan: number;
  titik: [number, number][];
};

export type Stnk = {
  merk: string | null;
  tipe: string | null;
  tahun: number | null;
  nomor_polisi: string | null;
  nomor_rangka: string | null;
  nama_pemilik: string | null;
  pakai_llm: boolean;
  /** Urutan berkas foto STNK-nya, melanjutkan nomor foto kerusakan. */
  urutan_foto: number | null;
};

export type RingkasanKlaim = {
  id: string;
  nomor_klaim: string;
  nomor_polis: string | null;
  pemegang_polis: string | null;
  kendaraan: string | null;
  status: string;
  surveyor: string;
  nama_surveyor: string | null;
  verdict_validitas: string | null;
  rekomendasi: string | null;
  total_biaya: string | null;
  harga_pasar_bekas: string | null;
  tahun_kendaraan: number | null;
  total_loss_ratio: number | null;
  dibuat: string | null;
  contoh_demo: boolean;
};

export type Surat = {
  jenis: "spk" | "penawaran_beli";
  nomor: string | null;
  tujuan: string;
  nilai: string;
  harga_pasar_bekas?: string;
  faktor_salvage?: number;
  waktu: string | null;
};

export type DetailKlaim = RingkasanKlaim & {
  foto: FotoKlaim[];
  /** Urutan tiap foto pelengkap. Foto ini tidak pernah dideteksi, jadi tidak punya temuan. */
  pelengkap: number[];
  narasi: string;
  penilaian_agent: { rekomendasi: string; alasan: string; jumlah_pass: number } | null;
  stnk: Stnk | null;
  cek: Cek[];
  biaya: Biaya | null;
  baris_biaya: BarisBiaya[];
  permintaan_foto: PermintaanFoto[];
  review_stnk: ReviewStnk[];
  /** Alasan kenapa klaim ini belum boleh diputuskan, kosong kalau sudah boleh. */
  review_kurang: string | null;
  keputusan: { keputusan: string; catatan: string; oleh: string; waktu: string | null }[];
  surat: Surat | null;
  token: { masuk: number; keluar: number };
};

function kepalaAuth(): Record<string, string> {
  const sesi = ambilSesi();
  return sesi ? { Authorization: `Bearer ${sesi.token}` } : {};
}

/** Token habis masa berlakunya saat presentasi harus berakhir di halaman masuk, bukan di
 *  layar error yang tidak bisa dijelaskan. */
function kembaliKeMasuk() {
  hapusSesi();
  if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    window.location.href = "/login";
  }
}

async function minta<T>(jalur: string, opsi?: RequestInit): Promise<T> {
  const r = await fetch(`${ALAMAT_API}${jalur}`, {
    cache: "no-store",
    ...opsi,
    headers: { ...kepalaAuth(), ...(opsi?.headers ?? {}) },
  });
  if (!r.ok) {
    // Penolakan di halaman masuk bukan sesi yang habis, jadi alasan aslinya yang
    // ditampilkan. Kalau disamakan, login yang gagal terbaca sebagai sesi berakhir.
    if (r.status === 401 && jalur !== "/api/login") {
      kembaliKeMasuk();
      throw new Error("Sesi berakhir, silakan masuk lagi");
    }
    // Backend mengirim alasan penolakan di field detail, dan alasan itu yang berguna
    // ditampilkan ke surveyor, bukan sekadar kode status.
    const isi = await r.json().catch(() => null);
    throw new Error(isi?.detail ?? `Permintaan gagal (${r.status})`);
  }
  return r.json();
}

export function masuk(username: string, password: string) {
  return minta<Sesi>("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

export function cekKesehatan() {
  return minta<{ siap: boolean; detektor: string; pesan: string }>("/api/kesehatan");
}

export function ambilPolis(nomor: string) {
  return minta<Polis>(`/api/polis/${encodeURIComponent(nomor)}`);
}

export function ambilDaftarKlaim() {
  return minta<RingkasanKlaim[]>("/api/klaim");
}

/** Alamat berkas foto. Token ikut lewat query karena tag img tidak bisa mengirim header. */
export function alamatFoto(
  id: string,
  urutan: number,
  jenis: "kerusakan" | "overlay" | "pelengkap" | "stnk",
) {
  const sesi = ambilSesi();
  const q = new URLSearchParams({ jenis, token: sesi?.token ?? "" });
  return `${ALAMAT_API}/api/klaim/${id}/foto/${urutan}?${q}`;
}

/** Alamat PDF estimasi. Token ikut lewat query karena tab baru dan unduhan tidak bisa
 *  mengirim header, sama seperti alamat foto. */
export function alamatEstimasiPdf(id: string, unduh = false) {
  const sesi = ambilSesi();
  const q = new URLSearchParams({ token: sesi?.token ?? "" });
  if (unduh) q.set("unduh", "1");
  return `${ALAMAT_API}/api/klaim/${id}/estimasi.pdf?${q}`;
}

/** Alamat PDF surat keputusan, mengikuti pola alamat estimasi. */
export function alamatSuratPdf(id: string, unduh = false) {
  const sesi = ambilSesi();
  const q = new URLSearchParams({ token: sesi?.token ?? "" });
  if (unduh) q.set("unduh", "1");
  return `${ALAMAT_API}/api/klaim/${id}/surat.pdf?${q}`;
}

export type Ringkasan = {
  total_klaim: number;
  per_status: Record<string, number>;
  per_verdict: Record<string, number>;
  per_rekomendasi: Record<string, number>;
  total_nilai_klaim: string;
  rata_rasio: number;
  klaim_dinilai: number;
  gagal_cek: Record<string, number>;
  deteksi: {
    total_temuan: number;
    dinilai: number;
    benar: number;
    akurasi: number | null;
    alasan_salah: Record<string, number>;
  };
  stnk: {
    dinilai: number;
    benar: number;
    akurasi: number | null;
    salah_per_field: Record<string, number>;
  };
  token: { masuk: number; keluar: number };
  terbaru: RingkasanKlaim[];
};

export function kirimReviewDeteksi(
  id: string,
  penilaian: { temuan_id: string; benar: boolean; alasan: AlasanSalah | null }[],
) {
  return minta<{ dinilai: number; foto: FotoKlaim[] }>(
    `/api/klaim/${id}/review-deteksi`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ penilaian }),
    },
  );
}

export function batalkanReviewDeteksi(id: string) {
  return minta<{ dibatalkan: number; review_kurang: string | null }>(
    `/api/klaim/${id}/review-deteksi`,
    { method: "DELETE" },
  );
}

export function batalkanReviewStnk(id: string) {
  return minta<{ dibatalkan: number; review_kurang: string | null }>(
    `/api/klaim/${id}/review-stnk`,
    { method: "DELETE" },
  );
}

export function ambilRingkasan() {
  return minta<Ringkasan>("/api/overview");
}

export function hapusKlaim(id: string) {
  return minta<{ nomor_klaim: string; foto_dihapus: number }>(`/api/klaim/${id}`, {
    method: "DELETE",
  });
}

export function ambilKlaim(id: string) {
  return minta<DetailKlaim>(`/api/klaim/${id}`);
}

export type PermintaanFoto = {
  permintaan: string;
  alasan: string;
  /** "aturan" kalau lahir dari aturan kode, "agent" kalau dari pertimbangan LLM. */
  sumber: string;
  dipenuhi: boolean;
};

/** Bentuk tipis untuk layar Klaim Saya. Tanpa biaya, verdict, maupun rekomendasi, karena
 *  ketiganya bahan keputusan adjuster. */
export type KirimanSaya = {
  id: string;
  nomor_klaim: string;
  nomor_polis: string | null;
  kendaraan: string | null;
  status: string;
  surveyor: string;
  nama_surveyor: string | null;
  dibuat: string | null;
  permintaan_foto: PermintaanFoto[];
};

export function ambilKirimanSaya() {
  return minta<KirimanSaya[]>("/api/klaim/saya");
}

/** Jawaban pengiriman sengaja tipis: pipelinenya baru jalan setelah jawaban ini terkirim. */
export type Terkirim = { id: string; nomor_klaim: string; status: string };

export type StatusKlaim = Terkirim & { permintaan_foto: PermintaanFoto[] };

export function ambilStatusKlaim(id: string) {
  return minta<StatusKlaim>(`/api/klaim/${id}/status`);
}

/** Kirim ulang seluruh berkas klaim yang ditahan menunggu foto.
 *
 *  Foto STNK ikut wajib. Kiriman lamanya dihapus seluruhnya, jadi menyisakan lembar STNK
 *  yang lama membuat klaim berdiri di atas dua kiriman yang berbeda.
 */
export function kirimUlangKlaim(
  id: string,
  foto: File[],
  fotoStnk: File,
  fotoPelengkap: File[] = [],
) {
  const isi = new FormData();
  foto.forEach((f) => isi.append("foto", f));
  isi.append("foto_stnk", fotoStnk);
  fotoPelengkap.forEach((f) => isi.append("foto_pelengkap", f));
  return minta<Terkirim>(`/api/klaim/${id}/kirim-ulang`, {
    method: "POST",
    body: isi,
  });
}

/** Kirim klaim lewat XHR, bukan fetch, karena cuma XHR yang melaporkan kemajuan unggahan. */
export function kirimKlaim(
  nomorPolis: string,
  foto: File[],
  fotoStnk: File,
  fotoPelengkap: File[] = [],
  saatUnggah?: (persen: number) => void,
): Promise<Terkirim> {
  const isi = new FormData();
  foto.forEach((f) => isi.append("foto", f));
  isi.append("foto_stnk", fotoStnk);
  fotoPelengkap.forEach((f) => isi.append("foto_pelengkap", f));
  // Nama surveyor tidak dikirim, backend memakai akun yang sedang masuk.
  const q = new URLSearchParams({ nomor_polis: nomorPolis });

  return new Promise((selesai, gagal) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${ALAMAT_API}/api/klaim?${q}`);
    Object.entries(kepalaAuth()).forEach(([k, v]) => xhr.setRequestHeader(k, v));
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && saatUnggah) saatUnggah(e.loaded / e.total);
    };
    xhr.onload = () => {
      let isi: unknown = null;
      try {
        isi = JSON.parse(xhr.responseText);
      } catch {
        gagal(new Error("Jawaban server tidak bisa dibaca"));
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        selesai(isi as Terkirim);
      } else if (xhr.status === 401) {
        kembaliKeMasuk();
        gagal(new Error("Sesi berakhir, silakan masuk lagi"));
      } else {
        const detail = (isi as { detail?: string } | null)?.detail;
        gagal(new Error(detail ?? `Permintaan gagal (${xhr.status})`));
      }
    };
    xhr.onerror = () => gagal(new Error("Tidak bisa menghubungi server"));
    xhr.send(isi);
  });
}

/** Nama pengambil keputusan tidak dikirim dari sini. Backend mengambilnya dari token,
 *  supaya tanda tangan keputusan menunjuk akun yang benar-benar masuk. */
export function kirimKeputusan(id: string, keputusan: string, catatan: string) {
  return minta<{ status: string; surat: string | null; nomor_spk?: string; harga_tawaran?: string }>(
    `/api/klaim/${id}/keputusan`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keputusan, catatan }),
    },
  );
}

/** Tarik kembali keputusan klaim. SPK atau penawaran beli yang sudah terbit ikut ditarik,
 *  dan klaim kembali ke antrean adjuster. */
export function batalkanKeputusan(id: string) {
  return minta<{ status: string; surat_ditarik: boolean }>(
    `/api/klaim/${id}/keputusan`,
    { method: "DELETE" },
  );
}

export type ReviewStnk = {
  field: string;
  benar: boolean;
  nilai_benar: string | null;
  oleh: string;
  waktu: string | null;
};

/** Catat benar atau salahnya tiap field hasil baca STNK. Koreksinya tidak menjalankan
 *  ulang cek validitas, cuma tersimpan sebagai catatan ketelitian. */
export function kirimReviewStnk(
  id: string,
  penilaian: { field: string; benar: boolean; nilai_benar: string | null }[],
) {
  return minta<{ dinilai: number; review_stnk: ReviewStnk[] }>(
    `/api/klaim/${id}/review-stnk`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ penilaian }),
    },
  );
}

export type PenggunaAkses = {
  username: string;
  nama: string;
  peran: string;
  nama_peran: string;
  aktif: boolean;
  dibuat: string | null;
};

export type PeranAkses = {
  kode: string;
  nama: string;
  keterangan: string;
  bawaan: boolean;
  jumlah_pengguna: number;
  izin: string[];
};

export type KatalogIzin = {
  kode: string;
  nama: string;
  keterangan: string;
  kelompok: string;
};

export type BarisLogAkses = {
  aksi: string;
  detail: Record<string, unknown>;
  waktu: string | null;
};

export function ambilPenggunaAkses() {
  return minta<PenggunaAkses[]>("/api/akses/pengguna");
}

export function buatPenggunaAkses(
  username: string,
  nama: string,
  peran: string,
  sandi: string,
) {
  return minta<Record<string, unknown>>("/api/akses/pengguna", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, nama, peran, sandi }),
  });
}

export function hapusPenggunaAkses(username: string) {
  return minta<Record<string, unknown>>(`/api/akses/pengguna/${username}`, {
    method: "DELETE",
  });
}

export function resetSandiPengguna(username: string) {
  return minta<Record<string, unknown>>(`/api/akses/pengguna/${username}/reset-sandi`, {
    method: "POST",
  });
}

export function ubahSandiSendiri(lama: string, baru: string) {
  return minta<Record<string, unknown>>("/api/sandi", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lama, baru }),
  });
}

export function ubahPenggunaAkses(
  username: string,
  ubah: { peran?: string; aktif?: boolean },
) {
  return minta<Record<string, unknown>>(`/api/akses/pengguna/${username}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(ubah),
  });
}

export function ambilPeranAkses() {
  return minta<{ peran: PeranAkses[]; katalog_izin: KatalogIzin[] }>("/api/akses/peran");
}

export function buatPeranAkses(kode: string, nama: string, keterangan: string) {
  return minta<Record<string, unknown>>("/api/akses/peran", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kode, nama, keterangan }),
  });
}

export function ubahPeranAkses(kode: string, nama: string, keterangan: string) {
  return minta<Record<string, unknown>>(`/api/akses/peran/${kode}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nama, keterangan }),
  });
}

export function hapusPeranAkses(kode: string) {
  return minta<Record<string, unknown>>(`/api/akses/peran/${kode}`, { method: "DELETE" });
}

export function aturIzinPeran(kode: string, daftar: string[]) {
  return minta<Record<string, unknown>>(`/api/akses/peran/${kode}/izin`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ izin: daftar }),
  });
}

export type TargetDemo = {
  folder: string;
  slot: { nomor: number; berkas: string }[];
  /** Folder lain yang ikut ditimpa bersamaan, misalnya pasangan foto dipakai ulang. */
  ikut: string[];
};

export function ambilTargetDemo() {
  return minta<TargetDemo[]>("/api/demo/target");
}

export function pasangFotoDemo(asal: string, folder: string, slot: number) {
  return minta<{ ditulis: string[] }>("/api/demo/pasang", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ asal, folder, slot }),
  });
}

export function ambilLogAkses() {
  return minta<BarisLogAkses[]>("/api/akses/log");
}
