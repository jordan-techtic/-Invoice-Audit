"use client";

import Link from "next/link";
import { useProgress } from "@/lib/progress";

export default function ReviewTabs({ current }: { current: "invoices" | "flags" }) {
  const p = useProgress();
  const tabs = [
    { id: "invoices", href: "/invoices", label: "2 · Check invoices", count: p?.needReview ?? 0 },
    { id: "flags", href: "/review", label: "3–4 · Flags to review", count: p?.flagsOpen ?? 0 },
  ];
  return (
    <nav aria-label="Review sections" className="flex gap-6 border-b border-line">
      {tabs.map((t) => (
        <Link key={t.id} href={t.href} aria-current={current === t.id ? "page" : undefined}
          className={`-mb-px flex min-h-[48px] items-center gap-2 border-b-4 text-base ${current === t.id ? "border-primary font-bold text-primary" : "border-transparent text-ink hover:border-line-strong"}`}>
          {t.label}
          {t.count > 0 && <span className="num rounded-full bg-amber px-2 text-xs font-bold leading-[22px] text-ink">{t.count}</span>}
        </Link>
      ))}
    </nav>
  );
}
