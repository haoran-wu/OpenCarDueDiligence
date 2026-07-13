from __future__ import annotations

import os
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .parser import parse_dtc_response, parse_pid_responses, parse_vin_response, readiness_summary
from .safety import FREEZE_FRAME_COMMANDS, LIVE_PID_COMMANDS, READINESS_COMMAND
from .transport import BleakElmTransport, ElmTransport, MockElmTransport


REFERENCE_PROFILES = {
    "nordic-uart": {
        "write_uuid": "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
        "notify_uuid": "6e400003-b5a3-f393-e0a9-e50e24dcca9e",
    }
}


class ScanRequest(BaseModel):
    address: str | None = None
    driver_profile: str = "nordic-uart"
    mock_responses: dict[str, str] | None = None


class ScanCode(BaseModel):
    code: str
    status: Literal["stored", "pending", "permanent"]


class ScanResult(BaseModel):
    vin: str | None = None
    adapter: str | None = None
    module_coverage: list[str] = Field(default_factory=lambda: ["generic_powertrain_emissions"])
    readiness: dict[str, str | int | bool]
    codes: list[ScanCode]
    freeze_frame: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    live_pids: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    raw: dict[str, str]
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Generic ELM327 coverage does not prove ABS, SRS, body, hybrid, or OEM modules were scanned.",
            "No codes does not prove mechanical condition; complete an independent inspection.",
        ]
    )


TOKEN = os.getenv("OCDD_OBD_BRIDGE_TOKEN")


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if not TOKEN:
        raise HTTPException(
            status_code=503,
            detail="OCDD_OBD_BRIDGE_TOKEN is not configured",
        )
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid local bridge token")


app = FastAPI(title="OpenCarDueDiligence OBD Bridge", version="0.1.0-alpha.2")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health")
async def health() -> dict[str, object]:
    return {"status": "ok", "read_only": True, "profiles": list(REFERENCE_PROFILES)}


@app.get("/v1/devices", dependencies=[Depends(require_token)])
async def devices(timeout: float = 4.0) -> list[dict[str, str | None]]:
    from bleak import BleakScanner

    discovered = await BleakScanner.discover(timeout=min(max(timeout, 1), 10))
    return [{"address": device.address, "name": device.name} for device in discovered]


async def _initialize(transport: ElmTransport) -> dict[str, str]:
    raw: dict[str, str] = {}
    for command in ("ATZ", "ATE0", "ATL0", "ATS0", "ATH0", "ATSP0", "ATI"):
        raw[command] = await transport.query(command)
    return raw


SCAN_COMMANDS = (
    "0902",
    READINESS_COMMAND,
    "03",
    "07",
    "0A",
    *LIVE_PID_COMMANDS,
    *FREEZE_FRAME_COMMANDS,
)


@app.post("/v1/scan", response_model=ScanResult, dependencies=[Depends(require_token)])
async def scan(request: ScanRequest) -> ScanResult:
    if request.mock_responses is not None:
        transport: ElmTransport = MockElmTransport(request.mock_responses)
    else:
        if not request.address:
            raise HTTPException(status_code=422, detail="BLE address is required")
        profile = REFERENCE_PROFILES.get(request.driver_profile)
        if not profile:
            raise HTTPException(status_code=422, detail="Unknown reviewed driver profile")
        transport = BleakElmTransport(request.address, **profile)

    try:
        await transport.connect()
        raw = await _initialize(transport)
        for command in SCAN_COMMANDS:
            raw[command] = await transport.query(command)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="OBD adapter timed out") from exc
    finally:
        await transport.close()

    codes = [
        *[ScanCode(code=code, status="stored") for code in parse_dtc_response(raw["03"], 0x43)],
        *[ScanCode(code=code, status="pending") for code in parse_dtc_response(raw["07"], 0x47)],
        *[ScanCode(code=code, status="permanent") for code in parse_dtc_response(raw["0A"], 0x4A)],
    ]
    return ScanResult(
        vin=parse_vin_response(raw["0902"]),
        adapter=raw.get("ATI", "").replace(">", "").strip() or None,
        readiness=readiness_summary(raw[READINESS_COMMAND]),
        codes=codes,
        freeze_frame=parse_pid_responses(raw, mode=2),
        live_pids=parse_pid_responses(raw, mode=1),
        raw=raw,
    )
