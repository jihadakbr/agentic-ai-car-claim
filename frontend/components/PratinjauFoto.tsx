"use client";

import { useEffect, useRef, useState } from "react";
import IkonPanah from "@/components/IkonPanah";

// Zoom dan geser dipakai bersama kedua foto, bukan sendiri-sendiri. Yang dicari adjuster
// adalah beda antara foto asli dan hasil deteksi di titik yang sama, dan itu cuma terlihat
// kalau dua-duanya membesar ke arah yang sama.

const ZOOM_MIN = 1;
const ZOOM_MAX = 6;
const LANGKAH = 0.25;

type Panel = {
  judul: string;
  keterangan: string;
  /** Gambar biasa. Diabaikan kalau `isi` diisi. */
  alamat?: string;
  /** Isi sendiri, dipakai halaman Demo yang menggambar overlay sebagai SVG. */
  isi?: React.ReactNode;
};

function batas(nilai: number): number {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, nilai));
}

export default function PratinjauFoto({
  panel,
  saatTutup,
  alat,
  saatSebelum,
  saatSesudah,
}: {
  panel: Panel[];
  saatTutup: () => void;
  /** Pengatur tampilan, ditaruh di dalam pratinjau supaya layar utamanya tetap bersih. */
  alat?: React.ReactNode;
  /** Pindah antar gambar tanpa menutup pratinjau. Tombolnya baru muncul kalau diisi. */
  saatSebelum?: () => void;
  saatSesudah?: () => void;
}) {
  const [zoom, setZoom] = useState(1);
  const [geser, setGeser] = useState({ x: 0, y: 0 });
  const seret = useRef<{ x: number; y: number } | null>(null);
  const badan = useRef<HTMLDivElement>(null);

  function pulihkan() {
    setZoom(1);
    setGeser({ x: 0, y: 0 });
  }

  useEffect(() => {
    function tombol(e: KeyboardEvent) {
      if (e.key === "Escape") saatTutup();
      else if (e.key === "+" || e.key === "=") setZoom((z) => batas(z + LANGKAH));
      else if (e.key === "-") setZoom((z) => batas(z - LANGKAH));
      else if (e.key === "0") pulihkan();
      else if (e.key.startsWith("Arrow")) {
        // Ditahan supaya panah tidak ikut menggulir halaman atau memindah fokus tombol.
        e.preventDefault();
        if (e.key === "ArrowLeft") saatSebelum?.();
        else if (e.key === "ArrowRight") saatSesudah?.();
        else if (e.key === "ArrowUp") setZoom((z) => batas(z + LANGKAH));
        else if (e.key === "ArrowDown") setZoom((z) => batas(z - LANGKAH));
      }
    }
    window.addEventListener("keydown", tombol);

    // Halaman di belakang tidak boleh ikut tergulir saat pratinjau terbuka.
    const gulirAsli = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      window.removeEventListener("keydown", tombol);
      document.body.style.overflow = gulirAsli;
    };
  }, [saatTutup, saatSebelum, saatSesudah]);

  useEffect(() => {
    const kotak = badan.current;
    if (!kotak) return;
    // Listener dipasang sendiri karena React memasang wheel sebagai passive, dan yang
    // passive tidak boleh menahan gulir halaman.
    function roda(e: WheelEvent) {
      e.preventDefault();
      setZoom((z) => batas(z - Math.sign(e.deltaY) * LANGKAH));
    }
    kotak.addEventListener("wheel", roda, { passive: false });
    return () => kotak.removeEventListener("wheel", roda);
  }, []);

  function mulaiSeret(e: React.MouseEvent) {
    if (zoom === 1) return;
    seret.current = { x: e.clientX - geser.x, y: e.clientY - geser.y };
  }

  function seretkan(e: React.MouseEvent) {
    if (!seret.current) return;
    setGeser({ x: e.clientX - seret.current.x, y: e.clientY - seret.current.y });
  }

  return (
    <div className="pratinjau" role="dialog" aria-modal="true" aria-label="Pratinjau foto">
      <div className="pratinjau-kepala">
        <div className="pratinjau-alat">
          <button
            className="sekunder"
            onClick={() => setZoom((z) => batas(z - LANGKAH))}
            disabled={zoom <= ZOOM_MIN}
            aria-label="Perkecil"
          >
            −
          </button>
          <span className="pratinjau-persen">{Math.round(zoom * 100)}%</span>
          <button
            className="sekunder"
            onClick={() => setZoom((z) => batas(z + LANGKAH))}
            disabled={zoom >= ZOOM_MAX}
            aria-label="Perbesar"
          >
            +
          </button>
          <button
            className="sekunder"
            onClick={pulihkan}
            disabled={zoom === 1 && geser.x === 0 && geser.y === 0}
          >
            Ukuran asli
          </button>
        </div>

        <span className="pratinjau-bantuan">
          Gulir atau panah atas dan bawah untuk zoom, seret untuk menggeser, Esc untuk
          menutup
          {(saatSebelum || saatSesudah) && ", panah kiri dan kanan untuk berpindah gambar"}
        </span>

        {(saatSebelum || saatSesudah) && (
          <div className="pratinjau-alat">
            <button
              className="sekunder pindah-gambar"
              onClick={saatSebelum}
              disabled={!saatSebelum}
              aria-label="Gambar sebelumnya"
              title="Gambar sebelumnya"
            >
              <IkonPanah arah="kiri" />
            </button>
            <button
              className="sekunder pindah-gambar"
              onClick={saatSesudah}
              disabled={!saatSesudah}
              aria-label="Gambar berikutnya"
              title="Gambar berikutnya"
            >
              <IkonPanah arah="kanan" />
            </button>
          </div>
        )}

        <button className="sekunder" onClick={saatTutup}>
          Tutup
        </button>
      </div>

      <div
        className="pratinjau-badan"
        ref={badan}
        onMouseDown={mulaiSeret}
        onMouseMove={seretkan}
        onMouseUp={() => (seret.current = null)}
        onMouseLeave={() => (seret.current = null)}
        style={{ cursor: zoom > 1 ? "grab" : "default" }}
      >
        {panel.map((p) => (
          <figure key={p.judul}>
            <figcaption>{p.judul}</figcaption>
            <div className="pratinjau-bingkai">
              {p.isi ? (
                <div
                  className="pratinjau-isi"
                  style={{
                    transform: `translate(${geser.x}px, ${geser.y}px) scale(${zoom})`,
                  }}
                >
                  {p.isi}
                </div>
              ) : (
                <img
                  src={p.alamat}
                  alt={p.keterangan}
                  draggable={false}
                  style={{
                    transform: `translate(${geser.x}px, ${geser.y}px) scale(${zoom})`,
                  }}
                />
              )}
            </div>
          </figure>
        ))}
      </div>

      {alat && <div className="pratinjau-alat-bawah">{alat}</div>}
    </div>
  );
}
