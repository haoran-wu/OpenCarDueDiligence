"""Official vehicle-data routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from ..providers.nhtsa import (
    NhtsaProvider,
    NhtsaProviderTimeout,
    NhtsaProviderUnavailable,
    RecallSignalQuery,
    RecallSignalsResponse,
    VinDecodeQuery,
    VinDecodeResponse,
)


router = APIRouter(prefix="/v1/vehicles", tags=["official vehicle data"])


def get_nhtsa_provider(request: Request) -> NhtsaProvider:
    """Allow tests or deployments to inject transport/caching without globals."""

    provider = getattr(request.app.state, "nhtsa_provider", None)
    return provider if provider is not None else NhtsaProvider()


ProviderDependency = Annotated[NhtsaProvider, Depends(get_nhtsa_provider)]


def _upstream_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NhtsaProviderTimeout):
        return HTTPException(
            status_code=504,
            detail="NHTSA official service timed out; no cached result was substituted",
        )
    return HTTPException(
        status_code=502,
        detail="NHTSA official service is unavailable or returned an invalid response",
    )


@router.post("/decode-vin", response_model=VinDecodeResponse)
def decode_vin(
    payload: VinDecodeQuery,
    provider: ProviderDependency,
) -> VinDecodeResponse:
    try:
        return provider.decode_vin(payload.vin, model_year=payload.model_year)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (NhtsaProviderTimeout, NhtsaProviderUnavailable) as exc:
        raise _upstream_http_error(exc) from exc


@router.post("/recall-signals", response_model=RecallSignalsResponse)
def recall_signals(
    payload: RecallSignalQuery,
    provider: ProviderDependency,
) -> RecallSignalsResponse:
    try:
        return provider.recall_signals(payload)
    except (NhtsaProviderTimeout, NhtsaProviderUnavailable) as exc:
        raise _upstream_http_error(exc) from exc
