"use client";

import { useState } from "react";
import PratinjauFoto from "@/components/PratinjauFoto";
import { alamatFoto, type DetailKlaim } from "@/lib/api";

/** Galeri bukti pendukung yang tidak ikut dihitung.
 *
 *  Foto dekat seperti nomor rangka dan ruang mesin tidak memuat bentuk mobil yang utuh,
 *  jadi kalau ikut dideteksi dia menghasilkan bagian yang salah dan bagian salah itu
 *  langsung masuk ke perhitungan biaya. Di sini foto itu tetap sampai ke adjuster sebagai
 *  bahan penilaian, tanpa pernah menyentuh angka. */
export default function FotoPelengkap({ klaim }: { klaim: DetailKlaim }) {
  const [dibuka, setDibuka] = useState<number | null>(null);

  if (!klaim.pelengkap?.length) return null;

  // Nomor urut fotonya tidak selalu rapat, jadi perpindahan dihitung dari posisinya di
  // daftar, bukan dari nomor urutnya.
  const nomor = dibuka === null ? -1 : klaim.pelengkap.indexOf(dibuka);

  function pindah(arah: number) {
    const daftar = klaim.pelengkap ?? [];
    const tujuan = daftar.indexOf(dibuka as number) + arah;
    if (tujuan >= 0 && tujuan < daftar.length) setDibuka(daftar[tujuan]);
  }

  return (
    <div className="kartu">
      <h2>Foto pelengkap dari surveyor</h2>
      <p className="petunjuk">
        {klaim.pelengkap.length} foto bukti pendukung.{" "}
        <strong>Tidak ikut dibaca sistem dan tidak memengaruhi biaya</strong>, jadi
        tidak ada temuan maupun baris biaya yang berasal dari sini. Klik untuk
        memperbesar.
      </p>

      <div className="galeri-pelengkap">
        {klaim.pelengkap.map((urutan) => (
          <button
            key={urutan}
            type="button"
            className="ubin-foto"
            onClick={() => setDibuka(urutan)}
          >
            <img
              src={alamatFoto(klaim.id, urutan, "pelengkap")}
              alt={`Foto pelengkap nomor ${urutan + 1}`}
            />
          </button>
        ))}
      </div>

      {dibuka !== null && (
        <PratinjauFoto
          panel={[{
            judul: `Foto pelengkap ${nomor + 1} dari ${klaim.pelengkap.length}`,
            alamat: alamatFoto(klaim.id, dibuka, "pelengkap"),
            keterangan: `Foto pelengkap nomor ${nomor + 1}`,
          }]}
          saatTutup={() => setDibuka(null)}
          saatSebelum={nomor > 0 ? () => pindah(-1) : undefined}
          saatSesudah={
            nomor < klaim.pelengkap.length - 1 ? () => pindah(1) : undefined
          }
        />
      )}
    </div>
  );
}
