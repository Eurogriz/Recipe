"use client";

import { useEffect, useState } from "react";
import { Plus, Trash2, Pencil } from "lucide-react";
import {
  api,
  type MeOut,
  type User,
  type UserCreateBody,
  type UserUpdateBody,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, THead, TH, TR, TD } from "@/components/ui/table";
import { useT } from "@/i18n/I18nProvider";

const ROLES = ["Viewer", "Technologist", "Auditor", "Admin"] as const;

type DialogMode = null | "create" | { kind: "edit"; user: User };

export default function AdminUsersPage() {
  const t = useT();
  const [me, setMe] = useState<MeOut | null>(null);
  const [users, setUsers] = useState<User[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [dialog, setDialog] = useState<DialogMode>(null);

  const load = () => {
    api
      .listUsers()
      .then((r) => setUsers(r.users))
      .catch((e) => setErr(t("admin.failed", { msg: e.message ?? String(e) })));
  };

  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const canAdmin = me?.scopes.includes("*") ?? false;

  const removeUser = async (u: User) => {
    if (typeof window !== "undefined") {
      const ok = window.confirm(
        t("admin.dialog.confirm_delete", { username: u.username })
      );
      if (!ok) return;
    }
    try {
      await api.deleteUser(u.id);
      setMsg(t("admin.delete_ok"));
      load();
    } catch (e: any) {
      setErr(t("admin.failed", { msg: e.message ?? String(e) }));
    }
  };

  return (
    <div className="p-8 space-y-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">{t("admin.title")}</h1>
        <p className="text-muted-foreground mt-1">{t("admin.subtitle")}</p>
      </header>

      {me && !canAdmin && (
        <div className="rounded-md border border-amber-300 bg-amber-50 text-amber-900 px-4 py-3 text-sm">
          {t("admin.forbidden", { role: me.role ?? me.mode })}
        </div>
      )}

      <div className="flex items-center gap-3">
        <Button onClick={() => setDialog("create")} disabled={!canAdmin}>
          <Plus className="h-4 w-4" /> {t("admin.new")}
        </Button>
        {msg && <span className="text-sm text-green-700">{msg}</span>}
        {err && <span className="text-sm text-red-700">{err}</span>}
      </div>

      <Card>
        <CardContent className="p-0">
          {!users ? (
            <p className="p-6 text-sm text-muted-foreground">{t("admin.loading")}</p>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>{t("admin.col.username")}</TH>
                  <TH>{t("admin.col.role")}</TH>
                  <TH>{t("admin.col.email")}</TH>
                  <TH>{t("admin.col.active")}</TH>
                  <TH>{t("admin.col.last_login")}</TH>
                  <TH>{t("admin.col.created")}</TH>
                  <TH className="text-right">{t("admin.col.actions")}</TH>
                </TR>
              </THead>
              <TBody>
                {users.map((u) => (
                  <TR key={u.id}>
                    <TD className="font-medium">{u.username}</TD>
                    <TD>
                      <Badge
                        variant={
                          u.role === "Admin"
                            ? "destructive"
                            : u.role === "Auditor"
                              ? "warning"
                              : u.role === "Technologist"
                                ? "info"
                                : "outline"
                        }
                      >
                        {u.role}
                      </Badge>
                    </TD>
                    <TD className="text-xs">{u.email ?? "—"}</TD>
                    <TD>
                      <Badge variant={u.is_active ? "success" : "outline"}>
                        {u.is_active ? "✓" : "✗"}
                      </Badge>
                    </TD>
                    <TD className="text-xs">{u.last_login_at ?? "—"}</TD>
                    <TD className="text-xs">{u.created_at}</TD>
                    <TD className="text-right">
                      <div className="inline-flex gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={!canAdmin}
                          onClick={() => setDialog({ kind: "edit", user: u })}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={!canAdmin}
                          onClick={() => removeUser(u)}
                        >
                          <Trash2 className="h-3.5 w-3.5 text-red-500" />
                        </Button>
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {dialog === "create" && (
        <UserDialog
          title={t("admin.dialog.create")}
          onCancel={() => setDialog(null)}
          onOk={async (body) => {
            await api.createUser(body as UserCreateBody);
            setMsg(t("admin.create_ok", { username: (body as UserCreateBody).username }));
            setDialog(null);
            load();
          }}
        />
      )}
      {dialog !== null && dialog !== "create" && (
        <UserDialog
          title={t("admin.dialog.edit")}
          user={dialog.user}
          onCancel={() => setDialog(null)}
          onOk={async (patch) => {
            await api.updateUser(dialog.user.id, patch as UserUpdateBody);
            setMsg(t("admin.update_ok", { username: dialog.user.username }));
            setDialog(null);
            load();
          }}
        />
      )}
    </div>
  );
}

function UserDialog({
  title,
  user,
  onCancel,
  onOk,
}: {
  title: string;
  user?: User;
  onCancel: () => void;
  onOk: (body: UserCreateBody | UserUpdateBody) => Promise<void>;
}) {
  const t = useT();
  const [username, setUsername] = useState(user?.username ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [role, setRole] = useState(user?.role ?? "Viewer");
  const [password, setPassword] = useState("");
  const [isActive, setIsActive] = useState(user?.is_active ?? true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      if (user) {
        // Edit — send only the fields the user actually touched.
        const patch: UserUpdateBody = {
          role,
          is_active: isActive,
          email: email.trim() ? email.trim() : null,
        };
        if (password) patch.new_password = password;
        await onOk(patch);
      } else {
        if (!username.trim()) throw new Error("username required");
        if (!password) throw new Error("password required");
        await onOk({
          username: username.trim(),
          password,
          role,
          email: email.trim() || undefined,
          is_active: isActive,
        });
      }
    } catch (e: any) {
      const detail = e?.detail?.detail ?? e?.detail;
      const msg =
        typeof detail === "string" ? detail : e?.message ?? String(e);
      setErr(t("admin.failed", { msg }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="w-full max-w-md rounded-xl bg-white border border-border shadow-lg">
        <div className="border-b border-border px-5 py-3 font-semibold">{title}</div>
        <div className="p-5 space-y-3">
          <Labeled label={t("admin.f.username")}>
            <Input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={!!user}
            />
          </Labeled>
          <Labeled
            label={user ? t("admin.f.password.change") : t("admin.f.password")}
          >
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Labeled>
          <Labeled label={t("admin.f.role")}>
            <select
              className="w-full h-9 rounded-md border border-input px-2 text-sm bg-white"
              value={role}
              onChange={(e) => setRole(e.target.value)}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </Labeled>
          <Labeled label={t("admin.f.email")}>
            <Input value={email} onChange={(e) => setEmail(e.target.value)} />
          </Labeled>
          <label className="inline-flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
            />
            {t("admin.f.active")}
          </label>
        </div>
        {err && (
          <div className="mx-5 mb-3 text-sm text-red-700 border border-red-200 bg-red-50 rounded px-3 py-2">
            {err}
          </div>
        )}
        <div className="border-t border-border px-5 py-3 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={busy}>
            {t("workflow.dialog.cancel")}
          </Button>
          <Button size="sm" onClick={submit} disabled={busy}>
            {t("workflow.dialog.ok")}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Labeled({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="text-xs text-muted-foreground block mb-1">{label}</label>
      {children}
    </div>
  );
}
