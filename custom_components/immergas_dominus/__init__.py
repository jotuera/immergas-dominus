"""Immergas Dominus integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.loader import async_get_integration

# Integration author, shown on the device pages together with the version.
AUTHOR = "JoTu"

from .const import (
    CONF_MAC,
    CONF_PASSWORD,
    DEFAULT_DISABLED_DEVICES,
    DEVICE_INFO,
    DEVICE_MAIN,
    DOMAIN,
    LEGACY_DEVICE_KEYS,
    LOGICAL_DEVICES,
    PLATFORMS,
)
from .coordinator import ImmergasDominusCoordinator
from .dominus_client import DominusClient, DominusConfig, DominusError

_LOGGER = logging.getLogger(__name__)


def _ensure_logical_devices(
    hass: HomeAssistant, entry: ConfigEntry, version: str | None
) -> None:
    """Create logical Dominus devices even before every zone has entities.

    Home Assistant does not support arbitrary per-device entity categories like
    "Zone 1".  The public integration represents Dominus areas as logical
    devices instead: the main Dominus unit, Zone 1, Zone 2 and Zone 3.
    Zone 2 and Zone 3 are intentionally empty placeholders until the user
    enables their (disabled-by-default) entities.

    The integration version and author are shown on the device pages via the
    "sw_version" field.
    """
    registry = dr.async_get(hass)
    main_identifier = (DOMAIN, entry.entry_id)
    sw_version = f"{version} — {AUTHOR}" if version else AUTHOR

    # Remove logical devices that were split out in older versions but whose
    # entities have since been merged into the main device (e.g. the old "CWU"
    # device; its DHW entities now live on the main Dominus device).
    for legacy_key in LEGACY_DEVICE_KEYS:
        legacy_device = registry.async_get_device(
            identifiers={(DOMAIN, f"{entry.entry_id}_{legacy_key}")}
        )
        if legacy_device is not None:
            registry.async_remove_device(legacy_device.id)

    for device_key in LOGICAL_DEVICES:
        info = DEVICE_INFO[device_key]
        identifiers = {main_identifier} if device_key == DEVICE_MAIN else {(DOMAIN, f"{entry.entry_id}_{device_key}")}
        existing = registry.async_get_device(identifiers=identifiers)
        kwargs = {
            "config_entry_id": entry.entry_id,
            "identifiers": identifiers,
            "manufacturer": "Immergas",
            "name": info["name"],
            "model": info["model"],
            "sw_version": sw_version,
        }
        if device_key != DEVICE_MAIN:
            kwargs["via_device"] = main_identifier
        device = registry.async_get_or_create(**kwargs)

        # Disable Zone 2/3 devices only the first time they are created, so a
        # single-zone system does not show inactive zones.  Never override a
        # device the user has since enabled (or disabled) themselves.
        if existing is None and device_key in DEFAULT_DISABLED_DEVICES:
            registry.async_update_device(
                device.id, disabled_by=dr.DeviceEntryDisabler.INTEGRATION
            )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Immergas Dominus from a config entry."""
    client = DominusClient(
        DominusConfig(
            host=entry.data[CONF_HOST],
            port=entry.data[CONF_PORT],
            mac=entry.data[CONF_MAC],
            password=entry.data[CONF_PASSWORD],
        )
    )
    coordinator = ImmergasDominusCoordinator(hass, entry, client)

    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version) if integration.version else None
    _ensure_logical_devices(hass, entry, version)

    # Do not block entity creation on the very first TCP poll.  Dominus local
    # TCP sessions can be temporarily rejected just after the mobile app, the
    # development gateway, or a failed AUTH attempt was used.  Creating the
    # entities first makes the integration visible in Home Assistant; the
    # coordinator will keep retrying and values will appear when Dominus accepts
    # the local TCP session.
    try:
        await coordinator.async_refresh()
    except ConfigEntryNotReady:
        raise
    except DominusError as err:
        _LOGGER.warning(
            "Initial Immergas Dominus poll failed; entities will be created and polling will retry: %s",
            err,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "Unexpected initial Immergas Dominus poll failure; entities will be created and polling will retry: %s",
            err,
        )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
