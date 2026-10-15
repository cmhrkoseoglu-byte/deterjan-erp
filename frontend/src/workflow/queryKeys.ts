import type { RecordRef, TaskQuery } from "../api/workflow";

export const workflowKeys = {
  all: ["workflow"] as const,
  tasks: ["workflow", "tasks"] as const,
  taskList: (query: TaskQuery) => ["workflow", "tasks", query] as const,
  notifications: ["workflow", "notifications"] as const,
  unreadCount: ["workflow", "notifications", "unread-count"] as const,
  notificationList: (unread: boolean) => ["workflow", "notifications", "list", unread] as const,
  notificationPreview: ["workflow", "notifications", "preview"] as const,
  comments: (record: RecordRef) =>
    ["workflow", "comments", record.contentType, record.objectId] as const,
  history: (record: RecordRef) =>
    ["workflow", "history", record.contentType, record.objectId] as const,
  mentionable: (search: string) => ["workflow", "mentionable", search] as const,
};
