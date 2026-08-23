"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Beaker,
  ClipboardList,
  Cpu,
  ExternalLink,
  Key,
  LayoutDashboard,
  LogIn,
  LogOut,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Waves,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api, type MeOut } from "@/lib/api";
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
  { href: "/regulatory", labelKey: "nav.regulatory", icon: ShieldCheck },
  { href: "/ml", labelKey: "nav.ml", icon: Cpu },
  { href: "/ml/drift", labelKey: "nav.drift", icon: Waves },
  { href: "/ml/jobs", labelKey: "nav.jobs", icon: Activity },
  { href: "/admin/data-quality", labelKey: "nav.dq", icon: ShieldAlert },
  { href: "/admin/users", labelKey: "nav.admin", icon: Shield },
  { href: "/admin/audit", labelKey: "nav.audit", icon: ClipboardList },
  { href: "/admin/api-keys", labelKey: "nav.apikeys", icon: Key },
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
              <div className="text-xs text-muted-foreground">v1.22.0</div>
            </div>
          </Link>
        </div>
        <nav className="flex-1 px-3 pb-6 space-y-1">
          {NAV.map((item) => {
            // Pick the longest matching NAV href, so /ml/drift lights up
            // "Data drift" (not "ML / Ops"), and /recipes/{id} lights up
            // "Recipes".
            const bestMatch = NAV.filter(
              (n) =>
                (n.href === "/" && pathname === "/") ||
                (n.href !== "/" &&
                  (pathname === n.href || pathname.startsWith(n.href + "/")))
            ).sort((a, b) => b.href.length - a.href.length)[0];
            const active = bestMatch?.href === item.href;
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
          <WhoAmI />
        </div>
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

function WhoAmI() {
  const t = useT();
  const [me, setMe] = useState<MeOut | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
  }, []);
  if (!me) return null;
  const roleLabel = me.role
    ? t(`me.role.${me.role.toLowerCase()}` as any)
    : t("me.anonymous");
  const cleanSubject = me.subject.startsWith("user:")
    ? me.subject.slice("user:".length)
    : me.subject;

  // Only offer "log out" when there's actually a session cookie to
  // clear.  For open-mode / static-token / JWT modes the button
  // would be a lie — the auth state lives elsewhere.
  const canLogout = me.mode === "session";
  // Show a "log in" nudge only when the user is genuinely anonymous
  // (open mode).  Basic/JWT users pass their creds on every request
  // and don't need a login page.
  const showLogin = me.mode === "open";

  const logout = async () => {
    if (!window.confirm(t("logout.confirm"))) return;
    setBusy(true);
    try {
      await api.logout();
      window.location.href = "/login";
    } catch (e: any) {
      window.alert(
        t("logout.failed").replace("{msg}", e?.message ?? String(e))
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Shield className="h-4 w-4" />
        <div className="min-w-0">
          <div className="font-medium text-foreground truncate">
            {cleanSubject}
          </div>
          <div className="truncate">{roleLabel}</div>
        </div>
      </div>
      {canLogout ? (
        <button
          onClick={logout}
          disabled={busy}
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground underline underline-offset-2 disabled:opacity-50"
        >
          <LogOut className="h-3 w-3" />
          {t("nav.logout")}
        </button>
      ) : null}
      {showLogin ? (
        <Link
          href="/login"
          className="inline-flex items-center gap-1 text-xs text-primary hover:text-primary/80 underline underline-offset-2"
        >
          <LogIn className="h-3 w-3" />
          {t("nav.login")}
        </Link>
      ) : null}
    </div>
  );
}
