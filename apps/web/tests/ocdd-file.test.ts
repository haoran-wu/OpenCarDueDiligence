import { describe, expect, it } from "vitest";
import {
  blobToBase64,
  normalizeOcddPassphrase,
  ocddDownloadName,
  ocddFileError,
  ocddPassphraseError,
} from "../lib/ocdd-file";

describe("encrypted .ocdd file boundaries", () => {
  it("requires eight non-edge-whitespace passphrase characters", () => {
    expect(ocddPassphraseError("1234567", "en")).toContain("at least 8");
    expect(ocddPassphraseError(" 1234567 ", "zh-CN")).toContain("至少需要 8");
    expect(ocddPassphraseError(" 12345678 ", "en")).toBeUndefined();
    expect(normalizeOcddPassphrase(" 12345678 ")).toBe("12345678");
  });

  it("accepts only the encrypted archive extension and sanitizes downloads", () => {
    expect(ocddFileError("buyer-case.OCDD", "en")).toBeUndefined();
    expect(ocddFileError("buyer-case.zip", "en")).toContain(".ocdd");
    expect(ocddDownloadName("../case id?<script>")).toBe("case-id-script.ocdd");
  });

  it("base64 encodes archive bytes without treating them as text", async () => {
    const encoded = await blobToBase64(new Blob([new Uint8Array([0, 1, 127, 128, 255])]));
    expect(encoded).toBe("AAF/gP8=");
  });
});
