"use client";

import { useState } from "react";
import { kirimUlangKlaim, type KirimanSaya } from "@/lib/api";
import { perkecil } from "@/lib/gambar";

// Batas sebenarnya ada di tabel config dan ditegakkan server. Angka di sini cuma supaya
// tombol Kirim mati lebih awal, jadi kalau config diubah, angka ini ikut disesuaikan.
const MIN_FOTO = 1;
const MAX_FOTO = 6;

/** Jendela kirim ulang untuk klaim yang fotonya diminta diganti.
 *
 *  Bedanya dengan jendela foto tambahan: di sini seluruh foto kerusakan diganti, bukan
 *  ditambahi. Dipakai kalau foto lamanya buram, kembar, atau klaimnya dikembalikan adjuster,
 *  tiga keadaan yang sama-sama berarti foto lama tidak layak jadi dasar keputusan.
 */
export default function DialogKirimUlang({
  kiriman,
  tutup,
  saatTerkirim,
}: {
  kiriman: KirimanSaya;
  tutup: () => void;
  saatTerkirim: (status: string) => void;
}) {
  const [foto, setFoto] = useState<File[]>([]);
  const [fotoStnk, setFotoStnk] = useState<File | null>(null);
  const [pelengkap, setPelengkap] = useState<File[]>([]);
  const [sibuk, setSibuk] = useState(false);
  const [galat, setGalat] = useState("");

  async function kirim() {
    setSibuk(true);
    setGalat("");
    try {
      if (!fotoStnk) return;
      const kecil = await Promise.all(foto.map(perkecil));
      const stnkKecil = await perkecil(fotoStnk);
      const pelengkapKecil = await Promise.all(pelengkap.map(perkecil));
      const hasil = await kirimUlangKlaim(kiriman.id, kecil, stnkKecil, pelengkapKecil);
      saatTerkirim(hasil.status);
    } catch (e) {
      setGalat((e as Error).message);
    } finally {
      setSibuk(false);
    }
  }

  const belum = kiriman.permintaan_foto.filter((p) => !p.dipenuhi);
  const lengkap = foto.length >= MIN_FOTO && foto.length <= MAX_FOTO && !!fotoStnk;

  return (
    <div className="tirai" role="dialog" aria-modal="true" aria-label="Kirim ulang klaim">
      <div className="dialog">
        <h2>Klaim {kiriman.nomor_klaim} perlu dikirim ulang</h2>
        <p>
          Seluruh berkas yang lama dihapus. Ambil ulang semuanya sesuai permintaan di
          bawah ini.
        </p>

        <ul className="daftar-minta">
          {belum.map((p, i) => (
            <li key={i}>
              <strong>{p.permintaan}</strong>
              {p.alasan && <div className="redup">{p.alasan}</div>}
            </li>
          ))}
        </ul>

        <label htmlFor="revisi-foto">
          Foto kerusakan <span className="wajib" aria-hidden="true">*</span>
        </label>
        <input
          id="revisi-foto"
          type="file"
          accept="image/jpeg,image/png"
          multiple
          onChange={(e) => setFoto(Array.from(e.target.files ?? []))}
        />

        <label htmlFor="revisi-stnk">
          Foto STNK <span className="wajib" aria-hidden="true">*</span>
        </label>
        <input
          id="revisi-stnk"
          type="file"
          accept="image/jpeg,image/png"
          onChange={(e) => setFotoStnk(e.target.files?.[0] ?? null)}
        />

        <label htmlFor="revisi-pelengkap">Foto pelengkap</label>
        <input
          id="revisi-pelengkap"
          type="file"
          accept="image/jpeg,image/png"
          multiple
          onChange={(e) => setPelengkap(Array.from(e.target.files ?? []))}
        />

        {galat && <div className="galat" style={{ marginTop: 12 }}>{galat}</div>}

        <div className="tombol-dialog">
          <button type="button" className="sekunder" onClick={tutup} disabled={sibuk}>
            Tutup
          </button>
          <button type="button" onClick={kirim} disabled={sibuk || !lengkap}>
            {sibuk ? "Mengirim..." : "Kirim ulang klaim"}
          </button>
        </div>
      </div>
    </div>
  );
}
