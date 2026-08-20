// Token disimpan di localStorage, bukan cookie, karena frontend dan backend berada di
// alamat berbeda saat deploy (Vercel dan Hugging Face Space) dan cookie lintas alamat
// merepotkan. Konsekuensinya token bisa dibaca skrip di halaman ini, dan itu diterima
// untuk demo dengan data buatan.

const KUNCI = "acc.sesi";

export type Peran = "surveyor" | "adjuster" | "admin";

export type Sesi = {
  token: string;
  username: string;
  nama: string;
  peran: string;
  izin: string[];
};

// Daftar hak yang dipakai frontend untuk memilih menu. Penjagaan sungguhannya di server,
// ini cuma supaya layar tidak menawarkan halaman yang ujungnya ditolak.
export const IZIN = {
  polisLihat: "polis.lihat",
  klaimKirim: "klaim.kirim",
  klaimLacak: "klaim.lacak_sendiri",
  klaimLihat: "klaim.lihat",
  klaimPutuskan: "klaim.putuskan",
  klaimReview: "klaim.review_deteksi",
  klaimHapus: "klaim.hapus",
  overviewLihat: "overview.lihat",
  aksesKelola: "akses.kelola",
} as const;

export function punyaIzin(kode: string): boolean {
  return ambilSesi()?.izin?.includes(kode) ?? false;
}

/** Penjaga halaman, dipakai lewat prop `butuh` di Kerangka. */
export function butuhIzin(kode: string) {
  return (sesi: Sesi | null) => sesi?.izin?.includes(kode) ?? false;
}

export function simpanSesi(sesi: Sesi) {
  localStorage.setItem(KUNCI, JSON.stringify(sesi));
}

export function ambilSesi(): Sesi | null {
  if (typeof window === "undefined") return null;
  const isi = localStorage.getItem(KUNCI);
  if (!isi) return null;
  try {
    return JSON.parse(isi) as Sesi;
  } catch {
    return null;
  }
}

export function hapusSesi() {
  localStorage.removeItem(KUNCI);
}

/** Halaman pertama setelah masuk, dipilih dari hak yang dimiliki, bukan dari nama peran.
 *  Dengan peran yang bisa dibuat sendiri, menebak dari namanya tidak lagi bisa diandalkan. */
export function halamanAwal(sesi: Sesi): string {
  const punya = (kode: string) => sesi.izin?.includes(kode) ?? false;
  if (punya(IZIN.klaimKirim)) return "/surveyor";
  if (punya(IZIN.overviewLihat)) return "/overview";
  if (punya(IZIN.klaimLihat)) return "/adjuster";
  if (punya(IZIN.aksesKelola)) return "/akses";
  return "/login";
}
