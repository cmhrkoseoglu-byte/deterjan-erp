import type { AppNotification, Comment, Task } from "../api/workflow";

export function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 1,
    title: "Malzeme hazırla: UE-2026-00001",
    description: "Üretim emri onaylandı.",
    status: "OPEN",
    status_label: "Açık",
    priority: 2,
    priority_label: "Normal",
    due_at: null,
    assigned_role: "depo",
    assigned_user: null,
    claimed_by: null,
    claimed_at: null,
    completed_by: null,
    completed_at: null,
    completion_note: "",
    related: { model: "production.productionorder", id: 5, repr: "UE-2026-00001" },
    event_name: "production_order.approved",
    rule_code: "material_prep",
    created_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
    updated_at: new Date().toISOString(),
    can_act: true,
    ...overrides,
  };
}

export function makeNotification(overrides: Partial<AppNotification> = {}): AppNotification {
  return {
    id: 1,
    title: "Lot reddedildi: H-261015-001",
    body: "LAS %96",
    level: "WARNING",
    related: null,
    task: null,
    event_name: "lot.rejected",
    is_read: false,
    read_at: null,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

export function makeComment(overrides: Partial<Comment> = {}): Comment {
  return {
    id: 1,
    content_type: "inventory.lot",
    object_id: 5,
    author: { id: 2, username: "ayse", full_name: "Ayşe Yılmaz" },
    body: "@mehmet numuneyi aldın mı?",
    mentions: [{ id: 3, username: "mehmet", full_name: "Mehmet Kaya" }],
    created_at: new Date().toISOString(),
    edited_at: null,
    can_edit: true,
    ...overrides,
  };
}

export function page<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results };
}
