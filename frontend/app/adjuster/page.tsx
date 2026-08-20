"use client";

import { useEffect, useState } from "react";
import Kerangka from "@/components/Kerangka";
import TabelKlaim from "@/components/TabelKlaim";
import { ambilDaftarKlaim, type RingkasanKlaim } from "@/lib/api";
import { butuhIzin, IZIN } from "@/lib/auth";

export default function DaftarKlaimAdjuster() {
  const [klaim, setKlaim] = useState<RingkasanKlaim[]>([]);
  const [galat, setGalat] = useState("");
  const [memuat, setMemuat] = useState(true);

  function muat() {
    ambilDaftarKlaim()
      .then(setKlaim)
      .catch((e: Error) => setGalat(e.message))
      .finally(() => setMemuat(false));
  }

  useEffect(muat, []);

  return (
    <Kerangka
      judul="Daftar Klaim"
      keterangan="Sistem hanya merekomendasikan, keputusan akhir ada di tangan adjuster"
      butuh={butuhIzin(IZIN.klaimLihat)}
    >
      <div className="kartu">
        <h2>Klaim menunggu review</h2>
        <p className="petunjuk">
          Klik "NOMOR KLAIM" untuk melakukan review atau melihat detail keputusan.
        </p>

        {galat && <div className="galat">{galat}</div>}
        {memuat && <p className="redup">Memuat...</p>}
        {!memuat && !galat && klaim.length === 0 && (
          <p className="redup">Belum ada klaim yang masuk.</p>
        )}

        {klaim.length > 0 && <TabelKlaim klaim={klaim} saatHapus={muat} />}
      </div>
    </Kerangka>
  );
}
