import type { VehicleSpec } from "./types";

export interface NewCaseVehicleForm {
  vin: string;
  year: string;
  make: string;
  model: string;
  trim: string;
  engine: string;
  transmission: string;
  drivetrain: string;
  fuel_type: string;
  body_style: string;
}

export function normalizeVinInput(value: string): string {
  return value.toUpperCase().replace(/[\s-]+/g, "");
}

export function isValidModernVin(value: string): boolean {
  return /^[A-HJ-NPR-Z0-9]{17}$/.test(normalizeVinInput(value));
}

export function applyDecodedVehicleToForm<T extends NewCaseVehicleForm>(form: T, vehicle: VehicleSpec): T {
  return {
    ...form,
    vin: normalizeVinInput(vehicle.vin || form.vin),
    year: vehicle.year ? String(vehicle.year) : form.year,
    make: vehicle.make || form.make,
    model: vehicle.model || form.model,
    trim: vehicle.trim || form.trim,
    engine: vehicle.engine || form.engine,
    transmission: vehicle.transmission || form.transmission,
    drivetrain: vehicle.drivetrain || form.drivetrain,
    fuel_type: vehicle.fuel_type || form.fuel_type,
    body_style: vehicle.body_style || form.body_style,
  };
}

/**
 * Keep NHTSA's mechanical fields only while they still belong to the VIN that
 * was decoded. Visible fields remain editable and always win over the decode.
 */
export function vehicleSpecForCase(form: NewCaseVehicleForm, decodedVehicle?: VehicleSpec): VehicleSpec {
  const vin = normalizeVinInput(form.vin);
  const decodedVin = normalizeVinInput(decodedVehicle?.vin || "");
  const decodedMatches = Boolean(vin && decodedVin && vin === decodedVin);
  const year = Number(form.year);

  return {
    ...(decodedMatches ? decodedVehicle : {}),
    vin: vin || undefined,
    year: form.year && Number.isFinite(year) ? year : undefined,
    make: form.make.trim() || undefined,
    model: form.model.trim() || undefined,
    trim: form.trim.trim() || undefined,
    engine: form.engine.trim() || undefined,
    transmission: form.transmission.trim() || undefined,
    drivetrain: form.drivetrain.trim() || undefined,
    fuel_type: form.fuel_type.trim() || undefined,
    body_style: form.body_style.trim() || undefined,
  };
}
