import { describe, expect, it } from "vitest";
import { demoCases } from "../lib/demo";
import {
  comparableListingImportForm,
  copyResolvedTargetConfiguration,
  listingImportPayload,
  listingImportVehicle,
  targetListingImportForm,
} from "../lib/listing-import";

describe("evidence-honest listing import", () => {
  const record = demoCases[0];

  it("prefills a target refresh from the resolved case and current target snapshot", () => {
    const form = targetListingImportForm(record);

    expect(form).toMatchObject({
      role: "target",
      title: "2017 Toyota Corolla LE — synthetic demo",
      asking_price: "8200",
      mileage: "88400",
      seller_type: "private",
      channel: "facebook_marketplace",
      vin: "1TESTCAR000000001",
      year: "2017",
      make: "Toyota",
      model: "Corolla",
      trim: "LE",
      generation: "E170",
      platform: "E170",
      engine: "1.8L 2ZR-FE I4",
      transmission: "CVT",
      drivetrain: "FWD",
      fuel_type: "gasoline",
    });
  });

  it("starts a comparable without silently claiming target configuration facts", () => {
    const form = comparableListingImportForm(record);

    expect(form.role).toBe("comparable");
    expect(form.seller_type).toBe("private");
    expect(form.channel).toBe("facebook_marketplace");
    expect(form.reference_kind).toBe("asking");
    expect(form.year).toBe("");
    expect(form.make).toBe("");
    expect(form.model).toBe("");
    expect(form.engine).toBe("");
    expect(form.vin).toBe("");
    expect(form.copied_configuration).toBe(false);
  });

  it("copies the target configuration only after an explicit action and marks it for verification", () => {
    const copied = copyResolvedTargetConfiguration(
      comparableListingImportForm(record),
      record.vehicle,
    );

    expect(copied).toMatchObject({
      role: "comparable",
      copied_configuration: true,
      year: "2017",
      make: "Toyota",
      model: "Corolla",
      engine: "1.8L 2ZR-FE I4",
      transmission: "CVT",
      drivetrain: "FWD",
      vin: "",
    });
  });

  it("builds the full comparable payload used by deterministic matching", () => {
    const payload = listingImportPayload({
      ...copyResolvedTargetConfiguration(comparableListingImportForm(record), record.vehicle),
      source_url: "https://example.com/comparable/42",
      title: "Verified sold comparable",
      asking_price: "7900",
      mileage: "90500",
      location: "Example City, NJ",
      reference_kind: "sold",
      listed_date: "2026-06-20",
      distance_miles: "42.5",
      production_date: "2017-03-01",
      body_style: "sedan",
    });

    expect(payload).toEqual({
      source_url: "https://example.com/comparable/42",
      title: "Verified sold comparable",
      asking_price: 7900,
      mileage: 90500,
      currency: "USD",
      location: "Example City, NJ",
      listed_at: "2026-06-20T12:00:00.000Z",
      seller_type: "private",
      channel: "facebook_marketplace",
      reference_kind: "sold",
      year: 2017,
      make: "Toyota",
      model: "Corolla",
      trim: "LE",
      generation: "E170",
      platform: "E170",
      engine: "1.8L 2ZR-FE I4",
      transmission: "CVT",
      drivetrain: "FWD",
      production_date: "2017-03-01",
      fuel_type: "gasoline",
      body_style: "sedan",
      distance_miles: 42.5,
      is_target: false,
    });
  });

  it("omits unverified optional comparable facts from the serialized payload", () => {
    const payload = listingImportPayload({
      ...comparableListingImportForm(record),
      title: "Sparse comparable",
      asking_price: "7500",
    });
    const serialized = JSON.parse(JSON.stringify(payload));

    expect(serialized.is_target).toBe(false);
    expect(serialized).not.toHaveProperty("year");
    expect(serialized).not.toHaveProperty("make");
    expect(serialized).not.toHaveProperty("listed_at");
    expect(serialized).not.toHaveProperty("distance_miles");
  });

  it("does not erase a resolved fuel type when a target refresh leaves it unknown", () => {
    const payload = listingImportPayload({
      ...targetListingImportForm(record),
      fuel_type: "unknown",
    });

    expect(listingImportVehicle(payload)).not.toHaveProperty("fuel_type");
  });

  it("normalizes an explicitly entered listing VIN and carries it into the target vehicle", () => {
    const payload = listingImportPayload({
      ...targetListingImportForm(record),
      vin: " 1testcar000000001 ",
    });

    expect(payload.vin).toBe("1TESTCAR000000001");
    expect(listingImportVehicle(payload).vin).toBe("1TESTCAR000000001");
  });
});
