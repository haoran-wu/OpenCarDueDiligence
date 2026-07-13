import { describe, expect, it } from "vitest";
import { applyDecodedVehicleToForm, isValidModernVin, normalizeVinInput, vehicleSpecForCase } from "../lib/new-case";

const vin = "1TESTCAR000000001";
const decoded = {
  vin,
  year: 2014,
  make: "MINI",
  model: "Hardtop",
  trim: "Cooper S",
  engine: "B48 / 2.0L / 4 cylinders / In-Line",
  transmission: "Automatic / 6 speeds",
  drivetrain: "FWD/Front-Wheel Drive",
  fuel_type: "gasoline",
  body_style: "Hatchback/Liftback/Notchback",
};

describe("new-case VIN decode handoff", () => {
  it("normalizes pasted VINs and rejects forbidden VIN letters", () => {
    expect(normalizeVinInput("1testcar-000000001 ")).toBe(vin);
    expect(isValidModernVin(vin)).toBe(true);
    expect(isValidModernVin("1TESTCIR000000001")).toBe(false);
  });

  it("fills visible fields while preserving decoded mechanical fields for case creation", () => {
    const form = applyDecodedVehicleToForm({ vin, year: "", make: "", model: "", trim: "", engine: "", transmission: "", drivetrain: "", fuel_type: "", body_style: "" }, decoded);
    const editedForm = { ...form, model: "Hardtop 2 Door" };

    expect(vehicleSpecForCase(editedForm, decoded)).toEqual({
      ...decoded,
      model: "Hardtop 2 Door",
    });
  });

  it("drops decoded mechanical fields when the user changes the VIN", () => {
    const vehicle = vehicleSpecForCase({ vin: "2TESTCAR000000002", year: "2003", make: "Honda", model: "Accord", trim: "", engine: "", transmission: "", drivetrain: "", fuel_type: "", body_style: "" }, decoded);

    expect(vehicle).toEqual({
      vin: "2TESTCAR000000002",
      year: 2003,
      make: "Honda",
      model: "Accord",
      trim: undefined,
      engine: undefined,
      transmission: undefined,
      drivetrain: undefined,
      fuel_type: undefined,
      body_style: undefined,
    });
    expect(vehicle.engine).toBeUndefined();
  });
});
