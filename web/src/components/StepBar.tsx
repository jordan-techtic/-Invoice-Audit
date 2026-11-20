"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useProgress, type Step } from "@/lib/progress";
import { IconCheck } from "./Icons";

const ON_PAGE: Record<Step["key"], string[]> = {
  check: ["/invoices"], review: ["/review", "/flags"], report: ["/reports"],
};

/** The three audit steps, always visible under the header, plus the single next action. */
export default function StepBar() {
  const p = useProgress();
  const path = usePathname();
  if (!p) return null;
  const next = p.next;
  const onNextPage = next.href.split("?")[0] === path;

  return (
    <div className="no-print border-b border-line bg-surface px-4 py-4 sm:px-6 lg:px-10" data-testid="step-bar">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <ol className="flex min-w-0 flex-1 items-start" aria-label="Audit steps">
          {p.steps.map((s, i) => {
            const here = ON_PAGE[s.key].some((m) => path.startsWith(m));
            const last = i === p.steps.length - 1;
            return (
              <li key={s.key} className="relative min-w-0 flex-1">
                {!last && (
                  <span aria-hidden className={`pointer-events-none absolute left-[calc(50%+26px)] right-[calc(-50%+26px)] top-[23px] h-0.5 ${s.state === "done" ? "bg-confirmed" : "bg-line"}`} />
                )}
                <Link href={s.href} aria-current={s.state === "current" ? "step" : undefined}
                  className={`relative flex h-full flex-col items-center gap-1 rounded-lg px-1 py-1.5 text-center sm:px-2 ${here ? "bg-bg" : "hover:bg-bg"}`}>
                  <span aria-hidden className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-base font-bold ${
                    s.state === "done" ? "bg-confirmed text-white" : s.state === "current" ? "bg-amber text-ink" : "bg-sunken text-muted"
                  } ${here ? "ring-2 ring-primary ring-offset-2 ring-offset-bg" : ""}`}>
                    {s.state === "done" ? <IconCheck /> : s.n}
                  </span>
                  <span className={`text-sm font-bold leading-tight sm:text-base ${s.state === "todo" ? "text-muted" : "text-ink"}`}>{s.short}</span>
                  <span className="text-xs leading-snug text-muted sm:text-sm">{p.loading ? "…" : s.detail}</span>
                  {here && <span aria-hidden className="mt-0.5 rounded-full bg-primary px-2 py-0.5 text-xs font-medium text-white">You are here</span>}
                  <span className="sr-only">{`Step ${s.n}: ${s.label}. ${s.state === "done" ? "Done" : s.state === "current" ? "Current step" : "Not started"}. ${s.detail}${here ? ". You are on this step." : ""}`}</span>
                </Link>
              </li>
            );
          })}
        </ol>
        {!p.loading && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg bg-amber-soft px-4 py-3 xl:w-[340px] xl:shrink-0" role="status" data-testid="next-step">
            <div className="min-w-0 flex-1 basis-40">
              <p className="text-sm text-muted">{p.running ? "Working" : "Next step"}</p>
              <p className="font-bold leading-snug">{p.running ? "Running the audit checks…" : next.title}</p>
            </div>
            {p.running
              ? <span aria-hidden className="h-6 w-6 shrink-0 animate-spin rounded-full border-4 border-sunken border-t-primary" />
              : !onNextPage && <Link href={next.href} className="btn-primary btn-sm shrink-0">{next.cta}</Link>}
          </div>
        )}
      </div>
    </div>
  );
}
