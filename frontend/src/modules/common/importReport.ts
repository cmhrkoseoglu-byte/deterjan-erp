import axios from "axios";
import type { ImportReport } from "../../api/masterdata";

/** 400 `import_has_errors` yanıtındaki raporu çıkarır. */
export function reportFromError(error: unknown): ImportReport | null {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as { report?: ImportReport } | undefined;
    return data?.report ?? null;
  }
  return null;
}
