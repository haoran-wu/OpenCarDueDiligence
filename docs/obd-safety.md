# OBD safety contract

The bundled bridge is intentionally diagnostic and read-only.

Allowed service families are limited to:

- Mode 01 readiness plus a fixed, reviewed subset of current emissions PIDs
- Mode 02 frame-zero values for that same fixed PID subset
- Mode 03 stored emissions DTCs
- Mode 07 pending emissions DTCs
- Mode 09 vehicle information/VIN
- Mode 0A permanent emissions DTCs

The bridge rejects clear-code, ECU reset, security access, output control,
coding, routine-control and programming commands. It exposes no arbitrary
command endpoint. Even within read-only Mode 01/02, a PID is rejected unless it
is part of the source-controlled allowlist. Mode 04 never reaches a transport.

A generic ELM327 scan normally covers emissions-related powertrain data only.
ABS, SRS, body, steering, hybrid and manufacturer-enhanced modules remain
unknown unless an imported full-system scan proves they were queried.

Permanent codes can remain after a repair, and not-ready monitors can follow a
battery event or code clear. Neither fact by itself proves fraud or a current
failed part.
