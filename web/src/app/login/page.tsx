import { redirect } from "next/navigation";

/** Login removed — send everyone into the app. */
export default function LoginPage() {
  redirect("/clients");
}
