// Grafik digambar sebagai SVG langsung, tanpa pustaka grafik, karena untuk beberapa
// bentuk sederhana pustaka tambahan cuma memperbesar unduhan tanpa memberi apa pun.
//
// Warnanya bukan pilihan selera. Tiga warna status di bawah sudah diperiksa dengan
// pemeriksa palet: jarak antar warna cukup jauh untuk mata normal maupun mata yang sulit
// membedakan warna. Percobaan pertama memakai amber dan merah dari tema aplikasi, dan
// pasangan itu gagal karena terlalu mirip. Kuning `#eda100` kontrasnya di bawah 3 banding 1
// terhadap latar putih, jadi tiap potongan wajib punya label angka, bukan warna saja.

export type Potongan = { label: string; nilai: number; warna: string };

// Dua kategori identitas, bukan status, jadi memakai warna kategori yang tervalidasi.
export const WARNA_REKOMENDASI: Record<string, string> = {
  repair: "#2a78d6",
  total_loss: "#eb6834",
};

export const WARNA_VERDICT: Record<string, string> = {
  valid: "#008300",
  perlu_review: "#eda100",
  invalid: "#e34948",
};

// Urutan tetap tujuh warna kategori, dipakai berurutan dan tidak pernah diputar ulang.
// Sudah lolos pemeriksa palet: pasangan terdekat ΔE 9.1 untuk mata protan, 19.6 untuk
// mata normal. Tiga di antaranya kontrasnya di bawah 3 banding 1 terhadap putih, jadi tiap
// potongan wajib punya label angka.
export const WARNA_KATEGORI = [
  "#2a78d6",
  "#eb6834",
  "#1baf7a",
  "#eda100",
  "#e87ba4",
  "#008300",
  "#4a3aa7",
];

// Palet yang sama, urutan berbeda, dipakai kartu pemeriksaan validitas yang gagal. Kartu
// itu berdiri sebaris dengan dua donat lain, dan kalau warnanya mulai dari biru dan jingga
// juga, ketiganya terbaca seperti memecah angka yang sama.
export const WARNA_CEK = [
  "#4a3aa7",
  "#1baf7a",
  "#e87ba4",
  "#eda100",
  "#2a78d6",
  "#eb6834",
  "#008300",
];

const JARI = 35;
const KELILING = 2 * Math.PI * JARI;
const TEBAL = 18;
const CELAH = 1.5;

/** Diagram donat untuk perbandingan bagian terhadap keseluruhan.
 *
 *  Lubang di tengahnya dipakai menampilkan totalnya, sekaligus membuat potongan dibaca
 *  sebagai panjang busur, bukan sebagai luas juring yang lebih sulit dibandingkan. */
export function Donat({
  judul,
  potongan,
  satuan = "klaim",
}: {
  judul: string;
  potongan: Potongan[];
  satuan?: string;
}) {
  const isi = potongan.filter((p) => p.nilai > 0);
  const total = isi.reduce((a, p) => a + p.nilai, 0);

  if (total === 0) {
    return (
      <div>
        <h3 className="judul-grafik">{judul}</h3>
        <p className="redup">Belum ada data.</p>
      </div>
    );
  }

  let mulai = 0;

  return (
    <div>
      <h3 className="judul-grafik">{judul}</h3>

      <div className="donat">
        <svg
          viewBox="0 0 100 100"
          role="img"
          aria-label={`${judul}: ${isi.map((p) => `${p.label} ${p.nilai}`).join(", ")}`}
        >
          {/* Diputar supaya potongan pertama mulai dari atas, bukan dari kanan. */}
          <g transform="rotate(-90 50 50)">
            {isi.map((p) => {
              const busur = (p.nilai / total) * KELILING;
              const celah = isi.length > 1 ? CELAH : 0;
              const potong = (
                <circle
                  key={p.label}
                  cx={50}
                  cy={50}
                  r={JARI}
                  fill="none"
                  stroke={p.warna}
                  strokeWidth={TEBAL}
                  strokeDasharray={`${Math.max(0, busur - celah)} ${KELILING}`}
                  strokeDashoffset={-mulai}
                >
                  <title>{`${p.label}: ${p.nilai} ${satuan}`}</title>
                </circle>
              );
              mulai += busur;
              return potong;
            })}
          </g>
          <text x="50" y="48" className="donat-angka">
            {total}
          </text>
          <text x="50" y="60" className="donat-satuan">
            {satuan}
          </text>
        </svg>

        {/* Setiap potongan diberi angka, bukan cuma warna. Ini yang membuat grafik tetap
            terbaca oleh yang sulit membedakan warna, dan saat dicetak hitam putih. */}
        <ul className="keterangan-grafik">
          {isi.map((p) => (
            <li key={p.label}>
              <span className="titik" style={{ background: p.warna }} />
              {p.label}
              <strong>{p.nilai}</strong>
              <span className="redup">
                {Math.round((p.nilai / total) * 100)}%
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/** Angka utama. Untuk satu nilai, angka besar lebih terbaca daripada grafik apa pun. */
export function KartuAngka({
  label,
  nilai,
  keterangan,
}: {
  label: string;
  nilai: string;
  keterangan?: string;
}) {
  return (
    <div className="kartu-angka">
      <div className="label">{label}</div>
      <div className="nilai">{nilai}</div>
      {keterangan && <div className="redup">{keterangan}</div>}
    </div>
  );
}
