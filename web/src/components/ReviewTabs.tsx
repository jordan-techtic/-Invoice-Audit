import Link from "next/link";

export default function ReviewTabs({ current }: { current: "invoices" | "flags" }) {
  const tabs = [{ id: "flags", href: "/review", label: "Flags to review" }, { id: "invoices", href: "/invoices", label: "Invoices" }];
  return (
    <nav aria-label="Review sections" className="flex gap-6 border-b border-line">
      {tabs.map((t) => (
        <Link key={t.id} href={t.href} aria-current={current === t.id ? "page" : undefined}
          className={`-mb-px flex min-h-[48px] items-center border-b-4 text-base ${current === t.id ? "border-primary font-bold text-primary" : "border-transparent text-ink hover:border-line-strong"}`}>
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
