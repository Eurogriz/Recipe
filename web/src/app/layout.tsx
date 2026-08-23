import type { Metadata } from "next";
import { AppShell } from "@/components/AppShell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Formulation Workbench",
  description:
    "Verified paint & coatings recipe database with ML property predictions.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // We render `lang="ru"` on the server (matches our default locale) and
  // let I18nProvider adjust `document.documentElement.lang` client-side.
  return (
    <html lang="ru" suppressHydrationWarning>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
