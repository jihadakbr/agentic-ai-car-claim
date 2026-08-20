"use client";

import { use, useEffect, useState } from "react";
import FotoDeteksi from "@/components/FotoDeteksi";
import FotoPelengkap from "@/components/FotoPelengkap";
import HargaPasarAI, { butuhPengesahan } from "@/components/HargaPasarAI";
import HasilKlaim from "@/components/HasilKlaim";
import Kerangka from "@/components/Kerangka";
import {
  alamatSuratPdf,
  ambilKlaim,
  batalkanKeputusan,
  kirimKeputusan,
  type Biaya,
  type DetailKlaim,
} from "@/lib/api";
import { butuhIzin, IZIN, punyaIzin } from "@/lib/auth";
import { rupiah, waktu } from "@/lib/format";

const LABEL_KEPUTUSAN: Record<string, string> = {
  setuju: "Disetujui",
  tolak: "Ditolak",
  revisi: "Diminta revisi",
};

const PILIHAN = [
  { nilai: "setuju", label: "Setujui" },
  { nilai: "tolak", label: "Tolak" },
  { nilai: "revisi", label: "Minta revisi" },
];

export default function RincianKlaim({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [klaim, setKlaim] = useState<DetailKlaim | null>(null);
  const [catatan, setCatatan] = useState("");
  const [galat, setGalat] = useState("");
  const [sibuk, setSibuk] = useState(false);
  const [tanyaBatal, setTanyaBatal] = useState(false);

  // Hak dibaca sekali setelah komponen terpasang. Membacanya saat render pertama membuat
  // hasil server dan hasil browser berbeda, dan React menolak itu.
  const [bolehPutuskan, setBolehPutuskan] = useState(false);
  useEffect(() => setBolehPutuskan(punyaIzin(IZIN.klaimPutuskan)), []);

  useEffect(() => {
    ambilKlaim(id)
      .then(setKlaim)
      .catch((e: Error) => setGalat(e.message));
  }, [id]);

  async function putuskan(keputusan: string) {
    setGalat("");
    setSibuk(true);
    try {
      await kirimKeputusan(id, keputusan, catatan.trim());
      setKlaim(await ambilKlaim(id));
    } catch (e) {
      setGalat((e as Error).message);
    } finally {
      setSibuk(false);
    }
  }

  async function batalkan() {
    setGalat("");
    setSibuk(true);
    try {
      await batalkanKeputusan(id);
      setCatatan("");
      setTanyaBatal(false);
      setKlaim(await ambilKlaim(id));
    } catch (e) {
      setGalat((e as Error).message);
    } finally {
      setSibuk(false);
    }
  }

  const sudahDiputuskan = (klaim?.keputusan.length ?? 0) > 0;

  // Harga bekas menentukan total loss dan besar penawaran beli. Selama harganya belum
  // disahkan manusia, tombol Setujui mati. Server menolak juga, jadi ini bukan satu-satunya
  // penjagaan, cuma supaya adjuster tidak menekan tombol yang pasti ditolak.
  const hargaBelumSah = butuhPengesahan(klaim?.biaya ?? null);

  // Temuan deteksi dan hasil baca STNK wajib diperiksa sebelum klaim diputuskan, termasuk
  // sebelum ditolak. Server menolak juga, jadi ini bukan satu-satunya penjagaan.
  const reviewKurang = klaim?.review_kurang ?? null;

  async function muatUlang() {
    setGalat("");
    try {
      setKlaim(await ambilKlaim(id));
    } catch (e) {
      setGalat((e as Error).message);
    }
  }

  function perbaruiBiaya(baru: Biaya) {
    setKlaim((lama) => (lama ? { ...lama, biaya: baru } : lama));
  }

  return (
    <Kerangka
      judul={klaim ? `Klaim ${klaim.nomor_klaim}` : "Rincian Klaim"}
      keterangan={klaim?.kendaraan ?? undefined}
      butuh={butuhIzin(IZIN.klaimLihat)}
    >
      {galat && !klaim && <div className="galat">{galat}</div>}
      {!klaim && !galat && <p className="redup">Memuat...</p>}

      {klaim && (
        <>
          <FotoDeteksi
            klaim={klaim}
            untuk="adjuster"
            terkunci={sudahDiputuskan}
            saatBerubah={muatUlang}
          />

          <FotoPelengkap klaim={klaim} />

          {klaim.biaya &&
            klaim.biaya.harga_pasar_sumber !== "database" &&
            klaim.biaya.harga_pasar_sumber !== "database_polis" && (
              <HargaPasarAI
                klaimId={id}
                biaya={klaim.biaya}
                saatDisahkan={perbaruiBiaya}
                terkunci={sudahDiputuskan}
              />
            )}

          <HasilKlaim
            klaim={klaim}
            terkunci={sudahDiputuskan}
            saatBerubah={muatUlang}
          />

          {sudahDiputuskan ? (
            <div className="kartu">
              <div className="kepala-kartu">
                <h2>Keputusan</h2>
                {/* Tautan biasa, bukan fetch lalu blob, supaya nama berkas unduhannya
                    ditentukan server. Tombolnya hanya ada kalau suratnya memang terbit,
                    jadi klaim yang ditolak tidak menawarkan dokumen yang tidak ada. */}
                {klaim.surat && (
                  <div className="aksi-kartu">
                    <a
                      className="tombol sekunder"
                      href={alamatSuratPdf(klaim.id)}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Lihat PDF
                    </a>
                    <a className="tombol sekunder" href={alamatSuratPdf(klaim.id, true)}>
                      Unduh PDF
                    </a>
                  </div>
                )}
              </div>
              {klaim.keputusan.map((k, i) => (
                <p key={i} style={{ margin: "0 0 8px" }}>
                  <strong>{LABEL_KEPUTUSAN[k.keputusan] ?? k.keputusan}</strong> oleh{" "}
                  {k.oleh} pada: {waktu(k.waktu)}
                  {k.catatan && (
                    <span className="redup"> &mdash; {k.catatan}</span>
                  )}
                </p>
              ))}
              {klaim.surat && (
                <p className="redup">
                  {klaim.surat.jenis === "spk"
                    ? `Surat perintah kerja ${klaim.surat.nomor} terbit ke ${klaim.surat.tujuan}, senilai ${rupiah(klaim.surat.nilai)}.`
                    : `Penawaran beli kendaraan terbit ke ${klaim.surat.tujuan} senilai ${rupiah(klaim.surat.nilai)}.`}
                </p>
              )}

              {galat && <div className="galat">{galat}</div>}

              {bolehPutuskan && (
                <button
                  type="button"
                  className="sekunder"
                  style={{ marginTop: 8 }}
                  disabled={sibuk}
                  onClick={() => setTanyaBatal(true)}
                >
                  Batalkan keputusan
                </button>
              )}
            </div>
          ) : (
            <div className="kartu">
              <h2>Keputusan Adjuster</h2>

              {galat && <div className="galat">{galat}</div>}

              {reviewKurang && (
                <div className="peringatan">{reviewKurang}</div>
              )}

              {hargaBelumSah && (
                <div className="peringatan">
                  Harga pasar bekas belum disahkan. Periksa kartu harga di atas
                  lebih dulu, baru klaim ini bisa disetujui. Menolak dan meminta
                  revisi tetap bisa.
                </div>
              )}

              <div style={{ marginBottom: 16 }}>
                <label htmlFor="catatan">Catatan</label>
                <p className="redup">
                  Wajib diisi kalau Anda meminta revisi. Catatan inilah yang dibaca
                  surveyor saat mengambil ulang fotonya.
                </p>
                <textarea
                  id="catatan"
                  value={catatan}
                  onChange={(e) => setCatatan(e.target.value)}
                />
              </div>

              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {PILIHAN.map((p) => (
                  <button
                    key={p.nilai}
                    className={p.nilai === "setuju" ? "" : "sekunder"}
                    disabled={
                      sibuk ||
                      !!reviewKurang ||
                      (p.nilai === "setuju" && hargaBelumSah) ||
                      (p.nilai === "revisi" && !catatan.trim())
                    }
                    onClick={() => putuskan(p.nilai)}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          <p className="redup">
            Pemakaian token klaim ini: {klaim.token.masuk} masuk,{" "}
            {klaim.token.keluar} keluar.
          </p>

          {/* Pembatalan menarik surat yang sudah dikirim ke bengkel atau tertanggung, jadi
              wajib lewat satu langkah tegas. */}
          {tanyaBatal && (
            <div
              className="tirai"
              role="dialog"
              aria-modal="true"
              aria-label="Konfirmasi pembatalan keputusan"
            >
              <div className="dialog">
                <h2>Batalkan keputusan klaim {klaim.nomor_klaim}?</h2>
                <p>
                  Surat perintah kerja atau penawaran beli yang sudah terbit ikut ditarik,
                  dan klaim kembali ke antrean untuk diputuskan ulang. Pembatalan ini
                  tercatat di jejak audit atas nama akun Anda.
                </p>
                {galat && <div className="galat">{galat}</div>}
                <div className="tombol-dialog">
                  <button
                    type="button"
                    className="sekunder"
                    onClick={() => setTanyaBatal(false)}
                    disabled={sibuk}
                  >
                    Tidak jadi
                  </button>
                  <button
                    type="button"
                    className="bahaya"
                    onClick={batalkan}
                    disabled={sibuk}
                  >
                    {sibuk ? "Membatalkan..." : "Ya, batalkan"}
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </Kerangka>
  );
}
