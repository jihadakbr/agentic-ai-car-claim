// Panah digambar sebagai SVG, bukan huruf seperti ‹ dan ›, karena metrik huruf itu berbeda
// tiap font dan hasilnya tidak pernah benar-benar di tengah tombol.

export default function IkonPanah({ arah }: { arah: "kiri" | "kanan" }) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
      <path
        d={arah === "kiri" ? "M15 5l-7 7 7 7" : "M9 5l7 7-7 7"}
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
