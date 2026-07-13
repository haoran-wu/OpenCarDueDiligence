import { describe, expect, it } from "vitest";
import { caseAccessHeaders, listingApiPayload, sanitizeListing } from "../src/payload";

describe("extension payload privacy boundary", () => {
  it("keeps only explicit listing fields", () => {
    const listing = sanitizeListing({
      source_url: "https://www.facebook.com/marketplace/item/123/",
      title: " 2014   MINI Cooper S ",
      asking_price: 5500,
      mileage: 120000,
      vin: "1TESTCAR000000001",
      captured_at: "2026-07-12T10:00:00Z",
      extraction_notes: ["review price"],
    });
    const payload = listingApiPayload(listing);
    expect(payload.listings[0]).toMatchObject({
      title: "2014 MINI Cooper S",
      asking_price: 5500,
      channel: "facebook_marketplace",
      is_target: true,
    });
    expect(payload.listings[0]).not.toHaveProperty("captured_at");
    expect(payload.listings[0]).not.toHaveProperty("extraction_notes");
    expect(JSON.stringify(payload)).not.toMatch(/cookie|chat|session/i);
  });

  it("drops malformed VINs and negative values", () => {
    const listing = sanitizeListing({ source_url: "https://example.com/car", title: "Car", vin: "NOT-A-VIN", asking_price: -1, mileage: -2 });
    expect(listing.vin).toBeUndefined();
    expect(listing.asking_price).toBeUndefined();
    expect(listing.mileage).toBeUndefined();
    expect(listing.channel).toBe("general_web");
    expect(listingApiPayload(listing).listings[0].channel).toBe("other");
  });

  it("keeps zero asking price as an explicit value", () => {
    const listing = sanitizeListing({ source_url: "https://example.com/car", title: "Project car", asking_price: 0 });
    expect(listingApiPayload(listing).listings[0].asking_price).toBe(0);
  });

  it("adds a cloud capability only as an explicit request header", () => {
    expect(caseAccessHeaders(undefined)).toEqual({});
    expect(caseAccessHeaders("  secret-capability  ")).toEqual({
      "X-OCDD-Case-Token": "secret-capability",
    });
  });
});
