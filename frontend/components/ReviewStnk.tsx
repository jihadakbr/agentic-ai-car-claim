"use client";

import { useState } from "react";
import PratinjauFoto from "@/components/PratinjauFoto";
import {
  alamatFoto,
  batalkanReviewStnk,
  kirimReviewStnk,
  type DetailKlaim,
} from "@/lib/api";

/** Field yang dinilai beserta urutan tampilnya. Sama persis dengan daftar di backend,
 *  field di luar daftar ini ditolak server. */
const FIELD: { kunci: string; label: string }[] = [
  { kunci: "merk", label: "Merk" },
  { kunci: "tipe", label: "Tipe" },
  { kunci: "tahun", label: "Tahun" },
  { kunci: "nomor_polisi", label: "Nomor polisi" },
  { kunci: "nomor_rangka", label: "Nomor rangka" },
  { kunci: "nama_pemilik", label: "Nama pemilik" },
];

type Isian = { benar: boolean; nilai: string };

/** Pemeriksaan manusia atas hasil baca STNK, satu baris per field.
 *
 *  Ditaruh sebelum kartu pemeriksaan validitas karena C5 dan C6 membandingkan angka di
 *  STNK dengan data polis. Kalau bacaannya sendiri salah, hasil kedua cek itu tidak bisa
 *  dipercaya, dan itu harus ketahuan lebih dulu. */
export default function ReviewStnk({
  klaim,
  bolehNilai,
  terkunci = false,
  saatBerubah,
}: {
  klaim: DetailKlaim;
  bolehNilai: boolean;
  /** Klaim yang sudah diputuskan tidak boleh diubah penilaiannya. */
  terkunci?: boolean;
  saatBerubah?: () => void;
}) {
  const stnk = klaim.stnk;
  // Backend yang belum dijalankan ulang setelah fitur ini masuk tidak mengirim kuncinya.
  const tersimpan = klaim.review_stnk ?? [];

  const [isian, setIsian] = useState<Record<string, Isian>>(() => {
    const awal: Record<string, Isian> = {};
    for (const f of FIELD) {
      const lama = tersimpan.find((r) => r.field === f.kunci);
      awal[f.kunci] = {
        benar: lama ? lama.benar : true,
        nilai: lama?.nilai_benar ?? "",
      };
    }
    return awal;
  });
  const [kirim, setKirim] = useState(false);
  const [pesan, setPesan] = useState("");
  const [galat, setGalat] = useState("");
  const [pratinjau, setPratinjau] = useState(false);
  const [tanyaBatal, setTanyaBatal] = useState(false);

  if (!stnk) return null;

  const dibaca: Record<string, string> = {
    merk: stnk.merk ?? "",
    tipe: stnk.tipe ?? "",
    tahun: stnk.tahun ? String(stnk.tahun) : "",
    nomor_polisi: stnk.nomor_polisi ?? "",
    nomor_rangka: stnk.nomor_rangka ?? "",
    nama_pemilik: stnk.nama_pemilik ?? "",
  };

  function ubah(kunci: string, baru: Partial<Isian>) {
    setIsian((lama) => ({ ...lama, [kunci]: { ...lama[kunci], ...baru } }));
  }

  async function simpan() {
    setKirim(true);
    setPesan("");
    setGalat("");
    try {
      const hasil = await kirimReviewStnk(
        klaim.id,
        FIELD.map((f) => ({
          field: f.kunci,
          benar: isian[f.kunci].benar,
          nilai_benar: isian[f.kunci].benar ? null : isian[f.kunci].nilai.trim(),
        })),
      );
      const salah = hasil.review_stnk.filter((r) => !r.benar).length;
      setPesan(
        salah === 0
          ? `${hasil.dinilai} field tersimpan, semuanya terbaca benar.`
          : `${hasil.dinilai} field tersimpan, ${salah} ditandai salah beserta nilai benarnya.`,
      );
      // Induknya perlu memuat ulang klaim, kalau tidak penanda sudah dinilai tidak ikut
      // berubah dan panelnya tidak pernah terkunci.
      saatBerubah?.();
    } catch (e) {
      setGalat((e as Error).message);
    } finally {
      setKirim(false);
    }
  }

  const sudahDinilai = tersimpan.length > 0;
  // Yang sudah disimpan dikunci supaya tidak berubah tanpa sengaja. Untuk mengubahnya,
  // penilaiannya dibatalkan lebih dulu, dan pembatalan itu tercatat di audit.
  const matikan = sudahDinilai || terkunci;

  async function batalkan() {
    setGalat("");
    setPesan("");
    setKirim(true);
    try {
      await batalkanReviewStnk(klaim.id);
      setTanyaBatal(false);
      saatBerubah?.();
    } catch (e) {
      setGalat((e as Error).message);
    } finally {
      setKirim(false);
    }
  }

  return (
    <div className="kartu">
      <h2>Hasil Deteksi pada STNK</h2>
      {stnk.urutan_foto !== null && (
        <div className="foto-stnk">
          <button type="button" onClick={() => setPratinjau(true)}>
            <img
              src={alamatFoto(klaim.id, stnk.urutan_foto, "stnk")}
              alt="Foto STNK yang dikirim surveyor"
            />
          </button>
        </div>
      )}

      <div className="gulir">
        <table>
          <thead>
            <tr>
              <th>Field</th>
              <th>Yang dibaca sistem</th>
              {bolehNilai && <th>Benar?</th>}
              {bolehNilai && <th>Nilai yang benar</th>}
              {!bolehNilai && <th>Hasil pemeriksaan</th>}
            </tr>
          </thead>
          <tbody>
            {FIELD.map((f) => {
              const lama = tersimpan.find((r) => r.field === f.kunci);
              return (
                <tr key={f.kunci}>
                  <td>{f.label}</td>
                  <td>{dibaca[f.kunci] || <span className="redup">tidak terbaca</span>}</td>
                  {bolehNilai ? (
                    <>
                      <td>
                        <select
                          value={isian[f.kunci].benar ? "benar" : "salah"}
                          disabled={matikan}
                          onChange={(e) =>
                            ubah(f.kunci, { benar: e.target.value === "benar" })
                          }
                        >
                          <option value="benar">Benar</option>
                          <option value="salah">Salah</option>
                        </select>
                      </td>
                      <td>
                        <input
                          value={isian[f.kunci].nilai}
                          disabled={matikan || isian[f.kunci].benar}
                          placeholder={isian[f.kunci].benar ? "" : "tulis yang benar"}
                          onChange={(e) => ubah(f.kunci, { nilai: e.target.value })}
                        />
                      </td>
                    </>
                  ) : (
                    <td>
                      {!lama ? (
                        <span className="redup">belum diperiksa</span>
                      ) : lama.benar ? (
                        <span className="lencana hijau">benar</span>
                      ) : (
                        <>
                          <span className="lencana merah">salah</span>
                          <span className="redup"> seharusnya {lama.nilai_benar}</span>
                        </>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {bolehNilai && (
        <div className="nilai-deteksi">
          {sudahDinilai && (
            <p className="redup">
              Hasil baca STNK klaim ini sudah diperiksa dan dikunci. Batalkan dulu kalau
              mau mengubahnya.
            </p>
          )}
          {sudahDinilai ? (
            <button
              className="sekunder"
              onClick={() => setTanyaBatal(true)}
              disabled={kirim || terkunci}
              title={
                terkunci
                  ? "Klaim ini sudah diputuskan. Batalkan keputusannya lebih dulu."
                  : undefined
              }
            >
              {kirim ? "Membatalkan..." : "Batalkan pemeriksaan STNK"}
            </button>
          ) : (
            <button onClick={simpan} disabled={kirim}>
              {kirim ? "Menyimpan..." : "Simpan pemeriksaan STNK"}
            </button>
          )}
          {pesan && <p className="berhasil">{pesan}</p>}
          {galat && <div className="galat">{galat}</div>}
        </div>
      )}

      {pratinjau && stnk.urutan_foto !== null && (
        <PratinjauFoto
          panel={[{
            judul: `Foto STNK klaim ${klaim.nomor_klaim}`,
            alamat: alamatFoto(klaim.id, stnk.urutan_foto, "stnk"),
            keterangan: "Bandingkan tiap isian di tabel dengan tulisan di foto ini",
          }]}
          saatTutup={() => setPratinjau(false)}
        />
      )}

      {/* Menghapus penilaian membuang jejak yang sudah masuk hitungan ketepatan model,
          jadi wajib lewat satu langkah tegas. */}
      {tanyaBatal && (
        <div
          className="tirai"
          role="dialog"
          aria-modal="true"
          aria-label="Konfirmasi pembatalan penilaian"
        >
          <div className="dialog">
            <h2>Batalkan pemeriksaan STNK klaim {klaim.nomor_klaim}?</h2>
            <p>
              Seluruh pemeriksaan field yang sudah tersimpan untuk klaim ini dihapus, dan angkanya ikut keluar dari ketepatan baca STNK di halaman Overview. Klaim ini tidak bisa diputuskan lagi sampai pemeriksaannya diisi ulang. Pembatalan ini tercatat di jejak audit atas nama akun Anda.
            </p>
            {galat && <div className="galat">{galat}</div>}
            <div className="tombol-dialog">
              <button
                type="button"
                className="sekunder"
                onClick={() => setTanyaBatal(false)}
                disabled={kirim}
              >
                Tidak jadi
              </button>
              <button
                type="button"
                className="bahaya"
                onClick={batalkan}
                disabled={kirim}
              >
                {kirim ? "Membatalkan..." : "Ya, batalkan"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
