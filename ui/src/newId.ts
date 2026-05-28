/** Message/session ids; works on http:// LAN IPs where `crypto.randomUUID` is blocked. */
export function newId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    try {
      return crypto.randomUUID();
    } catch {
      /* non-secure context (e.g. http://10.x.x.x:8003) */
    }
  }
  return `id-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
