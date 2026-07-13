# OCDD OBD bridge

This host-local service reads a reviewed subset of generic OBD-II through BLE
ELM327 adapters and returns a normalized scan to the main API. It cannot clear
codes, run actuator tests, reset adaptations, register batteries, code modules,
or program an ECU.

The normalized result includes stored/pending/permanent emissions DTCs,
readiness, the VIN when available, Mode 02 freeze-frame values for frame zero,
and a fixed subset of Mode 01 live PIDs (load, coolant temperature, manifold
pressure, RPM, speed, intake temperature, MAF, throttle position, engine run
time, and control-module voltage). Missing or malformed PID responses remain
absent; they are never reported as normal or zero. The bridge has no arbitrary
command endpoint and Mode 04 is blocked before transport.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export OCDD_OBD_BRIDGE_TOKEN='choose-a-random-local-token'
uvicorn obd_bridge.service:app --host 127.0.0.1 --port 8765
```

Discover devices with `GET /v1/devices`, then call `POST /v1/scan` with the BLE
address and a reviewed driver profile. The initial profile is a Nordic-UART
style BLE transport; clone adapters with other UUIDs require a separately
reviewed profile.

The bridge returns `generic_powertrain_emissions` as its only module coverage.
For ABS/SRS/body/hybrid/OEM modules, import the report from an appropriate
full-system scan tool into the main application.
