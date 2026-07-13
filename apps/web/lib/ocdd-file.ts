import type { Language } from "./types";

export const OCDD_MIN_PASSPHRASE_LENGTH = 8;

export function normalizeOcddPassphrase(value: string): string {
  return value.trim();
}

export function ocddPassphraseError(value: string, language: Language): string | undefined {
  if (normalizeOcddPassphrase(value).length >= OCDD_MIN_PASSPHRASE_LENGTH) return undefined;
  return language === "zh-CN"
    ? `口令至少需要 ${OCDD_MIN_PASSPHRASE_LENGTH} 个字符。`
    : `Passphrase must be at least ${OCDD_MIN_PASSPHRASE_LENGTH} characters.`;
}

export function ocddFileError(filename: string | undefined, language: Language): string | undefined {
  if (filename?.toLowerCase().endsWith(".ocdd")) return undefined;
  return language === "zh-CN" ? "请选择一个 .ocdd 案件文件。" : "Choose an .ocdd case file.";
}

export async function blobToBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return globalThis.btoa(binary);
}

export function ocddDownloadName(caseId: string): string {
  const safe = caseId.replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80);
  return `${safe || "case"}.ocdd`;
}
