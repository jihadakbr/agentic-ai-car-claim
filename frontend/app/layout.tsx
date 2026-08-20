import type { Metadata } from "next";
import { PenyimpanFormulir } from "@/components/FormulirKlaim";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agentic AI Car Claim",
  description: "Penilaian klaim asuransi mobil dari foto surveyor",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id">
      <body>
        <PenyimpanFormulir>{children}</PenyimpanFormulir>
      </body>
    </html>
  );
}
