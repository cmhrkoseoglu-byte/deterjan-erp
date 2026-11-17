// Kişiye özel yetkilerin sorgu anahtarları (api/access.ts testlerde taklit edildiği için ayrı dosya).
export const accessKeys = {
  user: (id: number) => ["system", "users", id, "access"] as const,
  history: (id: number, page = 1) => ["system", "users", id, "access", "history", page] as const,
  holders: (key: string, level: string) => ["access", "report", "holders", key, level] as const,
  mine: ["auth", "me", "access"] as const,
};
