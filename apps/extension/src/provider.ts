import type { ExtractedListing } from "./types";

type ListingChannel = ExtractedListing["channel"];

const PROVIDERS: ReadonlyArray<{ domain: string; channel: ListingChannel }> = [
  { domain: "facebook.com", channel: "facebook_marketplace" },
  { domain: "craigslist.org", channel: "craigslist" },
  { domain: "cars.com", channel: "cars_com" },
  { domain: "autotrader.com", channel: "autotrader" },
];

function isDomainOrSubdomain(hostname: string, domain: string): boolean {
  return hostname === domain || hostname.endsWith(`.${domain}`);
}

/**
 * Classify only normal HTTP(S) URLs whose parsed hostname is the provider's
 * exact domain or a real dot-delimited subdomain. Invalid URLs, other schemes,
 * and lookalike hosts deliberately fall back to the generic web contract.
 */
export function listingChannelFromUrl(value: string): ListingChannel {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return "general_web";
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "general_web";

  const hostname = parsed.hostname.toLowerCase();
  return PROVIDERS.find(({ domain }) => isDomainOrSubdomain(hostname, domain))?.channel ?? "general_web";
}
