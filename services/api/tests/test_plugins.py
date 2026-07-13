from __future__ import annotations

import pytest

from app.plugins import PluginMetadata, PluginRegistrationError, validate_plugin_metadata


def test_plugin_governance_metadata_is_required() -> None:
    metadata = PluginMetadata(
        name="example",
        version="1.0",
        licenseName="MIT",
        credentialStorage="none",
        retentionPolicy="no data retained",
        redistribution="allowed",
        dataSources=["fixture"],
    )
    validate_plugin_metadata(metadata)
    metadata.license_name = ""
    with pytest.raises(PluginRegistrationError):
        validate_plugin_metadata(metadata)
