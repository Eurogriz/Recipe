"use client";

import { useEffect, useState } from "react";
import { Copy, Key, Plus, ShieldOff, Trash2 } from "lucide-react";
import {
  api,
  type ApiKey,
  type ApiKeyIssuedOut,
  type MeOut,
} from "@/lib/api";
import { useT } from "@/i18n/I18nProvider";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, THead, TH, TR, TD } from "@/components/ui/table";

/** Extract the current user's id from ``/me`` when possible.
 *
 * ``MeOut.subject`` is ``user:<name>`` for real users.  We look the
 * user up by username in ``/users`` to get the id — /users is
 * Admin-only, so a non-Admin sees only their own keys via a small
 * pre-flight probe that reveals nothing about others.
 */
async function resolveUserId(me: MeOut): Promise<string | null> {
  if (!me.subject.startsWith("user:")) return null;
  const username = me.subject.slice(5);
  try {
    const list = await api.listUsers();
    return list.users.find((u) => u.username === username)?.id ?? null;
  } catch {
    return null;
  }
}

export default function ApiKeysPage() {
  const t = useT();
  const [me, setMe] = useState<MeOut | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [issued, setIssued] = useState<ApiKeyIssuedOut | null>(null);

  useEffect(() => {
    api
      .me()
      .then(async (m) => {
        setMe(m);
        const uid = await resolveUserId(m);
        setUserId(uid);
      })
      .catch(() => setMe(null));
  }, []);

  useEffect(() => {
    if (!userId) return;
    api
      .listApiKeys(userId)
      .then((r) => setKeys(r.keys))
      .catch((e: any) =>
        setErr(t("apikeys.failed").replace("{msg}", e?.message ?? String(e)))
      );
  }, [userId, t]);

  if (me === null) {
    return (
      <div className="p-6 text-muted-foreground">{t("apikeys.loading")}</div>
    );
  }
  if (!me.subject.startsWith("user:")) {
    return (
      <div className="p-6">
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            {t("apikeys.need_login")}
          </CardContent>
        </Card>
      </div>
    );
  }

  const revoke = async (k: ApiKey) => {
    if (!userId) return;
    if (
      !window.confirm(
        t("apikeys.revoke.confirm").replace("{label}", k.label)
      )
    )
      return;
    try {
      await api.revokeApiKey(userId, k.id);
      setKeys((prev) => (prev ?? []).filter((x) => x.id !== k.id));
      setMsg(t("apikeys.revoke.ok"));
    } catch (e: any) {
      setErr(t("apikeys.failed").replace("{msg}", e?.message ?? String(e)));
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-6xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <Key className="h-5 w-5 text-primary" />
            {t("apikeys.title")}
          </h1>
          <p className="text-sm text-muted-foreground pt-1">
            {t("apikeys.subtitle")}
          </p>
        </div>
        <Button onClick={() => setDialogOpen(true)} disabled={!userId}>
          <Plus className="h-4 w-4 mr-1" />
          {t("apikeys.new")}
        </Button>
      </div>

      {err ? (
        <div className="p-3 rounded-md bg-red-50 text-red-800 text-sm border border-red-200">
          {err}
        </div>
      ) : null}
      {msg ? (
        <div className="p-3 rounded-md bg-emerald-50 text-emerald-900 text-sm border border-emerald-200">
          {msg}
        </div>
      ) : null}

      <Card>
        <CardContent className="p-0">
          {keys === null ? (
            <div className="p-8 text-center text-muted-foreground">
              {t("apikeys.loading")}
            </div>
          ) : keys.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">
              {t("apikeys.empty")}
            </div>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>{t("apikeys.col.label")}</TH>
                  <TH>{t("apikeys.col.prefix")}</TH>
                  <TH>{t("apikeys.col.status")}</TH>
                  <TH>{t("apikeys.col.created")}</TH>
                  <TH>{t("apikeys.col.last_used")}</TH>
                  <TH>{t("apikeys.col.expires")}</TH>
                  <TH></TH>
                </TR>
              </THead>
              <TBody>
                {keys.map((k) => (
                  <TR key={k.id}>
                    <TD className="font-medium">{k.label}</TD>
                    <TD className="font-mono text-xs">{k.token_prefix}…</TD>
                    <TD>
                      {k.is_active ? (
                        <Badge variant="success">
                          {t("apikeys.status.active")}
                        </Badge>
                      ) : k.revoked_at ? (
                        <Badge variant="destructive">
                          {t("apikeys.status.revoked")}
                        </Badge>
                      ) : (
                        <Badge variant="warning">
                          {t("apikeys.status.expired")}
                        </Badge>
                      )}
                    </TD>
                    <TD className="text-xs text-muted-foreground">
                      {new Date(k.created_at).toLocaleString()}
                    </TD>
                    <TD className="text-xs text-muted-foreground">
                      {k.last_used_at
                        ? new Date(k.last_used_at).toLocaleString()
                        : "—"}
                    </TD>
                    <TD className="text-xs text-muted-foreground">
                      {k.expires_at
                        ? new Date(k.expires_at).toLocaleString()
                        : t("apikeys.expires.never")}
                    </TD>
                    <TD>
                      {k.is_active ? (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => revoke(k)}
                        >
                          <ShieldOff className="h-3 w-3 mr-1" />
                          {t("apikeys.revoke.button")}
                        </Button>
                      ) : null}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {dialogOpen && userId ? (
        <CreateDialog
          userId={userId}
          onClose={() => setDialogOpen(false)}
          onIssued={(out) => {
            setIssued(out);
            setKeys((prev) => [
              {
                id: out.id,
                user_id: out.user_id,
                label: out.label,
                token_prefix: out.token_prefix,
                created_at: out.created_at,
                last_used_at: out.last_used_at,
                expires_at: out.expires_at,
                revoked_at: out.revoked_at,
                is_active: out.is_active,
              },
              ...(prev ?? []),
            ]);
            setDialogOpen(false);
          }}
        />
      ) : null}

      {issued ? (
        <IssuedDialog issued={issued} onClose={() => setIssued(null)} />
      ) : null}
    </div>
  );
}

function CreateDialog({
  userId,
  onClose,
  onIssued,
}: {
  userId: string;
  onClose: () => void;
  onIssued: (out: ApiKeyIssuedOut) => void;
}) {
  const t = useT();
  const [label, setLabel] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!label.trim()) return;
    setBusy(true);
    try {
      const out = await api.createApiKey(userId, {
        label: label.trim(),
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      });
      onIssued(out);
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 grid place-items-center z-50 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>{t("apikeys.dialog.create")}</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-3">
            <div>
              <label className="block text-sm font-medium mb-1">
                {t("apikeys.f.label")}
              </label>
              <Input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="ci-runner"
                required
                autoFocus
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">
                {t("apikeys.f.expires")}
              </label>
              <Input
                type="datetime-local"
                value={expiresAt}
                onChange={(e) => setExpiresAt(e.target.value)}
              />
              <p className="text-xs text-muted-foreground mt-1">
                {t("apikeys.f.expires.hint")}
              </p>
            </div>
            {err ? (
              <div className="p-2 rounded-md bg-red-50 text-red-800 text-sm border border-red-200">
                {err}
              </div>
            ) : null}
            <div className="flex gap-2 justify-end pt-2">
              <Button type="button" variant="outline" onClick={onClose}>
                {t("apikeys.dialog.cancel")}
              </Button>
              <Button type="submit" disabled={busy}>
                {busy ? t("apikeys.dialog.creating") : t("apikeys.dialog.mint")}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

function IssuedDialog({
  issued,
  onClose,
}: {
  issued: ApiKeyIssuedOut;
  onClose: () => void;
}) {
  const t = useT();
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(issued.plaintext);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* older browsers — user copies manually */
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 grid place-items-center z-50 p-4">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Key className="h-5 w-5 text-primary" />
            {t("apikeys.issued.title").replace("{label}", issued.label)}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="p-3 rounded-md bg-amber-50 text-amber-900 text-sm border border-amber-200">
            {t("apikeys.issued.warning")}
          </div>
          <div className="flex gap-2">
            <Input
              value={issued.plaintext}
              readOnly
              className="font-mono text-xs"
              onClick={(e) => (e.target as HTMLInputElement).select()}
            />
            <Button variant="outline" onClick={copy}>
              <Copy className="h-4 w-4 mr-1" />
              {copied ? t("apikeys.issued.copied") : t("apikeys.issued.copy")}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            {t("apikeys.issued.usage")}
          </p>
          <pre className="bg-slate-50 p-3 rounded-md text-xs overflow-auto">
            curl -H &quot;Authorization: Bearer {issued.plaintext}&quot; \
            {"\n"}     https://.../api/me
          </pre>
          <div className="flex justify-end pt-2">
            <Button onClick={onClose}>
              <Trash2 className="h-4 w-4 mr-1" />
              {t("apikeys.issued.dismiss")}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
