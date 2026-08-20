"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import DialogKirimUlang from "@/components/DialogKirimUlang";
import Kerangka from "@/components/Kerangka";
import { ambilKirimanSaya, type KirimanSaya } from "@/lib/api";
import { ambilSesi, butuhIzin, IZIN, punyaIzin } from "@/lib/auth";
import { labelStatus, waktu, warnaStatus } from "@/lib/format";

const STATUS_MENUNGGU = "menunggu_foto_tambahan";
const JEDA_MS = 3000;
// Sekitar dua menit. Kalau pipelinenya belum selesai juga, menanya terus tidak menolong,
// dan lebih baik halamannya dibuka ulang nanti.
const BATAS_TANYA = 40;

export default function HalamanKlaimSaya() {
  const [kiriman, setKiriman] = useState<KirimanSaya[] | null>(null);
  const [galat, setGalat] = useState("");
  const [dialogUntuk, setDialogUntuk] = useState<string | null>(null);
  const percobaan = useRef(0);

  const muat = useCallback(() => {
    ambilKirimanSaya()
      .then((isi) => {
        setKiriman(isi);
        setGalat("");
      })
      .catch((e: Error) => setGalat(e.message));
  }, []);

  useEffect(muat, [muat]);

  // Pipeline berjalan di server setelah kiriman diterima, jadi daftarnya ditanya ulang
  // selama masih ada yang diproses. Berhenti sendiri begitu tidak ada lagi yang menggantung.
  useEffect(() => {
    const diproses = kiriman?.some((k) => k.status === "diproses") ?? false;
    if (!diproses || percobaan.current >= BATAS_TANYA) return;

    const jam = setTimeout(() => {
      percobaan.current += 1;
      muat();
    }, JEDA_MS);
    return () => clearTimeout(jam);
  }, [kiriman, muat]);

  const dialog = kiriman?.find((k) => k.id === dialogUntuk);

  // Yang berhak melihat seluruh klaim mendapat daftar dari semua pengirim, jadi kolom
  // pengirimnya baru berguna di situ. Untuk surveyor, kolom itu selalu berisi namanya
  // sendiri dan cuma memakan tempat.
  const semuaPengirim = punyaIzin(IZIN.klaimLihat);
  const sayaSiapa = ambilSesi()?.username ?? "";

  function sesudahKirim() {
    percobaan.current = 0;
    setDialogUntuk(null);
    muat();
  }

  return (
    <Kerangka
      judul="Klaim Saya"
      keterangan="Status klaim yang Anda kirim, beserta foto tambahan yang masih diminta oleh AI"
      butuh={butuhIzin(IZIN.klaimLacak)}
    >
      {galat && <div className="galat">{galat}</div>}
      {!kiriman && !galat && <p className="redup">Memuat...</p>}

      {kiriman?.length === 0 && (
        <div className="kartu">
          <p className="redup">
            {semuaPengirim
              ? "Belum ada klaim sama sekali di sistem."
              : "Belum ada klaim yang Anda kirim. Buka menu Ajukan Klaim untuk mengirim yang pertama."}
          </p>
        </div>
      )}

      {kiriman && kiriman.length > 0 && (
        <div className="kartu">
          <div className="gulir">
            <table>
              <thead>
                <tr>
                  <th>Nomor klaim</th>
                  {semuaPengirim && <th>Pengirim</th>}
                  <th>Polis</th>
                  <th>Kendaraan</th>
                  <th>Tanggal kirim</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {kiriman.map((k) => {
                  const belum = k.permintaan_foto.filter((p) => !p.dipenuhi);
                  return (
                    <tr key={k.id}>
                      <td>
                        <strong>{k.nomor_klaim}</strong>
                        {belum.map((p, i) => (
                          <p key={i} className="minta-foto">
                            {p.permintaan}
                            {p.alasan ? `. ${p.alasan}` : ""}
                          </p>
                        ))}
                        {k.status === "gagal" && (
                          <p className="minta-foto">
                            Pemrosesan gagal di server. Kirim ulang klaim ini, dan
                            kalau tetap gagal beri tahu tim teknis.
                          </p>
                        )}
                      </td>
                      {semuaPengirim && (
                        <td>
                          {k.nama_surveyor || k.surveyor || "-"}
                          {k.surveyor === sayaSiapa && (
                            <span className="redup"> (Anda)</span>
                          )}
                          {k.nama_surveyor && (
                            <div className="redup">{k.surveyor}</div>
                          )}
                        </td>
                      )}
                      <td>{k.nomor_polis ?? "-"}</td>
                      <td>{k.kendaraan ?? "-"}</td>
                      <td>{k.dibuat ? waktu(k.dibuat) : "-"}</td>
                      <td>
                        <span className={`lencana ${warnaStatus(k.status)}`}>
                          {labelStatus(k.status)}
                        </span>
                      </td>
                      <td>
                        {k.status === STATUS_MENUNGGU && (
                          <button type="button" onClick={() => setDialogUntuk(k.id)}>
                            Upload Foto
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {dialog && (
        <DialogKirimUlang
          kiriman={dialog}
          tutup={() => setDialogUntuk(null)}
          saatTerkirim={sesudahKirim}
        />
      )}
    </Kerangka>
  );
}
