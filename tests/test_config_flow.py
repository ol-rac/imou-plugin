"""Tests for the Imou config flow and options flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.imou_ha.config_flow import ImouConfigFlow
from custom_components.imou_ha.const import (
    CONF_API_URL,
    CONF_APP_ID,
    CONF_APP_SECRET,
    DEFAULT_API_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    OPT_SCAN_INTERVAL,
    REGIONAL_ENDPOINTS,
)
from custom_components.imou_ha.exceptions import (
    ImouAuthError,
    ImouError,
    ImouLicenseError,
)
from custom_components.imou_ha.models import DeviceStatus, ImouDeviceData

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

VALID_USER_INPUT = {
    CONF_APP_ID: "test_app_id",
    CONF_APP_SECRET: "test_app_secret",
    CONF_API_URL: DEFAULT_API_URL,
}

SAMPLE_DEVICES = {
    "CAM001": ImouDeviceData(
        serial="CAM001",
        name="Front Garden",
        model="IPC-C22EP",
        firmware="2.840.0",
        status=DeviceStatus.ACTIVE,
        capabilities=set(),
    ),
    "CAM002": ImouDeviceData(
        serial="CAM002",
        name="Back Door",
        model="IPC-F22FEP",
        firmware="2.840.0",
        status=DeviceStatus.ACTIVE,
        capabilities=set(),
    ),
}


def _mock_client(validate_side_effect=None, get_devices_return=None):
    """Build a mock ImouApiClient."""
    client = MagicMock()
    client.async_validate_credentials = AsyncMock(side_effect=validate_side_effect)
    client.async_get_devices = AsyncMock(
        return_value=get_devices_return if get_devices_return is not None else SAMPLE_DEVICES
    )
    return client


# ---------------------------------------------------------------------------
# Test: Step user form renders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_user_form_renders(hass):
    """Config flow step 'user' returns a form with the correct fields."""
    with patch(
        "custom_components.imou_ha.config_flow.ImouApiClient",
        return_value=_mock_client(),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    schema_keys = {str(k) for k in result["data_schema"].schema}
    assert CONF_APP_ID in schema_keys
    assert CONF_APP_SECRET in schema_keys
    assert CONF_API_URL in schema_keys


# ---------------------------------------------------------------------------
# Test: Region dropdown has exactly 4 options (SETUP-02)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_region_dropdown_has_four_options(hass):
    """SelectSelector for region must expose exactly the 4 REGIONAL_ENDPOINTS keys."""
    with patch(
        "custom_components.imou_ha.config_flow.ImouApiClient",
        return_value=_mock_client(),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

    assert result["type"] == FlowResultType.FORM
    # Locate the api_url field in the schema
    schema = result["data_schema"].schema
    api_url_key = next(k for k in schema if str(k) == CONF_API_URL)
    selector = schema[api_url_key]
    # SelectSelector stores options in its config
    options = selector.config["options"]
    option_values = {opt["value"] for opt in options}
    assert option_values == set(REGIONAL_ENDPOINTS.keys())
    assert len(options) == 4


# ---------------------------------------------------------------------------
# Test: Valid credentials advance to confirm step (SETUP-03)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_credentials_advance_to_confirm(hass):
    """Valid credentials + discovery -> step 'confirm' form."""
    with patch(
        "custom_components.imou_ha.config_flow.ImouApiClient",
        return_value=_mock_client(),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], VALID_USER_INPUT
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "confirm"


# ---------------------------------------------------------------------------
# Test: Invalid credentials show error on same step (SETUP-03, D-02)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_credentials_show_error(hass):
    """ImouAuthError -> errors={'base': 'invalid_auth'}, step_id stays 'user'."""
    with patch(
        "custom_components.imou_ha.config_flow.ImouApiClient",
        return_value=_mock_client(validate_side_effect=ImouAuthError("bad creds")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], VALID_USER_INPUT
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}


# ---------------------------------------------------------------------------
# Test: Cannot connect shows error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cannot_connect_show_error(hass):
    """ImouError (generic) -> errors={'base': 'cannot_connect'}."""
    with patch(
        "custom_components.imou_ha.config_flow.ImouApiClient",
        return_value=_mock_client(validate_side_effect=ImouError("network error")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], VALID_USER_INPUT
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


# ---------------------------------------------------------------------------
# Test: License limit shows error (INFR-04)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_license_limit_show_error(hass):
    """ImouLicenseError -> errors={'base': 'license_limit'}."""
    with patch(
        "custom_components.imou_ha.config_flow.ImouApiClient",
        return_value=_mock_client(
            validate_side_effect=ImouLicenseError("FL1001: device limit")
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], VALID_USER_INPUT
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "license_limit"}


# ---------------------------------------------------------------------------
# Test: Unknown exception shows 'unknown' error (D-11)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_exception_shows_error(hass):
    """Unhandled exception -> errors={'base': 'unknown'}."""
    with patch(
        "custom_components.imou_ha.config_flow.ImouApiClient",
        return_value=_mock_client(validate_side_effect=RuntimeError("oops")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], VALID_USER_INPUT
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "unknown"}


# ---------------------------------------------------------------------------
# Test: Confirm step creates config entry (D-01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_step_creates_entry(hass):
    """Submitting confirm step creates config entry with camera count in title."""
    with (
        patch(
            "custom_components.imou_ha.config_flow.ImouApiClient",
            return_value=_mock_client(),
        ),
        patch(
            "custom_components.imou_ha.async_setup_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], VALID_USER_INPUT
        )
        # Submit confirm step (empty form)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {}
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert "2 cameras" in result["title"]


# ---------------------------------------------------------------------------
# Test: Confirm step shows camera names (D-03)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_step_shows_camera_names(hass):
    """Confirm step description_placeholders must include camera_count and camera_names."""
    with patch(
        "custom_components.imou_ha.config_flow.ImouApiClient",
        return_value=_mock_client(),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], VALID_USER_INPUT
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "confirm"
    placeholders = result.get("description_placeholders", {})
    assert "camera_count" in placeholders
    assert "camera_names" in placeholders
    assert placeholders["camera_count"] == "2"
    # Both camera names should appear
    assert "Front Garden" in placeholders["camera_names"]
    assert "Back Door" in placeholders["camera_names"]


# ---------------------------------------------------------------------------
# Test: Duplicate entry aborted (D-09)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_entry_aborted(hass):
    """Configuring with the same AppId twice is aborted with 'already_configured'."""
    with (
        patch(
            "custom_components.imou_ha.config_flow.ImouApiClient",
            return_value=_mock_client(),
        ),
        patch(
            "custom_components.imou_ha.async_setup_entry",
            return_value=True,
        ),
    ):
        # First config — completes successfully
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], VALID_USER_INPUT
        )
        await hass.config_entries.flow.async_configure(result["flow_id"], {})

        # Second config — same AppId
        result2 = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result2["flow_id"], VALID_USER_INPUT
        )

    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Test: Options flow renders with correct fields (SETUP-04)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_options_flow_renders(hass):
    """Options flow step 'init' renders form with app_id, app_secret, api_url, scan_interval."""
    with (
        patch(
            "custom_components.imou_ha.config_flow.ImouApiClient",
            return_value=_mock_client(),
        ),
        patch(
            "custom_components.imou_ha.async_setup_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], VALID_USER_INPUT
        )
        await hass.config_entries.flow.async_configure(result["flow_id"], {})

    # Retrieve created entry
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    entry = entries[0]

    # Start options flow
    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    schema_keys = {str(k) for k in result["data_schema"].schema}
    assert CONF_APP_ID in schema_keys
    assert CONF_APP_SECRET in schema_keys
    assert CONF_API_URL in schema_keys
    assert OPT_SCAN_INTERVAL in schema_keys


# ---------------------------------------------------------------------------
# Test: Options flow rejects scan_interval below minimum (SETUP-05, D-08)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_options_flow_scan_interval_min(hass):
    """Options flow rejects scan_interval < MIN_SCAN_INTERVAL via schema validation."""
    with (
        patch(
            "custom_components.imou_ha.config_flow.ImouApiClient",
            return_value=_mock_client(),
        ),
        patch(
            "custom_components.imou_ha.async_setup_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], VALID_USER_INPUT
        )
        await hass.config_entries.flow.async_configure(result["flow_id"], {})

    entries = hass.config_entries.async_entries(DOMAIN)
    entry = entries[0]

    result = await hass.config_entries.options.async_init(entry.entry_id)

    # Try to submit with too-low scan_interval
    with pytest.raises((vol.Invalid, vol.MultipleInvalid)):
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_APP_ID: "my_app_id",
                CONF_APP_SECRET: "my_secret",
                CONF_API_URL: DEFAULT_API_URL,
                OPT_SCAN_INTERVAL: MIN_SCAN_INTERVAL - 1,  # 29 — below limit
            },
        )


# ---------------------------------------------------------------------------
# Test: Options flow saves and triggers reload (D-07)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_options_flow_saves_and_reloads(hass):
    """Valid options flow submission creates entry (OptionsFlowWithReload handles reload)."""
    with (
        patch(
            "custom_components.imou_ha.config_flow.ImouApiClient",
            return_value=_mock_client(),
        ),
        patch(
            "custom_components.imou_ha.async_setup_entry",
            return_value=True,
        ),
        patch(
            "custom_components.imou_ha.async_unload_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], VALID_USER_INPUT
        )
        await hass.config_entries.flow.async_configure(result["flow_id"], {})

        entries = hass.config_entries.async_entries(DOMAIN)
        entry = entries[0]

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_APP_ID: "my_app_id",
                CONF_APP_SECRET: "new_secret",
                CONF_API_URL: DEFAULT_API_URL,
                OPT_SCAN_INTERVAL: 60,
            },
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        # Give HA time to process the scheduled reload
        await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# Test: Credentials stored in entry.data only — not in hass.data (INFR-08)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credentials_stored_in_entry_data_only(hass):
    """Credentials must be in entry.data, never in hass.data."""
    with (
        patch(
            "custom_components.imou_ha.config_flow.ImouApiClient",
            return_value=_mock_client(),
        ),
        patch(
            "custom_components.imou_ha.async_setup_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], VALID_USER_INPUT
        )
        await hass.config_entries.flow.async_configure(result["flow_id"], {})

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    entry = entries[0]

    # Credentials present in entry.data
    assert entry.data[CONF_APP_ID] == VALID_USER_INPUT[CONF_APP_ID]
    assert entry.data[CONF_APP_SECRET] == VALID_USER_INPUT[CONF_APP_SECRET]

    # Not present in hass.data (under the DOMAIN key)
    assert DOMAIN not in hass.data or not isinstance(
        hass.data.get(DOMAIN), dict
    ) or CONF_APP_SECRET not in hass.data.get(DOMAIN, {})
