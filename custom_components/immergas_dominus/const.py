"""Constants and entity descriptions for Immergas Dominus."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from homeassistant.components.climate import ClimateEntityDescription
from homeassistant.components.number import NumberDeviceClass, NumberEntityDescription, NumberMode
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.sensor import SensorDeviceClass, SensorEntityDescription
from homeassistant.const import PERCENTAGE, UnitOfTemperature

DOMAIN = "immergas_dominus"
DEFAULT_PORT = 2000
DEFAULT_SCAN_INTERVAL = 45

CONF_MAC = "mac"
CONF_PASSWORD = "password"

# Boiler fault reporting (same registers as the D+/D- and T-/T+ tooling).
# PDU 2100 = fault code (0 = no fault, otherwise Immergas E<code>).
# PDU 2101 = flags written together with 2100; low-byte bit 1 = "reset available".
FAULT_CODE_PDU = 2100
FAULT_FLAGS_PDU = 2101
FAULT_RESET_AVAILABLE_MASK = 0x02

PLATFORMS = ["sensor", "binary_sensor", "number", "select", "climate", "time"]

DEVICE_MAIN = "dominus"
DEVICE_ZONE_1 = "zone_1"
DEVICE_ZONE_2 = "zone_2"
DEVICE_ZONE_3 = "zone_3"
DEVICE_DHW = "dhw"
DEVICE_SCHEDULE = "schedule"

DEVICE_INFO = {
    DEVICE_MAIN: {"name": "Immergas Dominus", "model": "Dominus"},
    DEVICE_ZONE_1: {"name": "Zone 1", "model": "Dominus zone"},
    DEVICE_ZONE_2: {"name": "Zone 2", "model": "Dominus zone"},
    DEVICE_ZONE_3: {"name": "Zone 3", "model": "Dominus zone"},
    DEVICE_SCHEDULE: {"name": "Heating schedule", "model": "Dominus schedule"},
}

# DHW (CWU) entities live on the main Dominus device since 0.2.4; the separate
# "CWU" logical device is no longer created.  DEVICE_DHW is kept only to clean up
# the legacy device on existing installs.
LOGICAL_DEVICES = (DEVICE_MAIN, DEVICE_ZONE_1, DEVICE_ZONE_2, DEVICE_ZONE_3, DEVICE_SCHEDULE)
LEGACY_DEVICE_KEYS = (DEVICE_DHW,)

# Devices created disabled by default: a single-zone hydraulic system leaves
# Zones 2/3 inactive, and the CO heating schedule is an advanced feature, so the
# whole device is disabled (its entities are enabled, so enabling the device
# brings them all online at once).  Only applied when the device is first created;
# a device the user manually enabled is left untouched.
DEFAULT_DISABLED_DEVICES = (DEVICE_ZONE_2, DEVICE_ZONE_3, DEVICE_SCHEDULE)


class OperationMode(StrEnum):
    """Known Dominus operation modes."""

    STANDBY = "standby"
    SUMMER = "summer"
    COOLING = "cooling"
    WINTER = "winter"


OPERATION_MODE_TO_RAW: dict[OperationMode, int] = {
    OperationMode.STANDBY: 0,
    OperationMode.SUMMER: 1,
    OperationMode.COOLING: 2,
    OperationMode.WINTER: 3,
}
RAW_TO_OPERATION_MODE = {raw: mode for mode, raw in OPERATION_MODE_TO_RAW.items()}
OPERATION_MODE_OPTIONS = [mode.value for mode in OperationMode]




@dataclass(frozen=True, kw_only=True)
class DominusClimateEntityDescription(ClimateEntityDescription):
    """Description of a Dominus thermostat/climate entity."""

    current_pdu: int
    target_pdu: int
    target_raw_scale: float = 1.0
    native_min_temp: float = 5.0
    native_max_temp: float = 35.0
    native_step: float = 0.5
    climate_kind: str = "space"
    device_key: str = DEVICE_MAIN


@dataclass(frozen=True, kw_only=True)
class DominusSensorEntityDescription(SensorEntityDescription):
    """Description of a read-only Dominus PDU sensor."""

    pdu: int
    value_scale: float = 1.0
    device_key: str = DEVICE_MAIN
    # Raw values that mean "no reading" and must be reported as unavailable
    # instead of scaled.  Confirmed by the D+/D- bus dump (dominus_0x33_register_map):
    # PDU 3002 outdoor temperature carries 0x00FF (255) when no outdoor probe is
    # fitted; scaling it would show a false 25.5 C.
    invalid_raw_values: tuple[int, ...] = ()


@dataclass(frozen=True, kw_only=True)
class DominusNumberEntityDescription(NumberEntityDescription):
    """Description of a writable Dominus PDU number."""

    pdu: int
    raw_scale: float = 1.0
    device_key: str = DEVICE_MAIN


@dataclass(frozen=True, kw_only=True)
class DominusSelectEntityDescription(SelectEntityDescription):
    """Description of a writable Dominus PDU select."""

    pdu: int
    option_to_raw: dict[str, int]
    raw_to_option: dict[int, str]
    device_key: str = DEVICE_MAIN
    # Read only the low byte of the PDU (u8), e.g. the weekday->profile registers
    # (2410-2416) return the profile number in the low byte.
    mask_low_byte: bool = False


@dataclass(frozen=True, kw_only=True)
class DominusTimeEntityDescription:
    """Description of a writable Dominus schedule time-of-day (PDU high=hour, low=minute)."""

    key: str
    pdu: int
    translation_key: str
    translation_placeholders: dict[str, str] | None = None
    device_key: str = DEVICE_SCHEDULE


SENSOR_DESCRIPTIONS: tuple[DominusSensorEntityDescription, ...] = (
    DominusSensorEntityDescription(
        key="room_temperature",
        pdu=2011,
        device_key=DEVICE_ZONE_1,
        translation_key="room_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_scale=0.1,
    ),
    DominusSensorEntityDescription(
        key="outdoor_temperature",
        pdu=3002,
        device_key=DEVICE_MAIN,
        translation_key="outdoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_scale=0.1,
        # 0x00FF (255) = brak sondy zewnętrznej / odczyt nieprawidłowy.
        invalid_raw_values=(255,),
    ),
    DominusSensorEntityDescription(
        key="dhw_tank_temperature",
        pdu=3016,
        device_key=DEVICE_MAIN,
        translation_key="dhw_tank_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_scale=0.1,
    ),
)

NUMBER_DESCRIPTIONS: tuple[DominusNumberEntityDescription, ...] = (
    DominusNumberEntityDescription(
        key="heating_target",
        pdu=2015,
        device_key=DEVICE_ZONE_1,
        translation_key="heating_target",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=5,
        native_max_value=35,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.SLIDER,
        raw_scale=10,
    ),
    DominusNumberEntityDescription(
        key="heating_curve_offset",
        pdu=2017,
        device_key=DEVICE_ZONE_1,
        translation_key="heating_curve_offset",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=-10,
        native_max_value=10,
        native_step=1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.SLIDER,
        raw_scale=10,
    ),
    DominusNumberEntityDescription(
        key="dhw_target",
        pdu=2095,
        device_key=DEVICE_MAIN,
        translation_key="dhw_target",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=30,
        native_max_value=60,
        native_step=1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.SLIDER,
        raw_scale=10,
    ),
    DominusNumberEntityDescription(
        key="comfort_heat",
        pdu=2210,
        device_key=DEVICE_ZONE_1,
        translation_key="comfort_heat",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=5,
        native_max_value=35,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.SLIDER,
        raw_scale=10,
    ),
    DominusNumberEntityDescription(
        key="eco_heat",
        pdu=2211,
        device_key=DEVICE_ZONE_1,
        translation_key="eco_heat",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=5,
        native_max_value=35,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.SLIDER,
        raw_scale=10,
    ),
    DominusNumberEntityDescription(
        key="comfort_cool",
        pdu=2214,
        device_key=DEVICE_ZONE_1,
        translation_key="comfort_cool",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=5,
        native_max_value=35,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.SLIDER,
        raw_scale=10,
    ),
    DominusNumberEntityDescription(
        key="eco_cool",
        pdu=2215,
        device_key=DEVICE_ZONE_1,
        translation_key="eco_cool",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=5,
        native_max_value=35,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.SLIDER,
        raw_scale=10,
    ),
    DominusNumberEntityDescription(
        key="humidity_target",
        pdu=2216,
        device_key=DEVICE_ZONE_1,
        translation_key="humidity_target",
        device_class=NumberDeviceClass.HUMIDITY,
        native_min_value=30,
        native_max_value=80,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        raw_scale=1,
    ),
    DominusNumberEntityDescription(
        key="flow_target",
        pdu=2217,
        device_key=DEVICE_ZONE_1,
        translation_key="flow_target",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=20,
        native_max_value=55,
        native_step=1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.SLIDER,
        raw_scale=10,
    ),
)

SELECT_DESCRIPTIONS: tuple[DominusSelectEntityDescription, ...] = (
    DominusSelectEntityDescription(
        key="operation_mode",
        pdu=2000,
        device_key=DEVICE_MAIN,
        translation_key="operation_mode",
        options=OPERATION_MODE_OPTIONS,
        option_to_raw={mode.value: raw for mode, raw in OPERATION_MODE_TO_RAW.items()},
        raw_to_option={raw: mode.value for raw, mode in RAW_TO_OPERATION_MODE.items()},
    ),
)

CLIMATE_DESCRIPTIONS: tuple[DominusClimateEntityDescription, ...] = (
    DominusClimateEntityDescription(
        key="heating_thermostat",
        translation_key="heating_thermostat",
        device_key=DEVICE_ZONE_1,
        current_pdu=2011,
        target_pdu=2015,
        target_raw_scale=10,
        native_min_temp=5,
        native_max_temp=35,
        native_step=0.5,
        climate_kind="space",
    ),
    DominusClimateEntityDescription(
        key="dhw_thermostat",
        translation_key="dhw_thermostat",
        device_key=DEVICE_MAIN,
        current_pdu=3016,
        target_pdu=2095,
        target_raw_scale=10,
        native_min_temp=30,
        native_max_temp=60,
        native_step=1,
        climate_kind="dhw",
    ),
)


# --- Zones 2 and 3 -----------------------------------------------------------
# Per-zone registers are offset by +10 per zone.  Confirmed from the Dominus app
# config (items_pdu_action_suffix.csv): room temp 2011/2021/2031, active setpoint
# 2015/2025/2035, comfort/eco/humidity/flow block 22x0..22x7 -> 22(x+1)0.. etc.
# On a single-zone hydraulic system Zones 2/3 are inactive, so their whole device
# is disabled by default (see DEFAULT_DISABLED_DEVICES).  The entities themselves
# are enabled, so enabling the device brings them all online; the coordinator only
# polls PDUs of entities that are actually enabled.
_EXTRA_ZONES: tuple[tuple[int, str], ...] = ((2, DEVICE_ZONE_2), (3, DEVICE_ZONE_3))

# (key, base PDU for Zone 1, min, max, step, icon) for per-zone temperature setpoints.
# heating_curve_offset uses PDU 2027/2037 for Zone 2/3: inferred from the +10 zone
# pattern (2017 for Zone 1), not directly listed in the Dominus app config — verify
# over TCP before relying on it.
_ZONE_TEMP_NUMBERS = (
    ("heating_target", 2015, 5, 35, 0.5, "mdi:home-thermometer"),
    ("heating_curve_offset", 2017, -10, 10, 1, "mdi:tune-vertical"),
    ("comfort_heat", 2210, 5, 35, 0.5, "mdi:fire"),
    ("eco_heat", 2211, 5, 35, 0.5, "mdi:leaf"),
    ("comfort_cool", 2214, 5, 35, 0.5, "mdi:snowflake"),
    ("eco_cool", 2215, 5, 35, 0.5, "mdi:snowflake-thermometer"),
    ("flow_target", 2217, 20, 55, 1, "mdi:thermometer-water"),
)


def _zone_sensor_descriptions() -> tuple[DominusSensorEntityDescription, ...]:
    result: list[DominusSensorEntityDescription] = []
    for zone, device_key in _EXTRA_ZONES:
        offset = (zone - 1) * 10
        result.append(
            DominusSensorEntityDescription(
                key=f"room_temperature_zone{zone}",
                pdu=2011 + offset,
                device_key=device_key,
                translation_key=f"room_temperature_zone{zone}",
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                suggested_display_precision=1,
                value_scale=0.1,            )
        )
    return tuple(result)


def _zone_number_descriptions() -> tuple[DominusNumberEntityDescription, ...]:
    result: list[DominusNumberEntityDescription] = []
    for zone, device_key in _EXTRA_ZONES:
        offset = (zone - 1) * 10
        for key, base_pdu, low, high, step, icon in _ZONE_TEMP_NUMBERS:
            result.append(
                DominusNumberEntityDescription(
                    key=f"{key}_zone{zone}",
                    pdu=base_pdu + offset,
                    device_key=device_key,
                    translation_key=f"{key}_zone{zone}",
                    device_class=NumberDeviceClass.TEMPERATURE,
                    native_min_value=low,
                    native_max_value=high,
                    native_step=step,
                    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                    mode=NumberMode.SLIDER,
                    icon=icon,
                    raw_scale=10,                )
            )
        result.append(
            DominusNumberEntityDescription(
                key=f"humidity_target_zone{zone}",
                pdu=2216 + offset,
                device_key=device_key,
                translation_key=f"humidity_target_zone{zone}",
                device_class=NumberDeviceClass.HUMIDITY,
                native_min_value=30,
                native_max_value=80,
                native_step=1,
                native_unit_of_measurement=PERCENTAGE,
                mode=NumberMode.SLIDER,
                icon="mdi:water-percent",
                raw_scale=1,            )
        )
    return tuple(result)


def _zone_climate_descriptions() -> tuple[DominusClimateEntityDescription, ...]:
    result: list[DominusClimateEntityDescription] = []
    for zone, device_key in _EXTRA_ZONES:
        offset = (zone - 1) * 10
        result.append(
            DominusClimateEntityDescription(
                key=f"heating_thermostat_zone{zone}",
                translation_key=f"heating_thermostat_zone{zone}",
                device_key=device_key,
                current_pdu=2011 + offset,
                target_pdu=2015 + offset,
                target_raw_scale=10,
                native_min_temp=5,
                native_max_temp=35,
                native_step=0.5,
                climate_kind="space",            )
        )
    return tuple(result)


SENSOR_DESCRIPTIONS = SENSOR_DESCRIPTIONS + _zone_sensor_descriptions()
NUMBER_DESCRIPTIONS = NUMBER_DESCRIPTIONS + _zone_number_descriptions()
CLIMATE_DESCRIPTIONS = CLIMATE_DESCRIPTIONS + _zone_climate_descriptions()


# --- CO heating schedule (chrono) --------------------------------------------
# Confirmed from the D+/D- dump and the Dominus app config.  4 shared day profiles
# (cal1-4), each with 4 comfort periods ("fascia") stored as a start/end pair.
# Time is encoded as high byte = hour, low byte = minute (e.g. 0x0600 = 06:00).
#   profile P (1-4) base PDU = 2300 + P*10; fascia F (1-4) start = base + (F-1)*2, end = +1.
# Weekday -> profile assignment for Zone 1: PDU 2410-2416 (Mon-Sun), low byte = 1-4.
_CHRONO_PROFILE_OPTIONS = ("Cal 1", "Cal 2", "Cal 3", "Cal 4")
_CHRONO_OPTION_TO_RAW = {opt: idx + 1 for idx, opt in enumerate(_CHRONO_PROFILE_OPTIONS)}
_CHRONO_RAW_TO_OPTION = {raw: opt for opt, raw in _CHRONO_OPTION_TO_RAW.items()}


def _schedule_time_descriptions() -> tuple[DominusTimeEntityDescription, ...]:
    result: list[DominusTimeEntityDescription] = []
    for profile in range(1, 5):
        base = 2300 + profile * 10
        for fascia in range(1, 5):
            start_pdu = base + (fascia - 1) * 2
            for edge, pdu in (("start", start_pdu), ("end", start_pdu + 1)):
                result.append(
                    DominusTimeEntityDescription(
                        key=f"profile{profile}_fascia{fascia}_{edge}",
                        pdu=pdu,
                        translation_key=f"fascia_{edge}",
                        translation_placeholders={
                            "profile": str(profile),
                            "fascia": str(fascia),
                        },
                    )
                )
    return tuple(result)


def _weekday_select_descriptions() -> tuple[DominusSelectEntityDescription, ...]:
    result: list[DominusSelectEntityDescription] = []
    for day in range(1, 8):
        result.append(
            DominusSelectEntityDescription(
                key=f"weekday_{day}_profile",
                pdu=2409 + day,
                device_key=DEVICE_SCHEDULE,
                translation_key=f"weekday_{day}_profile",
                options=list(_CHRONO_PROFILE_OPTIONS),
                option_to_raw=dict(_CHRONO_OPTION_TO_RAW),
                raw_to_option=dict(_CHRONO_RAW_TO_OPTION),
                mask_low_byte=True,
                icon="mdi:calendar-clock",
            )
        )
    return tuple(result)


SCHEDULE_TIME_DESCRIPTIONS: tuple[DominusTimeEntityDescription, ...] = _schedule_time_descriptions()
SELECT_DESCRIPTIONS = SELECT_DESCRIPTIONS + _weekday_select_descriptions()

# Public chrono constants for the "set the same profile for all days" shortcut.
CHRONO_PROFILE_OPTIONS = _CHRONO_PROFILE_OPTIONS
CHRONO_OPTION_TO_RAW = dict(_CHRONO_OPTION_TO_RAW)
CHRONO_RAW_TO_OPTION = dict(_CHRONO_RAW_TO_OPTION)
WEEKDAY_PROFILE_PDUS = tuple(2409 + day for day in range(1, 8))
