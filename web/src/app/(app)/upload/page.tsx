import { redirect } from "next/navigation";

/** Upload and check now share one page. Kept so old links and bookmarks still work. */
export default function UploadPage() {
  redirect("/invoices");
}
