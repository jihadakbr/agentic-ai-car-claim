export function rupiah(nilai: string | number | null | undefined): string {
  if (nilai === null || nilai === undefined) return "-";
  const angka = typeof nilai === "string" ? Number(nilai) : nilai;
  if (Number.isNaN(angka)) return "-";
  return `Rp ${angka.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export function persen(nilai: number | null | undefined, desimal = 1): string {
  if (nilai === null || nilai === undefined) return "-";
  return `${(nilai * 100).toFixed(desimal)}%`;
}

/** Zona waktunya dipatok ke WIB, bukan mengikuti setelan komputer yang membuka.
 *  Klaim asuransi Indonesia dibaca dalam WIB, dan saat presentasi layarnya bisa saja
 *  dibuka dari laptop yang zonanya tidak diperiksa siapa pun. */
export function waktu(iso: string | null): string {
  if (!iso) return "-";
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return "-";
  return `${t.toLocaleString("en-GB", {
    timeZone: "Asia/Jakarta",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })} WIB`;
}

const LABEL_STATUS: Record<string, string> = {
  diproses: "Diproses",
  siap_review: "Siap direview",
  menunggu_foto_tambahan: "Perlu upload ulang",
  disetujui: "Disetujui",
  ditolak: "Ditolak",
  perlu_revisi: "Perlu revisi",
  gagal: "Gagal diproses",
};

export function labelStatus(status: string): string {
  return LABEL_STATUS[status] ?? status;
}

const WARNA_STATUS: Record<string, string> = {
  disetujui: "hijau",
  ditolak: "merah",
  gagal: "merah",
  siap_review: "kuning",
  menunggu_foto_tambahan: "kuning",
  perlu_revisi: "kuning",
  diproses: "abu",
};

/** Kelas warna lencana status. Ditaruh di sini supaya Overview, Daftar Klaim, dan Klaim
 *  Saya memberi warna yang sama untuk status yang sama. */
export function warnaStatus(status: string): string {
  return WARNA_STATUS[status] ?? "abu";
}

const LABEL_REKOMENDASI: Record<string, string> = {
  repair: "Perbaikan",
  total_loss: "Total loss",
  tolak: "Tolak",
};

export function labelRekomendasi(nilai: string | null): string {
  if (!nilai) return "-";
  return LABEL_REKOMENDASI[nilai] ?? nilai;
}
