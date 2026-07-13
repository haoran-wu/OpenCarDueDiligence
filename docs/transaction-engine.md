# Transaction engine

The transaction engine treats ownership, insurance and permission to drive as
separate questions:

- a bill of sale documents the agreement;
- a title transfers ownership;
- insurance covers an insured risk;
- registration plus a valid plate or permit authorizes road use.

Having the first three does not automatically provide the fourth. When no
legal registration/plate/permit path is confirmed, the generated plan defaults
to tow, trailer or temporary storage.

State rule packs are dated and cite official sources. The initial private-sale
packs cover:

- [New Jersey MVC](https://www.nj.gov/mvc/vehicles/transowner.htm)
- [New York DMV](https://dmv.ny.gov/titles/buy-sell-or-transfer-vehicle-ownership)
- [Connecticut DMV](https://portal.ct.gov/dmv/vehicle-services/sell-vehicle)

The engine is decision support, not legal advice. It must return unknown or
needs-verification rather than invent a form, deadline, fee or permit rule.
