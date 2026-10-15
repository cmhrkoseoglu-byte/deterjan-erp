// /api/v1/workflow/* — görevler, bildirimler, kayda bağlı yorumlar ve kayıt geçmişi.
import { api } from "./client";
import type { Paginated, Role } from "./types";

export interface UserBrief {
  id: number;
  username: string;
  full_name: string;
}

/** Görevin/bildirimin bağlı olduğu kayıt: model "app_label.model" (ör. "inventory.lot"). */
export interface RelatedRecord {
  model: string;
  id: number;
  repr: string;
}

export type TaskStatus = "OPEN" | "IN_PROGRESS" | "DONE" | "CANCELLED";
/** 1 düşük, 2 normal, 3 yüksek, 4 acil */
export type TaskPriority = 1 | 2 | 3 | 4;

export interface Task {
  id: number;
  title: string;
  description: string;
  status: TaskStatus;
  status_label: string;
  priority: TaskPriority;
  priority_label: string;
  due_at: string | null;
  assigned_role: Role | null;
  assigned_user: UserBrief | null;
  claimed_by: UserBrief | null;
  claimed_at: string | null;
  completed_by: UserBrief | null;
  completed_at: string | null;
  completion_note: string;
  related: RelatedRecord | null;
  event_name: string;
  rule_code: string;
  created_at: string;
  updated_at: string;
  /** Giriş yapan kullanıcı bu görevi üstlenebilir/tamamlayabilir mi? */
  can_act: boolean;
}

export type NotificationLevel = "INFO" | "WARNING" | "CRITICAL";

export interface AppNotification {
  id: number;
  title: string;
  body: string;
  level: NotificationLevel;
  related: RelatedRecord | null;
  task: number | null;
  event_name: string;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
}

export interface Comment {
  id: number;
  content_type: string;
  object_id: number;
  author: UserBrief;
  body: string;
  mentions: UserBrief[];
  created_at: string;
  edited_at: string | null;
  can_edit: boolean;
}

export interface AuditEntry {
  id: number;
  timestamp: string;
  actor: number | null;
  actor_name: string;
  action: string;
  action_label: string;
  changes: Record<string, [unknown, unknown]>;
  note: string;
}

export interface RecordRef {
  /** "app_label.model", ör. "inventory.lot" */
  contentType: string;
  objectId: number;
}

export interface TaskQuery {
  mine?: boolean;
  open?: boolean;
  page?: number;
  page_size?: number;
  ordering?: string;
}

export async function fetchTasks(params: TaskQuery): Promise<Paginated<Task>> {
  const { data } = await api.get<Paginated<Task>>("/workflow/tasks/", { params });
  return data;
}

export async function claimTask(id: number): Promise<Task> {
  const { data } = await api.post<Task>(`/workflow/tasks/${id}/claim/`);
  return data;
}

export async function completeTask(id: number, note = ""): Promise<Task> {
  const { data } = await api.post<Task>(`/workflow/tasks/${id}/complete/`, { note });
  return data;
}

export async function fetchNotifications(params: {
  unread?: boolean;
  page?: number;
  page_size?: number;
}): Promise<Paginated<AppNotification>> {
  const { data } = await api.get<Paginated<AppNotification>>("/workflow/notifications/", {
    params,
  });
  return data;
}

export async function fetchUnreadCount(): Promise<number> {
  const { data } = await api.get<{ count: number }>("/workflow/notifications/unread-count/");
  return data.count;
}

/** `ids` verilmezse tüm bildirimler okundu işaretlenir. */
export async function markNotificationsRead(ids?: number[]): Promise<number> {
  const body = ids ? { ids } : { all: true };
  const { data } = await api.post<{ updated: number }>("/workflow/notifications/mark-read/", body);
  return data.updated;
}

function recordParams(record: RecordRef) {
  return { content_type: record.contentType, object_id: record.objectId };
}

export async function fetchComments(record: RecordRef): Promise<Comment[]> {
  const { data } = await api.get<Paginated<Comment>>("/workflow/comments/", {
    params: { ...recordParams(record), page_size: 500 },
  });
  return data.results;
}

export async function addComment(record: RecordRef, body: string): Promise<Comment> {
  const { data } = await api.post<Comment>("/workflow/comments/", {
    ...recordParams(record),
    body,
  });
  return data;
}

export async function editComment(id: number, body: string): Promise<Comment> {
  const { data } = await api.patch<Comment>(`/workflow/comments/${id}/`, { body });
  return data;
}

export async function fetchRecordHistory(record: RecordRef): Promise<AuditEntry[]> {
  const { data } = await api.get<Paginated<AuditEntry>>("/workflow/record-history/", {
    params: { ...recordParams(record), page_size: 200 },
  });
  return data.results;
}

export async function fetchMentionableUsers(search: string): Promise<UserBrief[]> {
  const { data } = await api.get<UserBrief[]>("/workflow/mentionable-users/", {
    params: { search },
  });
  return data;
}
