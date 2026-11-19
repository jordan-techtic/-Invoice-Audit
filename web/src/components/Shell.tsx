"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "@/lib/session";
import { IconClients, IconReports, IconReview, IconUpload } from "./Icons";

const NAV = [
  { href: "/clients", label: "Clients", Icon: IconClients, match: ["/clients"] },
  { href: "/upload", label: "Upload", Icon: IconUpload, match: ["/upload"] },
  { href: "/review", label: "Review", Icon: IconReview, match: ["/review", "/invoices", "/flags"] },
  { href: "/reports", label: "Reports", Icon: IconReports, match: ["/reports"] },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { user, client } = useSession();
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[232px_1fr]">
      <aside className="no-print fixed inset-y-0 left-0 z-10 flex w-[72px] flex-col bg-sunken lg:w-[232px]">
        <div className="px-2 pb-6 pt-6 text-center lg:px-6 lg:text-left">
          <p className="text-sm font-bold leading-tight text-primary lg:text-lg">Techtic</p>
          <p className="hidden text-base text-muted lg:block">Invoice Audit</p>
        </div>
        <nav aria-label="Main" className="flex-1">
          <ul className="flex flex-col gap-1 px-2 lg:px-3">
            {NAV.map(({ href, label, Icon, match }) => {
              const active = match.some((m) => path.startsWith(m));
              return (
                <li key={href}>
                  <Link
                    href={href}
                    aria-current={active ? "page" : undefined}
                    className={`flex min-h-[52px] flex-col items-center justify-center gap-0.5 rounded-md border-l-4 px-1 text-sm lg:min-h-[48px] lg:flex-row lg:justify-start lg:gap-3 lg:px-3 lg:text-base ${
                      active ? "border-primary bg-surface font-bold text-primary" : "border-transparent text-ink hover:bg-surface/60"
                    }`}
                  >
                    <Icon />
                    <span>{label}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="border-t border-line px-2 py-4 text-center lg:px-6 lg:text-left">
          <p className="hidden text-base font-medium lg:block">{user.name}</p>
          <p className="hidden text-sm capitalize text-muted lg:block">{user.role}</p>
          {user.role === "admin" && (
            <Link href="/admin/audit" className="mt-1 block min-h-[44px] content-center text-sm font-medium text-primary underline underline-offset-4 lg:text-base">Audit log</Link>
          )}
        </div>
      </aside>
      <div className="min-w-0 pl-[72px] lg:col-start-2 lg:pl-0">
        <header className="no-print flex min-h-[72px] items-center justify-between gap-4 border-b border-line px-6 lg:px-10">
          <p className="text-lg font-bold" data-testid="active-client">
            {client ? client.name : <span className="font-medium text-muted">No client chosen</span>}
          </p>
          <Link href="/clients" className="min-h-[44px] content-center text-base font-medium text-primary underline underline-offset-4">
            {client ? "Switch client" : "Choose client"}
          </Link>
        </header>
        <main className="mx-auto w-full max-w-page px-6 py-8 lg:px-10 lg:py-10">{children}</main>
      </div>
    </div>
  );
}
