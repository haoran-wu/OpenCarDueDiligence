"""Stable plugin protocols for BYO-credential providers.

No commercial data source is scraped by the open core. Providers must declare
license, credential, retention, and redistribution behavior before registration.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from .models import (
    DomainModel,
    HistoryEvent,
    ListingInput,
    RepairScenario,
    RiskFinding,
    TransactionContext,
    TransactionPlan,
    VehicleSpec,
)


class PluginMetadata(DomainModel):
    name: str
    version: str
    license_name: str
    license_url: str | None = None
    credential_storage: str
    retention_policy: str
    redistribution: str
    data_sources: list[str] = Field(min_length=1)


class PluginRegistrationError(ValueError):
    pass


def validate_plugin_metadata(metadata: PluginMetadata) -> None:
    fields = (
        metadata.license_name,
        metadata.credential_storage,
        metadata.retention_policy,
        metadata.redistribution,
    )
    if any(not value.strip() for value in fields):
        raise PluginRegistrationError("plugin governance metadata must be explicit")


@runtime_checkable
class ListingProvider(Protocol):
    metadata: PluginMetadata

    async def fetch_listings(self, query: dict[str, Any]) -> list[ListingInput]: ...


@runtime_checkable
class HistoryProvider(Protocol):
    metadata: PluginMetadata

    async def fetch_history(self, vehicle: VehicleSpec) -> list[HistoryEvent]: ...


@runtime_checkable
class MarketDataProvider(Protocol):
    metadata: PluginMetadata

    async def fetch_comparables(self, vehicle: VehicleSpec, query: dict[str, Any]) -> list[ListingInput]: ...


@runtime_checkable
class RepairCostProvider(Protocol):
    metadata: PluginMetadata

    async def price_scenarios(self, vehicle: VehicleSpec, finding: RiskFinding, zip3: str) -> list[RepairScenario]: ...


@runtime_checkable
class DtcDefinitionProvider(Protocol):
    metadata: PluginMetadata

    async def define(self, vehicle: VehicleSpec, codes: list[str]) -> list[RiskFinding]: ...


@runtime_checkable
class StateRuleProvider(Protocol):
    metadata: PluginMetadata

    async def transaction_plan(self, context: TransactionContext) -> TransactionPlan: ...


@runtime_checkable
class LLMProvider(Protocol):
    metadata: PluginMetadata

    async def explain(self, structured_facts: dict[str, Any], language: str) -> str: ...
