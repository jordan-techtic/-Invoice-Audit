/** Copies text to the clipboard. Returns false if the browser refused.
 *  `navigator.clipboard` only exists on HTTPS or localhost, so plain-HTTP deployments use the older execCommand route. */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* fall through to the fallback */ }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.cssText = "position:fixed;top:0;left:0;opacity:0;pointer-events:none";
  document.body.appendChild(ta);
  ta.select();
  ta.setSelectionRange(0, text.length);
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { ok = false; }
  ta.remove();
  return ok;
}

/** The share link the server built uses its PUBLIC_BASE_URL. If that was left at localhost while the app is opened from
 *  another address, swap in the address the page was opened from so the copied link still works. */
export function shareLink(url: string): string {
  try {
    const u = new URL(url, window.location.origin);
    const local = (h: string) => h === "localhost" || h === "127.0.0.1" || h === "0.0.0.0";
    if (local(u.hostname) && !local(window.location.hostname)) return `${window.location.origin}${u.pathname}`;
    return u.toString();
  } catch { return url; }
}
