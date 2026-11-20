import type { Metadata } from "next";

// The report link is a secret address: keep it out of search engines and do not send it on as a referrer.
export const metadata: Metadata = { robots: { index: false, follow: false }, referrer: "no-referrer" };

export default function PublicReportLayout({ children }: { children: React.ReactNode }) {
  return children;
}
