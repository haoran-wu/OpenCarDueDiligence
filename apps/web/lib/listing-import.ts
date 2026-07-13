import type { CaseRecord, ListingImportInput, VehicleSpec } from "./types";

export type ListingRole = "target" | "comparable";

export interface ListingImportForm {
  role: ListingRole;
  source_url: string;
  title: string;
  asking_price: string;
  mileage: string;
  location: string;
  channel: string;
  seller_type: "private" | "dealer" | "unknown";
  reference_kind: "asking" | "sold" | "reference";
  listed_date: string;
  distance_miles: string;
  vin: string;
  year: string;
  make: string;
  model: string;
  trim: string;
  generation: string;
  platform: string;
  engine: string;
  transmission: string;
  drivetrain: string;
  production_date: string;
  fuel_type: string;
  body_style: string;
  copied_configuration: boolean;
}

function stringValue(value: string | number | undefined): string {
  return value === undefined ? "" : String(value);
}

function vehicleFields(vehicle: VehicleSpec) {
  return {
    vin: vehicle.vin || "",
    year: stringValue(vehicle.year),
    make: vehicle.make || "",
    model: vehicle.model || "",
    trim: vehicle.trim || "",
    generation: vehicle.generation || "",
    platform: vehicle.platform || "",
    engine: vehicle.engine || "",
    transmission: vehicle.transmission || "",
    drivetrain: vehicle.drivetrain || "",
    production_date: vehicle.production_date || "",
    fuel_type: vehicle.fuel_type || "unknown",
    body_style: vehicle.body_style || "",
  };
}

export function targetListingImportForm(record: CaseRecord): ListingImportForm {
  return {
    role: "target",
    source_url: record.listing.source_url || "",
    title: record.listing.title || record.name,
    asking_price: stringValue(record.listing.asking_price),
    mileage: stringValue(record.listing.mileage),
    location: record.listing.location || "",
    channel: record.listing.channel || "facebook_marketplace",
    seller_type: record.listing.seller_type || "unknown",
    reference_kind: record.listing.reference_kind || "asking",
    listed_date: record.listing.listed_at?.slice(0, 10) || "",
    distance_miles: "",
    ...vehicleFields(record.vehicle),
    copied_configuration: false,
  };
}

export function comparableListingImportForm(record: CaseRecord): ListingImportForm {
  return {
    role: "comparable",
    source_url: "",
    title: "",
    asking_price: "",
    mileage: "",
    location: "",
    // Keep the channel and seller population visible and editable. These are
    // needed by deterministic admission, but the user must still verify them.
    channel: record.listing.channel || "facebook_marketplace",
    seller_type: record.listing.seller_type || "unknown",
    reference_kind: record.listing.reference_kind || "asking",
    listed_date: "",
    distance_miles: "",
    vin: "",
    year: "",
    make: "",
    model: "",
    trim: "",
    generation: "",
    platform: "",
    engine: "",
    transmission: "",
    drivetrain: "",
    production_date: "",
    fuel_type: "unknown",
    body_style: "",
    copied_configuration: false,
  };
}

export function copyResolvedTargetConfiguration(
  form: ListingImportForm,
  vehicle: VehicleSpec,
): ListingImportForm {
  const { vin: _targetVin, ...configuration } = vehicleFields(vehicle);
  return {
    ...form,
    ...configuration,
    copied_configuration: true,
  };
}

function optionalText(value: string): string | undefined {
  const normalized = value.trim();
  return normalized || undefined;
}

function optionalNumber(value: string): number | undefined {
  const normalized = value.trim();
  if (!normalized) return undefined;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function listingImportPayload(form: ListingImportForm): ListingImportInput {
  const payload: ListingImportInput = {
    title: form.title.trim(),
    asking_price: Number(form.asking_price),
    currency: "USD",
    seller_type: form.seller_type,
    channel: form.channel,
    reference_kind: form.reference_kind,
    fuel_type: form.fuel_type || "unknown",
    is_target: form.role === "target",
  };

  const optionalValues: Partial<ListingImportInput> = {
    source_url: optionalText(form.source_url),
    mileage: optionalNumber(form.mileage),
    location: optionalText(form.location),
    listed_at: form.listed_date ? `${form.listed_date}T12:00:00.000Z` : undefined,
    distance_miles: optionalNumber(form.distance_miles),
    vin: optionalText(form.vin) ? form.vin.trim().toUpperCase() : undefined,
    year: optionalNumber(form.year),
    make: optionalText(form.make),
    model: optionalText(form.model),
    trim: optionalText(form.trim),
    generation: optionalText(form.generation),
    platform: optionalText(form.platform),
    engine: optionalText(form.engine),
    transmission: optionalText(form.transmission),
    drivetrain: optionalText(form.drivetrain),
    production_date: optionalText(form.production_date),
    body_style: optionalText(form.body_style),
  };

  Object.assign(
    payload,
    Object.fromEntries(Object.entries(optionalValues).filter(([, value]) => value !== undefined)),
  );
  return payload;
}

export function listingImportVehicle(payload: ListingImportInput): VehicleSpec {
  const vehicle: VehicleSpec = {};
  if (payload.vin !== undefined) vehicle.vin = payload.vin;
  if (payload.year !== undefined) vehicle.year = payload.year;
  if (payload.make !== undefined) vehicle.make = payload.make;
  if (payload.model !== undefined) vehicle.model = payload.model;
  if (payload.trim !== undefined) vehicle.trim = payload.trim;
  if (payload.generation !== undefined) vehicle.generation = payload.generation;
  if (payload.platform !== undefined) vehicle.platform = payload.platform;
  if (payload.engine !== undefined) vehicle.engine = payload.engine;
  if (payload.transmission !== undefined) vehicle.transmission = payload.transmission;
  if (payload.drivetrain !== undefined) vehicle.drivetrain = payload.drivetrain;
  if (payload.production_date !== undefined) vehicle.production_date = payload.production_date;
  // Match the API target-refresh rule: an explicit unknown is not evidence
  // that should erase a previously resolved fuel type in demo/local state.
  if (payload.fuel_type !== undefined && payload.fuel_type !== "unknown") {
    vehicle.fuel_type = payload.fuel_type;
  }
  if (payload.body_style !== undefined) vehicle.body_style = payload.body_style;
  return vehicle;
}
