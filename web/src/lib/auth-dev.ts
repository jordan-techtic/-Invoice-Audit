/** Local dev: skip the sign-in screen and use seeded demo credentials. Set NEXT_PUBLIC_AUTO_LOGIN=false to use /login. */
export const devAutoLogin =
  process.env.NEXT_PUBLIC_AUTO_LOGIN !== "false" &&
  (process.env.NEXT_PUBLIC_AUTO_LOGIN === "true" || process.env.NODE_ENV === "development");

export const devLoginEmail =
  process.env.NEXT_PUBLIC_AUTO_LOGIN_EMAIL ?? "admin@audit-demo.com";

export const devLoginPassword =
  process.env.NEXT_PUBLIC_AUTO_LOGIN_PASSWORD ?? "admin-password-123";