import "./popup.css";
import { caseAccessHeaders, listingApiPayload, sanitizeListing } from "./payload";
import type { ComposerTarget, ExtractedListing } from "./types";

const $ = <T extends HTMLElement>(selector: string) => {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`Missing extension element: ${selector}`);
  return element;
};

const extractButton = $("#extract") as HTMLButtonElement;
const importButton = $("#import") as HTMLButtonElement;
const confirmImport = $("#confirm-import") as HTMLInputElement;
const preview = $("#preview");
const status = $("#status");
const messageText = $("#message-text") as HTMLTextAreaElement;
const inspectTargetButton = $("#inspect-target") as HTMLButtonElement;
const fillMessageButton = $("#fill-message") as HTMLButtonElement;
const targetPreview = $("#target-preview");
const overwriteRow = $("#overwrite-row");
const allowOverwrite = $("#allow-overwrite") as HTMLInputElement;

let currentListing: ExtractedListing | undefined;
let currentTarget: ComposerTarget | undefined;

function showStatus(message: string, kind: "ok" | "error" | "info" = "info") {
  status.textContent = message;
  status.className = `status show ${kind}`;
  window.setTimeout(() => {
    status.className = "status";
  }, 4200);
}

async function activeTabId(): Promise<number> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) throw new Error("No active web page is available.");
  if (!tab.url || !/^https?:/i.test(tab.url)) throw new Error("Open a normal http(s) listing page first.");
  return tab.id;
}

function extractionScript(): Partial<ExtractedListing> {
  const normalized = (value: string | null | undefined) => (value || "").replace(/\s+/g, " ").trim();
  const visible = (element: Element) => {
    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const isPrivateUi = (element: Element) => Boolean(
    element.closest("[aria-label*='conversation' i], [aria-label*='messages' i], [data-pagelet^='ChatTab'], [role='textbox']"),
  );
  const shortVisibleTexts = Array.from(document.querySelectorAll("h1,h2,[role='heading'],span,div"))
    .filter((element) => visible(element) && !isPrivateUi(element))
    .map((element) => normalized(element.textContent))
    .filter((value) => value.length > 0 && value.length < 220);

  const host = location.hostname.toLowerCase();
  const channel = host.includes("facebook.com")
    ? "facebook_marketplace"
    : host.includes("craigslist.org")
      ? "craigslist"
      : host.includes("cars.com")
        ? "cars_com"
        : host.includes("autotrader.com")
          ? "autotrader"
          : "general_web";

  let structured: Record<string, unknown> | undefined;
  for (const script of Array.from(document.querySelectorAll<HTMLScriptElement>('script[type="application/ld+json"]'))) {
    try {
      const parsed = JSON.parse(script.textContent || "null") as unknown;
      const entries = Array.isArray(parsed) ? parsed : [parsed];
      const candidate = entries.find((entry) => {
        if (!entry || typeof entry !== "object") return false;
        const type = (entry as { "@type"?: unknown })["@type"];
        return type === "Vehicle" || type === "Car" || type === "Product";
      });
      if (candidate && typeof candidate === "object") { structured = candidate as Record<string, unknown>; break; }
    } catch { /* Ignore invalid publisher metadata. */ }
  }

  const heading = Array.from(document.querySelectorAll("h1,[role='heading'][aria-level='1']"))
    .find((element) => visible(element) && normalized(element.textContent).length > 3);
  const structuredName = typeof structured?.name === "string" ? structured.name : undefined;
  const title = normalized(heading?.textContent) || normalized(structuredName) || normalized(document.title).replace(/\s*[|–-]\s*Facebook.*$/i, "");

  const offers = structured?.offers && typeof structured.offers === "object" ? structured.offers as Record<string, unknown> : undefined;
  const structuredPrice = Number(offers?.price);
  const priceText = shortVisibleTexts.find((value) => /^\$\s?\d[\d,]*(?:\.\d{2})?$/.test(value));
  const askingPrice = Number.isFinite(structuredPrice) && structuredPrice >= 0
    ? structuredPrice
    : priceText
      ? Number(priceText.replace(/[$,\s]/g, ""))
      : undefined;

  // Work only from the reviewed public-listing candidates above. We deliberately
  // do not read document.body.innerText because an open marketplace chat can be
  // mounted beside the listing.
  const listingText = shortVisibleTexts.join("\n").slice(0, 120000);
  const mileageMatch = listingText.match(/(?:Driven|Mileage\s*:?)\s*([\d,]+)\s*(?:mi|miles)/i);
  const mileage = mileageMatch ? Number(mileageMatch[1].replace(/,/g, "")) : undefined;
  const transmission = listingText.match(/\b(automatic|manual|cvt)\s+transmission\b/i)?.[0];
  const vin = listingText.match(/\b[A-HJ-NPR-Z0-9]{17}\b/)?.[0];
  const year = Number(title.match(/\b(19\d{2}|20\d{2})\b/)?.[1]);

  const fbLocation = shortVisibleTexts.find((value) => /^Listed .{0,80} in .{2,100}$/i.test(value));
  const locationFromFb = fbLocation?.match(/\sin\s+(.+)$/i)?.[1];
  const locationText = shortVisibleTexts.find((value) => /Location is approximate$/i.test(value));
  const locationFromApprox = locationText?.replace(/\s*Location is approximate$/i, "");
  const structuredAddress = structured?.itemOffered && typeof structured.itemOffered === "object"
    ? (structured.itemOffered as Record<string, unknown>).address
    : undefined;
  const locationValue = typeof structuredAddress === "string" ? structuredAddress : locationFromFb || locationFromApprox;

  const notes: string[] = [];
  if (!askingPrice) notes.push("Price was not confidently detected.");
  if (!mileage) notes.push("Mileage was not confidently detected.");
  if (channel === "general_web") notes.push("General page extraction; review every field.");

  return {
    source_url: location.href,
    title,
    asking_price: askingPrice,
    mileage,
    currency: "USD",
    location: locationValue,
    seller_type: listingText.includes("Seller information") ? "private" : "unknown",
    channel,
    vin,
    year: Number.isFinite(year) ? year : undefined,
    transmission,
    captured_at: new Date().toISOString(),
    extraction_notes: notes,
  };
}

function composerInspectionScript(): ComposerTarget {
  const visible = (element: Element) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 20 && rect.height > 10 && style.visibility !== "hidden" && style.display !== "none";
  };
  const selectors = [
    '[contenteditable="true"][role="textbox"]',
    'textarea[aria-label*="message" i]',
    'textarea[placeholder]',
    '[contenteditable="true"]',
    "textarea",
  ];
  let target: HTMLElement | undefined;
  for (const selector of selectors) {
    target = Array.from(document.querySelectorAll<HTMLElement>(selector)).find(visible);
    if (target) break;
  }
  if (!target) return { found: false, reason: "No visible message composer was found." };
  const label = target.getAttribute("aria-label") || target.getAttribute("placeholder") || "Visible text composer";
  const existing = target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement ? target.value : target.innerText;
  return { found: true, label: label.slice(0, 120), kind: target.tagName.toLowerCase(), existing_length: existing.trim().length };
}

function fillComposerScript(message: string, overwrite: boolean) {
  const visible = (element: Element) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 20 && rect.height > 10 && style.visibility !== "hidden" && style.display !== "none";
  };
  const selectors = [
    '[contenteditable="true"][role="textbox"]',
    'textarea[aria-label*="message" i]',
    'textarea[placeholder]',
    '[contenteditable="true"]',
    "textarea",
  ];
  let target: HTMLElement | undefined;
  for (const selector of selectors) {
    target = Array.from(document.querySelectorAll<HTMLElement>(selector)).find(visible);
    if (target) break;
  }
  if (!target) return { ok: false, reason: "No visible message composer was found." };
  const existing = target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement ? target.value : target.innerText;
  if (existing.trim() && !overwrite) return { ok: false, reason: "Composer already contains text. Confirm overwrite first." };

  target.focus();
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement) {
    const prototype = target instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
    if (setter) setter.call(target, message);
    else target.value = message;
  } else {
    target.textContent = message;
  }
  target.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: message }));
  target.dispatchEvent(new Event("change", { bubbles: true }));
  return { ok: true, reason: "Text filled. Review it on the page; Send was not clicked." };
}

function setInput(id: string, value: string | number | undefined) {
  const input = $(`#${id}`) as HTMLInputElement;
  input.value = value === undefined ? "" : String(value);
}

function listingFromForm(): ExtractedListing {
  if (!currentListing) throw new Error("Extract a listing first.");
  const listing = sanitizeListing({
    ...currentListing,
    title: ($<HTMLInputElement>("#listing-title")).value,
    asking_price: ($<HTMLInputElement>("#listing-price")).valueAsNumber,
    mileage: ($<HTMLInputElement>("#listing-mileage")).valueAsNumber,
    location: ($<HTMLInputElement>("#listing-location")).value,
    transmission: ($<HTMLInputElement>("#listing-transmission")).value,
    vin: ($<HTMLInputElement>("#listing-vin")).value,
    source_url: ($<HTMLInputElement>("#listing-url")).value,
  });
  if (listing.asking_price === undefined) {
    throw new Error("Review and enter the asking price before importing.");
  }
  return listing;
}

async function ensureApiPermission(apiBase: string): Promise<void> {
  const url = new URL(apiBase);
  if (!/^https?:$/.test(url.protocol)) throw new Error("API must use http or https.");
  const originPattern = `${url.origin}/*`;
  const hasPermission = await chrome.permissions.contains({ origins: [originPattern] });
  if (!hasPermission) {
    const granted = await chrome.permissions.request({ origins: [originPattern] });
    if (!granted) throw new Error("API origin permission was not granted.");
  }
}

extractButton.addEventListener("click", async () => {
  extractButton.disabled = true;
  extractButton.textContent = "Extracting…";
  try {
    const tabId = await activeTabId();
    const [{ result }] = await chrome.scripting.executeScript({ target: { tabId }, func: extractionScript });
    currentListing = sanitizeListing(result || {});
    setInput("listing-title", currentListing.title);
    setInput("listing-price", currentListing.asking_price);
    setInput("listing-mileage", currentListing.mileage);
    setInput("listing-location", currentListing.location);
    setInput("listing-transmission", currentListing.transmission);
    setInput("listing-vin", currentListing.vin);
    setInput("listing-url", currentListing.source_url);
    $("#source-label").textContent = currentListing.channel.replaceAll("_", " ");
    $("#captured-time").textContent = new Date(currentListing.captured_at).toLocaleString();
    preview.classList.remove("hidden");
    showStatus(currentListing.extraction_notes.length ? currentListing.extraction_notes.join(" ") : "Snapshot ready for review.", "ok");
  } catch (error) {
    showStatus(error instanceof Error ? error.message : "Could not extract this page.", "error");
  } finally {
    extractButton.disabled = false;
    extractButton.textContent = "Extract current listing";
  }
});

confirmImport.addEventListener("change", () => {
  importButton.disabled = !confirmImport.checked || !currentListing;
});

importButton.addEventListener("click", async () => {
  const caseId = ($<HTMLInputElement>("#case-id")).value.trim();
  const caseToken = ($<HTMLInputElement>("#case-token")).value;
  const apiBase = ($<HTMLInputElement>("#api-base")).value.trim().replace(/\/$/, "");
  if (!caseId) return showStatus("Enter the destination Case ID.", "error");
  importButton.disabled = true;
  importButton.textContent = "Importing…";
  try {
    await ensureApiPermission(apiBase);
    const listing = listingFromForm();
    const response = await fetch(`${apiBase}/v1/cases/${encodeURIComponent(caseId)}/listings/import`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...caseAccessHeaders(caseToken) },
      credentials: "omit",
      referrerPolicy: "no-referrer",
      body: JSON.stringify(listingApiPayload(listing)),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => undefined) as { detail?: string } | undefined;
      throw new Error(payload?.detail || `API returned ${response.status}`);
    }
    await chrome.storage.local.set({ apiBase, lastCaseId: caseId });
    ($<HTMLInputElement>("#case-token")).value = "";
    confirmImport.checked = false;
    showStatus("Imported. Only the reviewed snapshot fields were uploaded.", "ok");
  } catch (error) {
    showStatus(error instanceof Error ? error.message : "Import failed.", "error");
  } finally {
    importButton.textContent = "Confirm & import";
    importButton.disabled = !confirmImport.checked;
  }
});

inspectTargetButton.addEventListener("click", async () => {
  const message = messageText.value.trim();
  if (!message) return showStatus("Paste a reviewed message first.", "error");
  try {
    const tabId = await activeTabId();
    const [{ result }] = await chrome.scripting.executeScript({ target: { tabId }, func: composerInspectionScript });
    currentTarget = result;
    targetPreview.classList.remove("hidden");
    if (!result?.found) {
      targetPreview.className = "target-preview error";
      targetPreview.textContent = result?.reason || "No composer found.";
      fillMessageButton.disabled = true;
      return;
    }
    targetPreview.className = "target-preview ok";
    targetPreview.textContent = `${result.label} · ${result.kind} · ${result.existing_length || 0} existing characters`;
    const hasText = (result.existing_length || 0) > 0;
    overwriteRow.classList.toggle("hidden", !hasText);
    allowOverwrite.checked = false;
    fillMessageButton.disabled = hasText;
  } catch (error) {
    showStatus(error instanceof Error ? error.message : "Could not inspect the page.", "error");
  }
});

messageText.addEventListener("input", () => {
  currentTarget = undefined;
  fillMessageButton.disabled = true;
  targetPreview.classList.add("hidden");
});

allowOverwrite.addEventListener("change", () => {
  fillMessageButton.disabled = !allowOverwrite.checked || !currentTarget?.found;
});

fillMessageButton.addEventListener("click", async () => {
  if (!currentTarget?.found) return showStatus("Preview the page target again.", "error");
  try {
    const tabId = await activeTabId();
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      func: fillComposerScript,
      args: [messageText.value.trim(), allowOverwrite.checked],
    });
    if (!result?.ok) throw new Error(result?.reason || "Text was not filled.");
    showStatus("Text filled for review. Send was not clicked.", "ok");
    fillMessageButton.disabled = true;
  } catch (error) {
    showStatus(error instanceof Error ? error.message : "Could not fill the message.", "error");
  }
});

document.querySelectorAll<HTMLButtonElement>(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((item) => item.classList.toggle("active", item === tab));
    document.querySelectorAll(".panel").forEach((panel) => panel.classList.toggle("active", panel.id === `${tab.dataset.tab}-panel`));
  });
});

$("#save-settings").addEventListener("click", async () => {
  const apiBase = ($<HTMLInputElement>("#api-base")).value.trim().replace(/\/$/, "");
  try {
    const parsed = new URL(apiBase);
    if (!/^https?:$/.test(parsed.protocol)) throw new Error();
    await chrome.storage.local.set({ apiBase });
    showStatus("Settings saved locally.", "ok");
  } catch {
    showStatus("Enter a valid http(s) API URL.", "error");
  }
});

void chrome.storage.local.get(["apiBase", "lastCaseId"]).then((stored) => {
  if (typeof stored.apiBase === "string") ($<HTMLInputElement>("#api-base")).value = stored.apiBase;
  if (typeof stored.lastCaseId === "string") ($<HTMLInputElement>("#case-id")).value = stored.lastCaseId;
});
