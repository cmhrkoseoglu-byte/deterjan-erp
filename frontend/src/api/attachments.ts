// Kayda bağlı dosya ekleri: /api/v1/attachments/ (lot, mal kabul, numune, yorum).
import { api } from "./client";

export type AttachmentKind = "SUPPLIER_COA" | "PHOTO" | "DELIVERY_NOTE" | "DOCUMENT" | "OTHER";

export interface Attachment {
  id: number;
  content_type: string;
  object_id: number;
  kind: AttachmentKind;
  kind_display: string;
  original_name: string;
  size: number;
  mime_type: string;
  note: string;
  is_active: boolean;
  uploaded_by_name: string | null;
  created_at: string;
  removed_at: string | null;
  removed_by_name: string | null;
  removal_reason: string;
  download_url: string;
  can_remove: boolean;
}

export async function listAttachments(
  contentType: string,
  objectId: number,
): Promise<Attachment[]> {
  const { data } = await api.get<Attachment[]>("/attachments/", {
    params: { content_type: contentType, object_id: objectId },
  });
  return data;
}

export async function uploadAttachment(
  contentType: string,
  objectId: number,
  file: File | Blob,
  options: { kind: AttachmentKind; note?: string; filename?: string },
): Promise<Attachment> {
  const form = new FormData();
  form.append("content_type", contentType);
  form.append("object_id", String(objectId));
  form.append("kind", options.kind);
  if (options.note) form.append("note", options.note);
  const name = options.filename ?? (file instanceof File ? file.name : "dosya");
  form.append("file", file, name);
  const { data } = await api.post<Attachment>("/attachments/", form);
  return data;
}

export async function removeAttachment(id: number, reason = ""): Promise<Attachment> {
  const { data } = await api.post<Attachment>(`/attachments/${id}/remove/`, { reason });
  return data;
}

export const attachmentKeys = {
  list: (contentType: string, objectId: number) => ["attachments", contentType, objectId] as const,
};
