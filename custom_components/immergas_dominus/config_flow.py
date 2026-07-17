"""Config flow for Immergas Dominus."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import CONF_MAC, CONF_PASSWORD, DEFAULT_PORT, DOMAIN
from .dominus_client import DominusClient, DominusConfig, DominusError

_LOGGER = logging.getLogger(__name__)


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_MAC): str,
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


def normalize_mac_for_unique_id(mac: str) -> str | None:
    """Normalize MAC for unique_id or return None if invalid."""
    normalized = str(mac or "").replace(":", "").replace("-", "").strip().lower()
    if len(normalized) != 12 or any(ch not in "0123456789abcdef" for ch in normalized):
        return None
    return normalized


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> str:
    """Try to validate the user input against the local Dominus module."""
    client = DominusClient(
        DominusConfig(
            host=data[CONF_HOST],
            port=data[CONF_PORT],
            mac=data[CONF_MAC],
            password=data[CONF_PASSWORD],
        )
    )
    await client.async_test_connection()
    return data[CONF_HOST]


class ImmergasDominusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Immergas Dominus."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            mac_unique = normalize_mac_for_unique_id(user_input[CONF_MAC])
            if mac_unique is None:
                errors[CONF_MAC] = "invalid_mac"
            else:
                await self.async_set_unique_id(mac_unique)
                self._abort_if_unique_id_configured()

                # Dominus local TCP is known to be session-sensitive and can
                # temporarily reject local connections after the mobile app or
                # the development gateway was used.  Do not block config entry
                # creation on one failed live read; the coordinator will retry
                # after setup.  This is still a local-only integration: no cloud
                # call is made here.
                try:
                    title = await validate_input(self.hass, user_input)
                except DominusError as err:
                    _LOGGER.warning(
                        "Initial Immergas Dominus TCP test failed; creating entry and Home Assistant will retry: %s",
                        err,
                    )
                    title = user_input[CONF_HOST]
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "Unexpected initial Immergas Dominus TCP test failure; creating entry and Home Assistant will retry: %s",
                        err,
                    )
                    title = user_input[CONF_HOST]

                return self.async_create_entry(title=f"Immergas Dominus {title}", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
