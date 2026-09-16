import { apiFetch } from "./http";

type AdminSeverity = "ok" | "warn" | "danger";

export interface AdminUserOut {
  id: string;
  username: string;
  email?: string | null;
  disabled_at?: string | null;
  is_admin?: boolean;
  created_at?: string | null;
  project_count: number;
  tokens_today: number;
  calls_today: number;
  flags: string[];
  flag_labels: string[];
  severity: AdminSeverity;
}

export interface AdminOverviewOut {
  user_count: number;
  disabled_count: number;
  admin_count?: number;
  danger_count: number;
  warn_count: number;
  max_projects_per_user: number;
  users: AdminUserOut[];
}

export interface BanOut {
  ok: boolean;
  username: string;
  disabled: boolean;
  message: string;
}

export interface AdminFlagOut {
  ok: boolean;
  username: string;
  is_admin: boolean;
  message: string;
}

interface AdminFunnelStep {
  key: string;
  label: string;
  users: number;
}

export interface AdminFunnelOut {
  days: number;
  funnel: AdminFunnelStep[];
  events: Record<string, number>;
  notes?: string;
}

export function fetchAdminOverview(opts?: {
  anomaliesOnly?: boolean;
  disabledOnly?: boolean;
}): Promise<AdminOverviewOut> {
  const q = new URLSearchParams();
  if (opts?.anomaliesOnly) q.set("anomalies_only", "true");
  if (opts?.disabledOnly) q.set("disabled_only", "true");
  const qs = q.toString();
  return apiFetch<AdminOverviewOut>(`/admin/overview${qs ? `?${qs}` : ""}`);
}

export function fetchAdminFunnel(days = 30): Promise<AdminFunnelOut> {
  return apiFetch<AdminFunnelOut>(`/admin/funnel?days=${days}`);
}

export interface EmailDiagOut {
  query: string;
  matched_by: "email" | "username" | "none";
  username?: string | null;
  email?: string | null;
  email_verified: boolean;
  created_at?: string | null;
  verify_sends: number;
  verify_clicks: number;
  reset_sends: number;
  reset_clicks: number;
  last_verify_sent_at?: string | null;
  last_click_lag_s?: number | null;
  similar: { username: string; email?: string | null; verified: boolean }[];
  hint: string;
}

interface AiUsageKind {
  kind: string;
  label: string;
  calls: number;
  tokens: number;
  users: number;
  last_at?: string | null;
}

export interface AiUsageOut {
  days: number;
  totals: { calls: number; tokens: number };
  byKind: AiUsageKind[];
}

export function fetchAiUsage(days = 30): Promise<AiUsageOut> {
  return apiFetch<AiUsageOut>(`/admin/ai-usage?days=${days}`);
}

export function fetchEmailDiag(q: string): Promise<EmailDiagOut> {
  return apiFetch<EmailDiagOut>(`/admin/email-diag?q=${encodeURIComponent(q)}`);
}

export function banUser(username: string): Promise<BanOut> {
  return apiFetch<BanOut>(
    `/admin/users/${encodeURIComponent(username)}/ban`,
    { method: "POST" }
  );
}

export function unbanUser(username: string): Promise<BanOut> {
  return apiFetch<BanOut>(
    `/admin/users/${encodeURIComponent(username)}/unban`,
    { method: "POST" }
  );
}

export function grantAdmin(username: string): Promise<AdminFlagOut> {
  return apiFetch<AdminFlagOut>(
    `/admin/users/${encodeURIComponent(username)}/grant-admin`,
    { method: "POST" }
  );
}

export function revokeAdmin(username: string): Promise<AdminFlagOut> {
  return apiFetch<AdminFlagOut>(
    `/admin/users/${encodeURIComponent(username)}/revoke-admin`,
    { method: "POST" }
  );
}
