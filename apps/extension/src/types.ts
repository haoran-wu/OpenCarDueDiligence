export interface ExtractedListing {
  source_url: string;
  title: string;
  asking_price?: number;
  mileage?: number;
  currency: "USD";
  location?: string;
  seller_type: "private" | "dealer" | "unknown";
  channel: "facebook_marketplace" | "craigslist" | "cars_com" | "autotrader" | "general_web";
  vin?: string;
  year?: number;
  make?: string;
  model?: string;
  trim?: string;
  engine?: string;
  transmission?: string;
  drivetrain?: string;
  captured_at: string;
  extraction_notes: string[];
}

export interface ComposerTarget {
  found: boolean;
  label?: string;
  kind?: string;
  existing_length?: number;
  reason?: string;
}
