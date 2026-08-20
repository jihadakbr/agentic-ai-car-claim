"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { masuk } from "@/lib/api";
import { halamanAwal, simpanSesi } from "@/lib/auth";

export default function HalamanMasuk() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [galat, setGalat] = useState("");
  const [sibuk, setSibuk] = useState(false);
  const router = useRouter();

  async function kirim(e: React.FormEvent) {
    e.preventDefault();
    setGalat("");
    setSibuk(true);
    try {
      const sesi = await masuk(username.trim(), password);
      simpanSesi(sesi);
      router.replace(halamanAwal(sesi));
    } catch (err) {
      setGalat((err as Error).message);
      setSibuk(false);
    }
  }

  return (
    <div className="halaman-masuk">
      <form className="kotak-masuk" onSubmit={kirim}>
        <h1>Agentic AI Car Claim</h1>
        <p className="petunjuk">Masuk untuk mengajukan atau memeriksa klaim.</p>

        {galat && <div className="galat">{galat}</div>}

        <div className="isian">
          <label htmlFor="username">Username</label>
          <input
            id="username"
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>

        <div className="isian">
          <label htmlFor="password">Kata sandi</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        <button type="submit" disabled={sibuk || !username.trim() || !password}>
          {sibuk ? "Memeriksa..." : "Masuk"}
        </button>
      </form>
    </div>
  );
}
