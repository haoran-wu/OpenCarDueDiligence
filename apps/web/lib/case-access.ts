const STORAGE_KEY = "ocdd.case-capabilities.v1";
let volatileCapabilities: Record<string, string> = {};

function readCapabilities(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const parsed = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const capabilities: Record<string, string> = {};
    for (const [caseId, token] of Object.entries(parsed)) {
      if (caseId && typeof token === "string" && token.length >= 20) capabilities[caseId] = token;
    }
    return { ...capabilities, ...volatileCapabilities };
  } catch {
    return { ...volatileCapabilities };
  }
}

function writeCapabilities(value: Record<string, string>) {
  volatileCapabilities = { ...value };
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Storage can be disabled by browser policy. The in-memory copy keeps the
    // current tab usable without exposing the capability elsewhere.
  }
}

/**
 * Capability tokens are stored by opaque case ID, never placed in URLs,
 * rendered, or logged. They intentionally expire with the browser tab/session
 * instead of being persisted as durable local-site data.
 */
export function rememberCaseAccess(caseId: string, accessToken?: string): void {
  if (!accessToken) return;
  writeCapabilities({ ...readCapabilities(), [caseId]: accessToken });
}

export function caseAccessFor(caseId: string): { accessToken: string } | undefined {
  const accessToken = readCapabilities()[caseId];
  return accessToken ? { accessToken } : undefined;
}

export function knownCaseAccesses(): Array<{ caseId: string; accessToken: string }> {
  return Object.entries(readCapabilities()).map(([caseId, accessToken]) => ({ caseId, accessToken }));
}

export function accessTokenMap(caseIds: string[]): Record<string, string> {
  const known = readCapabilities();
  return Object.fromEntries(caseIds.flatMap((caseId) => known[caseId] ? [[caseId, known[caseId]]] : []));
}

export function forgetCaseAccess(caseId: string): void {
  const known = readCapabilities();
  delete known[caseId];
  writeCapabilities(known);
}
