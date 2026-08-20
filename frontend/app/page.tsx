"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { ambilSesi, halamanAwal } from "@/lib/auth";

/** Alamat akar tidak punya isi sendiri, cuma mengantar ke halaman awal sesuai peran. */
export default function Pengalih() {
  const router = useRouter();

  useEffect(() => {
    const sesi = ambilSesi();
    router.replace(sesi ? halamanAwal(sesi) : "/login");
  }, [router]);

  return null;
}
