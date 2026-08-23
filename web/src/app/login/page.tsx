"use client";

import { useEffect, useState } from "react";
import { LogIn, ShieldCheck } from "lucide-react";
import { api, type MeOut, type LoginOut } from "@/lib/api";
import { useT } from "@/i18n/I18nProvider";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function LoginPage() {
  const t = useT();
  const [me, setMe] = useState<MeOut | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<LoginOut | null>(null);

  useEffect(() => {
    // Detect an existing session so we can warn the user before they
    // overwrite it — logging in a second time silently changes who
    // the audit log will attribute future actions to.
    api.me().then(setMe).catch(() => setMe(null));
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) return;
    setBusy(true);
    setErr(null);
    try {
      const out = await api.login({ username, password });
      setOk(out);
      // Small delay so the user notices the redirect, then hard reload
      // so every widget that snapshots /me refetches with the new cookie.
      setTimeout(() => {
        window.location.href = "/";
      }, 400);
    } catch (e: any) {
      const msg =
        e?.status === 401
          ? t("login.bad_credentials")
          : e?.message ?? String(e);
      setErr(t("login.failed").replace("{msg}", msg));
    } finally {
      setBusy(false);
    }
  };

  const isSessionActive = me?.mode === "session" && me.role;

  return (
    <div className="min-h-screen grid place-items-center bg-slate-50 p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <LogIn className="h-5 w-5 text-primary" />
            {t("login.title")}
          </CardTitle>
          <p className="text-sm text-muted-foreground pt-2">
            {t("login.subtitle")}
          </p>
        </CardHeader>
        <CardContent>
          {isSessionActive ? (
            <div className="p-3 rounded-md bg-amber-50 text-amber-900 text-sm border border-amber-200 mb-4">
              {t("login.already_authed")
                .replace(
                  "{who}",
                  me!.subject.replace(/^user:/, "")
                )
                .replace("{role}", me!.role || "-")}
            </div>
          ) : null}
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">
                {t("login.f.username")}
              </label>
              <Input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
                autoComplete="username"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">
                {t("login.f.password")}
              </label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>
            {err ? (
              <div className="p-2 rounded-md bg-red-50 text-red-800 text-sm border border-red-200">
                {err}
              </div>
            ) : null}
            {ok ? (
              <div className="p-2 rounded-md bg-emerald-50 text-emerald-900 text-sm border border-emerald-200 flex items-center gap-2">
                <ShieldCheck className="h-4 w-4" />
                <span>
                  {t("login.session_expires_in").replace(
                    "{mins}",
                    String(
                      Math.max(
                        1,
                        Math.round((ok.expires_at * 1000 - Date.now()) / 60000)
                      )
                    )
                  )}
                </span>
              </div>
            ) : null}
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? t("login.submitting") : t("login.submit")}
            </Button>
            <p className="text-xs text-muted-foreground">
              {t("login.after_login_hint")}
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
