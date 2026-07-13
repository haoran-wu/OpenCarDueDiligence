# NHTSA and vPIC integration

OpenCarDueDiligence uses only the official U.S. National Highway Traffic
Safety Administration endpoints in this first-party provider:

- VIN attributes: [NHTSA vPIC API](https://vpic.nhtsa.dot.gov/api/Home/Index),
  `DecodeVinValuesExtended` in JSON format.
- Model-level recall signals: [NHTSA recalls API](https://www.nhtsa.gov/nhtsa-datasets-and-apis),
  `recallsByVehicle` by model year, make, and model.
- Final VIN check: [NHTSA VIN recall lookup](https://www.nhtsa.gov/recalls).

The routes are:

```text
POST /v1/vehicles/decode-vin
POST /v1/vehicles/recall-signals
```

VIN decode request bodies use `{"vin":"...","modelYear":2014}`. VINs are
never accepted in the application URL because paths and query strings are
commonly retained by access proxies and server logs.

Example recall request:

```json
{
  "modelYear": 2014,
  "make": "MINI",
  "model": "Cooper"
}
```

Every response includes a `SourceEnvelope` with the exact official query URL,
provider, observation time, source-response SHA-256, credential policy, and
retention statement. Upstream responses are not silently replaced with
unattributed cached or third-party data.

These two endpoints do not expose a dataset-snapshot timestamp in their normal
response. Consequently, `lastUpdatedAt` is set to the same timestamp as
`observedAt`; it records when this exact response was observed, not when NHTSA
last changed its underlying dataset.

## Hard limitations

vPIC fields describe what NHTSA can decode from manufacturer submissions. A
successful decode does **not** verify title, ownership, odometer accuracy,
mechanical condition, accident history, exact installed options, or recall
status. Missing decoded attributes remain unknown.

The public `recallsByVehicle` endpoint is keyed by **model year, make, and
model**. Its records are signals for that model combination. They do **not**
prove that a particular VIN:

- is inside the affected production population;
- currently has an open recall; or
- has or has not received the remedy.

The API therefore always returns `vehicleSpecific: false` and
`vinCompletionVerified: false`. A buyer must run the actual VIN through the
official NHTSA recall lookup and, where appropriate, confirm completion with an
OEM dealer. OpenCarDueDiligence must never turn a model-level recall result into
a green VIN-level completion status.

The implementation and links above were manually reviewed on 2026-07-12.
