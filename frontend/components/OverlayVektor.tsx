"use client";

// Overlay digambar sebagai SVG di atas foto, bukan dibakar jadi gambar seperti di layar
// adjuster. Bedanya menentukan: bentuk yang masih berupa vektor bisa diganti warnanya,
// ditipiskan garisnya, dan dimatikan satu per satu tanpa menjalankan model lagi.

export type Bentuk = {
  kelas: string;
  keyakinan: number;
  titik: [number, number][];
};

export type Setelan = {
  tampilPart: boolean;
  tampilDamage: boolean;
  warnaPart: string;
  warnaDamage: string;
  tebal: number;
  kepekatan: number;
  tampilLabel: boolean;
  kelasMati: string[];
};

export const SETELAN_AWAL: Setelan = {
  tampilPart: true,
  tampilDamage: true,
  warnaPart: "#2563eb",
  warnaDamage: "#dc2626",
  // Garis tipis dan isian bening secara bawaan. Isian 35% seperti di layar adjuster
  // membuat mask kerusakan dan mask bagian saling menutupi, dan itu justru yang bikin
  // susah menilai deteksinya benar atau tidak.
  tebal: 1.5,
  kepekatan: 0,
  tampilLabel: true,
  kelasMati: [],
};

/** Setelan disimpan supaya tidak perlu diatur ulang tiap kali pindah foto atau halaman. */
export const KUNCI_SETELAN = "setelan_overlay";

/** Penanda satu bentuk. Berbasis urutan, jadi cuma berlaku untuk satu foto. */
export function idBentuk(lapisan: "part" | "damage", urutan: number): string {
  return `${lapisan}:${urutan}`;
}

/** Nomor tiap bentuk di antara yang sekelas, misal Broken part pertama, kedua, ketiga.
 *
 *  Kelas yang cuma punya satu bentuk tidak dinomori, karena nomor di situ tidak
 *  membedakan apa pun dan malah menambah bacaan.
 */
export function nomorSekelas(daftar: Bentuk[]): (number | null)[] {
  const jumlah = new Map<string, number>();
  for (const b of daftar) jumlah.set(b.kelas, (jumlah.get(b.kelas) ?? 0) + 1);

  const berjalan = new Map<string, number>();
  return daftar.map((b) => {
    if ((jumlah.get(b.kelas) ?? 0) < 2) return null;
    const n = (berjalan.get(b.kelas) ?? 0) + 1;
    berjalan.set(b.kelas, n);
    return n;
  });
}

/** Nama kelas beserta nomor instance-nya, dipakai label gambar maupun baris tabel. */
export function namaSekelas(kelas: string, nomor: number | null): string {
  return nomor === null ? kelas : `${kelas} (${nomor})`;
}

function jalur(titik: [number, number][], lebar: number, tinggi: number): string {
  return titik.map(([x, y]) => `${(x * lebar).toFixed(1)},${(y * tinggi).toFixed(1)}`).join(" ");
}

/** Titik paling kiri-atas, dipakai menaruh label supaya tidak menutupi tengah bentuknya. */
function sudut(titik: [number, number][], lebar: number, tinggi: number) {
  const x = Math.min(...titik.map((t) => t[0])) * lebar;
  const y = Math.min(...titik.map((t) => t[1])) * tinggi;
  return { x, y };
}

type Isi = { bentuk: Bentuk; id: string; nomor: number | null };

function Lapisan({
  isi,
  warna,
  setelan,
  lebar,
  tinggi,
  sorot,
}: {
  isi: Isi[];
  warna: string;
  setelan: Setelan;
  lebar: number;
  tinggi: number;
  sorot: string | null;
}) {
  return (
    <>
      {isi.map(({ bentuk, id }) => {
        const disorot = sorot === id;
        return (
          <polygon
            key={id}
            points={jalur(bentuk.titik, lebar, tinggi)}
            fill={warna}
            fillOpacity={disorot ? Math.max(0.25, setelan.kepekatan) : setelan.kepekatan}
            stroke={warna}
            strokeWidth={setelan.tebal}
            strokeLinejoin="round"
            // Bentuk lain diredupkan saat ada yang disorot, supaya yang sedang ditunjuk
            // langsung terlihat tanpa perlu dicari.
            opacity={sorot && !disorot ? 0.25 : 1}
          />
        );
      })}
      {setelan.tampilLabel &&
        isi.map(({ bentuk, id, nomor }) => {
          const { x, y } = sudut(bentuk.titik, lebar, tinggi);
          const nama = namaSekelas(bentuk.kelas, nomor);
          const teks = `${nama} ${Math.round(bentuk.keyakinan * 100)}%`;
          return (
            <g
              key={`l${id}`}
              transform={`translate(${x + 2}, ${Math.max(11, y - 3)})`}
              opacity={sorot && sorot !== id ? 0.25 : 1}
            >
              <rect x={0} y={-9} width={teks.length * 5.6 + 6} height={12} fill={warna} rx={2} />
              <text x={3} y={0} fontSize={9} fill="#fff">
                {teks}
              </text>
            </g>
          );
        })}
    </>
  );
}

export default function OverlayVektor({
  alamat,
  lebar,
  tinggi,
  part,
  damage,
  setelan,
  instansiMati = [],
  sorot = null,
}: {
  alamat: string;
  lebar: number;
  tinggi: number;
  part: Bentuk[];
  damage: Bentuk[];
  setelan: Setelan;
  /** Bentuk yang disembunyikan satu per satu. Berbasis urutan, jadi hanya untuk foto ini. */
  instansiMati?: string[];
  /** Bentuk yang sedang ditunjuk dari daftar, ditebalkan dan yang lain diredupkan. */
  sorot?: string | null;
}) {
  const kelasMati = new Set(setelan.kelasMati);
  const mati = new Set(instansiMati);

  function pilih(daftar: Bentuk[], lapisan: "part" | "damage", tampil: boolean): Isi[] {
    if (!tampil) return [];
    const nomor = nomorSekelas(daftar);
    return daftar
      .map((bentuk, i) => ({ bentuk, id: idBentuk(lapisan, i), nomor: nomor[i] }))
      .filter(({ bentuk, id }) => !kelasMati.has(bentuk.kelas) && !mati.has(id));
  }

  return (
    <svg
      viewBox={`0 0 ${lebar} ${tinggi}`}
      width={lebar}
      height={tinggi}
      className="overlay-vektor"
      preserveAspectRatio="xMidYMid meet"
    >
      <image href={alamat} x={0} y={0} width={lebar} height={tinggi} />
      {/* Kerusakan digambar terakhir supaya garisnya tetap terlihat di atas garis bagian. */}
      <Lapisan
        isi={pilih(part, "part", setelan.tampilPart)}
        warna={setelan.warnaPart}
        setelan={setelan}
        lebar={lebar}
        tinggi={tinggi}
        sorot={sorot}
      />
      <Lapisan
        isi={pilih(damage, "damage", setelan.tampilDamage)}
        warna={setelan.warnaDamage}
        setelan={setelan}
        lebar={lebar}
        tinggi={tinggi}
        sorot={sorot}
      />
    </svg>
  );
}
