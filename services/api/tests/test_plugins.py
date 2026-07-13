from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.plugins import PluginMetadata, PluginRegistrationError, validate_plugin_metadata


def test_plugin_governance_metadata_is_required() -> None:
    metadata = PluginMetadata(
        name="example",
        version="1.0",
        licenseName="MIT",
        accessCost="free",
        credentialStorage="none",
        retentionPolicy="no data retained",
        redistribution="allowed",
        dataSources=["fixture"],
    )
    validate_plugin_metadata(metadata)
    metadata.license_name = ""
    with pytest.raises(PluginRegistrationError):
        validate_plugin_metadata(metadata)


def test_official_plugin_registry_rejects_paid_access_modes() -> None:
    with pytest.raises(ValidationError, match="accessCost"):
        PluginMetadata(
            name="paid-example",
            version="1.0",
            licenseName="Proprietary",
            accessCost="subscription",
            credentialStorage="external account",
            retentionPolicy="external",
            redistribution="not allowed",
            dataSources=["paid feed"],
        )
