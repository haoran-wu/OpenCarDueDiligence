import type {
  DiagnosticCode,
  ListingSnapshot,
  SourceEnvelope,
  VehicleSpec,
} from "@ocdd/contracts";

export interface ProviderPolicy {
  id: string;
  displayName: string;
  license: string;
  accessCost: "free" | "user-supplied-artifact";
  credentialPolicy: "none" | "bring-your-own" | "server-managed";
  retentionPolicy: string;
  redistributionAllowed: boolean;
  termsUrl?: string;
}

export interface ListingProvider {
  policy: ProviderPolicy;
  import(input: unknown): Promise<{ source: SourceEnvelope; listings: ListingSnapshot[] }>;
}

export interface HistoryProvider {
  policy: ProviderPolicy;
  parse(input: Uint8Array | string): Promise<{ source: SourceEnvelope; facts: unknown[] }>;
}

export interface MarketDataProvider {
  policy: ProviderPolicy;
  comparables(vehicle: VehicleSpec, region: string): Promise<ListingSnapshot[]>;
}

export interface RepairCostProvider {
  policy: ProviderPolicy;
  estimate(input: { vehicle: VehicleSpec; repairKey: string; zip3?: string }): Promise<unknown>;
}

export interface DtcDefinitionProvider {
  policy: ProviderPolicy;
  define(code: DiagnosticCode, vehicle?: VehicleSpec): Promise<unknown>;
}

export interface StateRuleProvider {
  policy: ProviderPolicy;
  plan(context: unknown): Promise<unknown>;
}

export interface LLMProvider {
  policy: ProviderPolicy;
  explain(groundedContext: unknown, locale: "en" | "zh-CN"): Promise<string>;
}
