"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Beaker, Cpu, LayoutDashboard, Activity, ExternalLink } from "lucide-react";
import { I18nProvider, useT } from "@/i18n/I18nProvider";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { cn } from "@/lib/utils";

/** Client-only shell so we can use hooks (usePathname, useT). */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <I18nProvider>
      <Layout>{children}</Layout>
    </I18nProvider>
  );
}

const NAV = [
  { href: "/", labelKey: "nav.dashboard", icon: LayoutDashboard },
  { href: "/recipes", labelKey: "nav.recipes", icon: Beaker },
  { href: "/ml", labelKey: "nav.ml", icon: Cpu },
  { href: "/ml/jobs", labelKey: "nav.jobs", icon: Activity },
] as const;

function Layout({ children }: { children: React.ReactNode }) {
  const t = useT();
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen w-full">
      <aside className="hidden md:flex md:w-60 md:flex-col border-r border-border bg-white">
        <div className="px-6 py-5">
          <Link href="/" className="flex items-center gap-2 group">
            <div className="h-9 w-9 rounded-lg bg-primary text-primary-foreground grid place-items-center font-semibold">
              FW
            </div>
            <div>
              <div className="font-semibold leading-tight group-hover:text-primary transition-colors">
                {t("app.brand")}
              </div>
              <div className="text-xs text-muted-foreground">v1.8.0</div>
            </div>
          </Link>
        </div>
        <nav className="flex-1 px-3 pb-6 space-y-1">
          {NAV.map((item) => {
            const active =
              item.href === "/"
                ? pathname === "/"
                : pathname === item.href || pathname.startsWith(item.href + "/");
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-primary/10 text-primary font-medium"
                    : "text-foreground hover:bg-accent"
                )}
              >
                <item.icon
                  className={cn(
                    "h-4 w-4",
                    active ? "text-primary" : "text-muted-foreground"
                  )}
                />
                {t(item.labelKey)}
              </Link>
            );
          })}
        </nav>
        <div className="px-4 py-3 border-t border-border">
          <LanguageSwitcher />
        </div>
        <div className="px-4 py-3 border-t border-border text-xs text-muted-foreground">
          <a
            href="/api/docs"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 hover:text-foreground underline underline-offset-2"
          >
            {t("nav.swagger")} <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </aside>

      <main className="flex-1 min-w-0">
        {/* Mobile top bar (visible < md) */}
        <div className="md:hidden flex items-center justify-between border-b border-border bg-white px-4 py-3">
          <Link href="/" className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-md bg-primary text-primary-foreground grid place-items-center text-xs font-semibold">
              FW
            </div>
            <span className="font-medium">{t("app.brand")}</span>
          </Link>
          <LanguageSwitcher compact />
        </div>

        {children}
      </main>
    </div>
  );
}
