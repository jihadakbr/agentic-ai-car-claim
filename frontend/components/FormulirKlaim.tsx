"use client";

// Isian formulir klaim disimpan di sini, bukan di dalam halamannya.
//
// Pindah menu membongkar komponen halaman, jadi isian yang ditaruh di sana ikut hilang.
// Penyimpan ini dipasang di layout yang tidak ikut dibongkar saat pindah menu, sehingga
// nomor polis dan foto yang sudah dipilih masih ada saat surveyor kembali.
//
// Foto sengaja disimpan sebagai objek File di memori, bukan di sessionStorage. Berkas
// tidak bisa diubah jadi teks tanpa disalin seluruh isinya, dan browser memang melarang
// mengisi kotak pilih berkas dari kode demi keamanan. Konsekuensinya foto tetap hilang
// kalau halamannya benar-benar dimuat ulang, dan itu dijelaskan di layar.

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { Polis } from "@/lib/api";
import { ambilSesi } from "@/lib/auth";

const KUNCI_POLIS = "formulir-polis";

type IsiFormulir = {
  nomorPolis: string;
  setNomorPolis: (v: string) => void;
  polis: Polis | null;
  setPolis: (v: Polis | null) => void;
  foto: File[];
  setFoto: (v: File[]) => void;
  fotoStnk: File | null;
  setFotoStnk: (v: File | null) => void;
  fotoPelengkap: File[];
  setFotoPelengkap: (v: File[]) => void;
};

const Konteks = createContext<IsiFormulir | null>(null);

export function PenyimpanFormulir({ children }: { children: React.ReactNode }) {
  const [nomorPolis, setNomorPolis] = useState("");
  const [polis, setPolis] = useState<Polis | null>(null);
  const [foto, setFoto] = useState<File[]>([]);
  const [fotoStnk, setFotoStnk] = useState<File | null>(null);
  const [fotoPelengkap, setFotoPelengkap] = useState<File[]>([]);

  // Nomor polis ikut disimpan di sessionStorage supaya bertahan juga saat halaman dimuat
  // ulang, bukan cuma saat pindah menu. Ini teks pendek, jadi murah.
  const pengguna = ambilSesi()?.username ?? "";
  const [dimuat, setDimuat] = useState(false);

  useEffect(() => {
    if (typeof sessionStorage === "undefined") return;
    setNomorPolis(sessionStorage.getItem(`${KUNCI_POLIS}:${pengguna}`) ?? "");
    setDimuat(true);
  }, [pengguna]);

  useEffect(() => {
    if (!dimuat) return;
    sessionStorage.setItem(`${KUNCI_POLIS}:${pengguna}`, nomorPolis);
  }, [dimuat, pengguna, nomorPolis]);

  const isi = useMemo(
    () => ({
      nomorPolis, setNomorPolis,
      polis, setPolis,
      foto, setFoto,
      fotoStnk, setFotoStnk,
      fotoPelengkap, setFotoPelengkap,
    }),
    [nomorPolis, polis, foto, fotoStnk, fotoPelengkap],
  );

  return <Konteks.Provider value={isi}>{children}</Konteks.Provider>;
}

export function useFormulirKlaim(): IsiFormulir {
  const isi = useContext(Konteks);
  if (!isi) throw new Error("useFormulirKlaim dipakai di luar PenyimpanFormulir");
  return isi;
}
