import type { ExtractedListing } from "./types";
import { listingChannelFromUrl } from "./provider";

function text(value: unknown, max: number): string | undefined {
  if (typeof value !== "string") return undefined;
  const cleaned = value.replace(/\s+/g, " ").trim().slice(0, max);
  return cleaned || undefined;
}

function positiveNumber(value: unknown): number | undefined {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) && number >= 0 ? number : undefined;
}

export function sanitizeListing(input: Partial<ExtractedListing>): ExtractedListing {
  const url = text(input.source_url, 2048) || "";
  const channel = listingChannelFromUrl(url);
  const vin = text(input.vin, 17)?.toUpperCase().replace(/[^A-HJ-NPR-Z0-9]/g, "");

  return {
    source_url: url,
    title: text(input.title, 180) || "Untitled vehicle listing",
    asking_price: positiveNumber(input.asking_price),
    mileage: positiveNumber(input.mileage),
    currency: "USD",
    location: text(input.location, 120),
    seller_type: input.seller_type === "private" || input.seller_type === "dealer" ? input.seller_type : "unknown",
    channel,
    vin: vin?.length === 17 ? vin : undefined,
    year: positiveNumber(input.year),
    make: text(input.make, 60),
    model: text(input.model, 80),
    trim: text(input.trim, 80),
    engine: text(input.engine, 100),
    transmission: text(input.transmission, 100),
    drivetrain: text(input.drivetrain, 60),
    captured_at: text(input.captured_at, 40) || new Date().toISOString(),
    extraction_notes: Array.isArray(input.extraction_notes)
      ? input.extraction_notes.filter((item): item is string => typeof item === "string").map((item) => item.slice(0, 180)).slice(0, 10)
      : [],
  };
}

export function listingApiPayload(listing: ExtractedListing) {
  const { captured_at: _captured, extraction_notes: _notes, ...allowed } = sanitizeListing(listing);
  const channel = allowed.channel === "general_web" ? "other" : allowed.channel;
  return {
    listings: [
      {
        ...allowed,
        channel,
        is_target: true,
      },
    ],
  };
}

export function caseAccessHeaders(token: string | undefined): Record<string, string> {
  const capability = typeof token === "string" ? token.trim() : "";
  return capability ? { "X-OCDD-Case-Token": capability } : {};
}
