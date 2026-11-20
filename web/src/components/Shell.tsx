"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "@/lib/session";
import { ProgressProvider, useProgress } from "@/lib/progress";
import StepBar from "./StepBar";
import { IconClients, IconHome, IconReports, IconReview, IconUpload } from "./Icons";

const NAV = [
  { href: "/overview", label: "Overview", Icon: IconHome, match: ["/overview"], badge: null },
  { href: "/invoices", label: "Invoices", Icon: IconUpload, match: ["/invoices", "/upload"], badge: "invoices" },
  { href: "/review", label: "Review", Icon: IconReview, match: ["/review", "/flags"], badge: "flags" },
  { href: "/reports", label: "Reports", Icon: IconReports, match: ["/reports"], badge: null },
  { href: "/clients", label: "Clients", Icon: IconClients, match: ["/clients"], badge: null },
] as const;

export default function Shell({ children }: { children: React.ReactNode }) {
  const { client } = useSession();
  return (
    <ProgressProvider key={client?.id ?? "none"} cid={client?.id ?? null}>
      <Frame>{children}</Frame>
    </ProgressProvider>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { user, client } = useSession();
  const p = useProgress();
  const badges: Record<string, number> = { invoices: (p?.filesBusy ?? 0) + (p?.needReview ?? 0), flags: p?.flagsOpen ?? 0 };
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[232px_1fr]">
      <aside className="no-print fixed inset-x-0 bottom-0 z-20 flex h-16 border-t border-line bg-sunken md:inset-y-0 md:right-auto md:h-auto md:w-[72px] md:flex-col md:border-t-0 lg:w-[232px]">
        <div className="hidden px-2 pb-6 pt-6 text-center md:block lg:px-6 lg:text-left">
          <p className="text-sm font-bold leading-tight text-primary lg:text-lg">Techtic</p>
          <p className="hidden text-base text-muted lg:block">Invoice Audit</p>
        </div>
        <nav aria-label="Main" className="flex-1">
          <ul className="flex h-full items-stretch gap-0.5 px-1 py-1 md:flex-col md:gap-1 md:px-2 md:py-0 lg:px-3">
            {NAV.map(({ href, label, Icon, match, badge }) => {
              const active = match.some((m) => path.startsWith(m));
              const count = badge ? badges[badge] : 0;
              return (
                <li key={href} className="min-w-0 flex-1 md:flex-none">
                  <Link
                    href={href}
                    aria-current={active ? "page" : undefined}
                    className={`relative flex h-full min-h-[52px] flex-col items-center justify-center gap-0.5 rounded-md border-t-4 px-1 text-xs md:border-l-4 md:border-t-0 md:text-sm lg:min-h-[48px] lg:flex-row lg:justify-start lg:gap-3 lg:px-3 lg:text-base ${
                      active ? "border-primary bg-surface font-bold text-primary" : "border-transparent text-ink hover:bg-surface/60"
                    }`}
                  >
                    <Icon />
                    {label === "Overview" ? <><span className="lg:hidden">Home</span><span className="hidden lg:inline">Overview</span></> : <span>{label}</span>}
                    {count > 0 && (
                      <span className="num absolute right-2 top-1 min-w-[22px] rounded-full bg-amber px-1.5 text-center text-xs font-bold leading-[22px] text-ink lg:static lg:ml-auto"
                        aria-label={`${count} waiting`}>{count}</span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="hidden border-t border-line px-2 py-4 text-center md:block lg:px-6 lg:text-left">
          <p className="hidden text-base font-medium lg:block">{user.name}</p>
          <p className="hidden text-sm capitalize text-muted lg:block">{user.role}</p>
        </div>
      </aside>
      <div className="min-w-0 pb-16 md:pb-0 md:pl-[72px] lg:col-start-2 lg:pl-0">
        <header className="no-print flex min-h-[64px] items-center justify-between gap-4 border-b border-line bg-surface px-4 sm:px-6 lg:px-10">
          <div className="min-w-0">
            <p className="text-sm text-muted">Working on</p>
            <p className="truncate text-lg font-bold" data-testid="active-client">
              {client ? client.name : <span className="font-medium text-muted">No client chosen</span>}
            </p>
          </div>
          <Link href="/clients" className={client ? "btn-secondary btn-sm" : "btn-primary btn-sm"}>
            {client ? "Switch client" : "Choose client"}
          </Link>
        </header>
        {client && <StepBar />}
        <main className="w-full px-4 py-6 sm:px-6 sm:py-8 lg:px-10 lg:py-10">{children}</main>
      </div>
    </div>
  );
}
