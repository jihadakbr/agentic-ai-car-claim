// Menolak foto yang sama dipilih lebih dari sekali dalam satu kiriman, sebelum satu byte
// pun dikirim ke server.
//
// Yang dibandingkan isi berkasnya, bukan namanya, karena mengganti nama berkas adalah cara
// paling gampang untuk memilih foto yang sama dua kali. Perhitungannya memakai berkas asli,
// bukan hasil perkecilan, supaya tidak bergantung pada hasil kompresi tiap browser.
//
// Foto yang dipakai ulang dari klaim lain bukan urusan berkas ini. Itu diperiksa server
// lewat sidik jari gambar, karena browser cuma tahu kiriman dari dirinya sendiri.

const PANJANG_SIDIK = 32;

/** crypto.subtle cuma ada di halaman aman. localhost dan https memenuhi syarat itu. */
export function bisaMenyidik(): boolean {
  return typeof crypto !== "undefined" && crypto.subtle !== undefined;
}

async function sidikBerkas(berkas: File): Promise<string> {
  const isi = await berkas.arrayBuffer();
  const cerna = await crypto.subtle.digest("SHA-256", isi);
  return Array.from(new Uint8Array(cerna))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, PANJANG_SIDIK);
}

/** Sidik jari tiap foto, urut sesuai berkasnya dipilih. */
export function sidikSemua(berkas: File[]): Promise<string[]> {
  return Promise.all(berkas.map(sidikBerkas));
}

/** Nama berkas yang isinya kembar di dalam satu kiriman. */
export function berkasKembar(berkas: File[], sidik: string[]): string[] {
  const terlihat = new Map<string, string>();
  const kembar: string[] = [];
  sidik.forEach((s, i) => {
    const awal = terlihat.get(s);
    if (awal) kembar.push(`${awal} dan ${berkas[i].name}`);
    else terlihat.set(s, berkas[i].name);
  });
  return kembar;
}
