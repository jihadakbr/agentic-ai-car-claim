"use client";

import { useState } from "react";
import { batalkanKonfirmasiHarga, konfirmasiHarga, type Biaya } from "@/lib/api";
import { rupiah } from "@/lib/format";

const DARI_PENCARIAN = "pencarian_ai";
const TIDAK_DIKETAHUI = "tidak_diketahui";

export function butuhPengesahan(biaya: Biaya | null): boolean {
  if (!biaya) return false;
  const perlu =
    biaya.harga_pasar_sumber === DARI_PENCARIAN ||
    biaya.harga_pasar_sumber === TIDAK_DIKETAHUI;
  return perlu && !biaya.harga_dikonfirmasi_oleh;
}

/** Kartu pengesahan harga pasar bekas.
 *
 *  Muncul hanya kalau harganya bukan dari katalog. Harga bekas adalah penyebut rasio total
 *  loss dan penentu besar penawaran beli kendaraan, jadi angka yang datang dari pencarian
 *  internet atau yang belum ada sama sekali tidak boleh melewati titik keputusan tanpa ada
 *  nama yang bertanggung jawab. Tombol Setujui di bawah ikut mati sampai ini diisi. */
export default function HargaPasarAI({
  klaimId,
  biaya,
  saatDisahkan,
  terkunci = false,
}: {
  klaimId: string;
  biaya: Biaya;
  saatDisahkan: (baru: Biaya) => void;
  /** Klaim yang sudah diputuskan tetap menampilkan kartunya, tapi harganya tidak bisa
   *  diubah lagi. Angka ini penyebut rasio total loss, jadi mengubahnya setelah keputusan
   *  membuat surat yang sudah terbit tidak cocok lagi dengan dasar hitungannya. */
  terkunci?: boolean;
}) {
  const [koreksi, setKoreksi] = useState("");
  const [sibuk, setSibuk] = useState(false);
  const [galat, setGalat] = useState("");

  const belumAda = biaya.harga_pasar_sumber === TIDAK_DIKETAHUI;
  const sudah = biaya.harga_dikonfirmasi_oleh;

  async function sahkan() {
    setSibuk(true);
    setGalat("");
    try {
      saatDisahkan(await konfirmasiHarga(klaimId, koreksi.trim() || undefined));
    } catch (e) {
      setGalat((e as Error).message);
    } finally {
      setSibuk(false);
    }
  }

  async function batalkan() {
    setSibuk(true);
    setGalat("");
    try {
      saatDisahkan(await batalkanKonfirmasiHarga(klaimId));
      setKoreksi("");
    } catch (e) {
      setGalat((e as Error).message);
    } finally {
      setSibuk(false);
    }
  }

  if (sudah) {
    return (
      <div className="kartu kartu-aman">
        <h2>Harga pasar bekas sudah disahkan</h2>
        <p className="petunjuk">
          {rupiah(biaya.harga_pasar_bekas)}, disahkan oleh {sudah}.{" "}
          {biaya.harga_pasar_keterangan}
        </p>

        {galat && <div className="galat">{galat}</div>}

        <button
          className="sekunder"
          onClick={batalkan}
          disabled={sibuk || terkunci}
          title={
            terkunci
              ? "Klaim ini sudah diputuskan. Batalkan keputusannya lebih dulu."
              : undefined
          }
        >
          {sibuk ? "Membatalkan..." : "Batalkan pengesahan"}
        </button>
      </div>
    );
  }

  return (
    <div className="kartu kartu-peringatan">
      <h2>
        {belumAda
          ? "Harga pasar bekas belum diketahui"
          : "Harga pasar bekas dari pencarian AI Agent di Internet, bukan dari database"}
      </h2>

      {belumAda && (
        <p className="petunjuk">
          Kendaraan ini tidak ada di katalog harga, dan pencarian tidak menemukan angka
          yang bisa dipakai. Isi harganya sendiri sebelum memutuskan.
        </p>
      )}

      {!belumAda && (
        <p className="harga-besar">{rupiah(biaya.harga_pasar_bekas)}</p>
      )}

      {biaya.harga_pasar_keterangan && (
        <p className="petunjuk">{biaya.harga_pasar_keterangan}</p>
      )}

      {biaya.harga_rujukan.length > 0 && (
        <>
          <h3>Sumber yang dipakai agent</h3>
          <ul className="daftar-rujukan">
            {biaya.harga_rujukan.map((r, i) => (
              <li key={i}>
                <a href={r.url} target="_blank" rel="noopener noreferrer">
                  {r.judul || r.url}
                </a>
                {r.cuplikan && <div className="redup">{r.cuplikan}</div>}
              </li>
            ))}
          </ul>
        </>
      )}

      <div className="baris-harga">
        <div>
          <label htmlFor="koreksi-harga">
            Harga yang benar {belumAda && <span className="wajib">*</span>}
          </label>
          <input
            id="koreksi-harga"
            type="number"
            min={1}
            step={1000000}
            value={koreksi}
            disabled={terkunci}
            placeholder={belumAda ? "Rupiah, tanpa titik" : "Kosongkan kalau benar"}
            onChange={(e) => setKoreksi(e.target.value)}
          />
        </div>
        <button
          type="button"
          onClick={sahkan}
          disabled={sibuk || terkunci || (belumAda && !koreksi.trim())}
          title={
            terkunci
              ? "Klaim ini sudah diputuskan. Batalkan keputusannya lebih dulu."
              : undefined
          }
        >
          {sibuk
            ? "Menyimpan..."
            : koreksi.trim()
              ? "Koreksi dan sahkan harga"
              : "Saya sudah periksa, harga ini benar"}
        </button>
      </div>

      {galat && <div className="galat" style={{ marginTop: 12 }}>{galat}</div>}
    </div>
  );
}
