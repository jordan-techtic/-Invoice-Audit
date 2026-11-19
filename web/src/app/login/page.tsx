"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { devAutoLogin, devLoginEmail, devLoginPassword } from "@/lib/auth-dev";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(devAutoLogin);

  useEffect(() => {
    if (!devAutoLogin) return;
    let live = true;
    (async () => {
      try {
        await api.login(devLoginEmail, devLoginPassword);
        if (live) router.replace("/clients");
      } catch (err) {
        if (!live) return;
        setError(err instanceof Error ? err.message : "Auto sign-in failed. Is the API running?");
        setBusy(false);
      }
    })();
    return () => { live = false; };
  }, [router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(email.trim(), password);
      router.replace("/clients");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed. Check your details and try again.");
      setBusy(false);
    }
  }

  if (devAutoLogin && busy && !error) {
    return (
      <main className="grid min-h-screen place-items-center px-6 py-10">
        <p className="text-muted" role="status">Signing in…</p>
      </main>
    );
  }

  return (
    <main className="grid min-h-screen place-items-center px-6 py-10">
      <div className="w-full max-w-[420px]">
        <p className="text-lg font-bold text-primary">Techtic Invoice Audit</p>
        <h1 className="mt-6 text-xl">Sign in</h1>
        <p className="mt-1 text-muted">Use the email and password your Techtic contact set up.</p>
        <form onSubmit={submit} className="mt-8 space-y-5 border-t-4 border-primary bg-surface p-6" noValidate>
          <div>
            <label htmlFor="email" className="mb-1 block text-base font-medium">Email</label>
            <input id="email" type="email" autoComplete="username" required className="field" value={email}
              onChange={(e) => setEmail(e.target.value)} aria-invalid={!!error} aria-describedby={error ? "login-error" : undefined} />
          </div>
          <div>
            <label htmlFor="password" className="mb-1 block text-base font-medium">Password</label>
            <input id="password" type="password" autoComplete="current-password" required className="field" value={password}
              onChange={(e) => setPassword(e.target.value)} aria-invalid={!!error} aria-describedby={error ? "login-error" : undefined} />
          </div>
          {error && <p id="login-error" role="alert" className="text-base text-danger">{error}</p>}
          <button type="submit" className="btn-primary w-full" disabled={busy || !email || !password}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </main>
  );
}