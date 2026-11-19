"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useProgress, type Step } from "@/lib/progress";
import { IconCheck } from "./Icons";

const ON_PAGE: Record<Step["key"], string[]> = {
  upload: ["/upload"], check: ["/invoices"], run: ["/review"], review: ["/review"], report: ["/reports"],
};

/** The five audit steps, always visible under the header, plus the single next action. */
export default function StepBar() {
  const p = useProgress();
  const path = usePathname();
  if (!p) return null;
  const next = p.next;
  const onNextPage = next.href.split("?")[0] === path;

  return (
    <div className="no-print border-b border-line bg-surface px-6 py-4 lg:px-10" data-testid="step-bar">
      <div className="mx-auto flex max-w-page flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <ol className="grid min-w-0 flex-1 grid-cols-5 gap-2" aria-label="Audit steps">
          {p.steps.map((s) => {
            const here = ON_PAGE[s.key].some((m) => path.startsWith(m));
            return (
              <li key={s.key} className="min-w-0">
                <Link href={s.href} aria-current={s.state === "current" ? "step" : undefined}
                  className={`flex h-full min-h-[56px] items-start gap-2 rounded-md border px-2 py-2 sm:px-3 ${here ? "border-primary" : "border-transparent"} hover:bg-bg`}>
                  <span aria-hidden className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-bold ${
                    s.state === "done" ? "bg-confirmed text-white" : s.state === "current" ? "bg-amber text-ink" : "bg-sunken text-muted"}`}>
                    {s.state === "done" ? <IconCheck /> : s.n}
                  </span>
                  <span className="hidden min-w-0 sm:block">
                    <span className={`block truncate text-sm font-bold ${s.state === "todo" ? "text-muted" : "text-ink"}`}>{s.short}</span>
                    <span className="block truncate text-sm text-muted">{p.loading ? "…" : s.detail}</span>
                  </span>
                  <span className="sr-only">{`Step ${s.n}: ${s.label}. ${s.state === "done" ? "Done" : s.state === "current" ? "Current step" : "Not started"}. ${s.detail}`}</span>
                </Link>
              </li>
            );
          })}
        </ol>
        {!p.loading && (
          <div className="flex items-center gap-3 rounded-md bg-amber-soft px-4 py-2 xl:w-[330px] xl:shrink-0" role="status" data-testid="next-step">
            <div className="min-w-0 flex-1">
              <p className="text-sm text-muted">Next step</p>
              <p className="truncate font-bold">{next.title}</p>
            </div>
            {!onNextPage && <Link href={next.href} className="btn-primary btn-sm shrink-0">{next.cta}</Link>}
          </div>
        )}
      </div>
    </div>
  );
}
