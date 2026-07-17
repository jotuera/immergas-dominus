# Immergas Dominus

Version: `0.3.0`
Author: **JoTu** ([github.com/jotuera](https://github.com/jotuera))

Home Assistant custom integration for **local** control of an Immergas boiler through
the **Dominus** Wi-Fi module — no cloud, no MQTT. Home Assistant talks directly to the
Dominus module over local TCP (default port `2000`) using the module MAC and password.

> **Tested on Immergas Magis Combo and Magis Pro** (Magis PRO COMBO V2, MPROCOMBOV2
> configuration). Other Immergas models that use the same Dominus module may work, but
> are not verified.

The interface is **English by default**, with a full **Polish** translation. The
integration version and author are also shown on each Dominus device page in Home
Assistant (the *Firmware* field, e.g. `0.3.0 — JoTu`).

## Features

- Local TCP connection, config flow (host/IP, port, Dominus MAC, Dominus password).
- No cloud dependency, no MQTT, no sniffer, no debug/raw-PDU entities.
- Last-known-good caching and dynamic polling — only PDUs of **enabled** entities are read.

### Main device

- Sensors: outdoor temperature (`3002`, `0xFF` = no probe), DHW tank temperature (`3016`).
- Operation mode select (`2000`): Standby / Summer / Cooling / Winter.
- DHW target (`2095`) and DHW thermostat.
- **Boiler fault reporting** (like the Dominus app): fault code (`2100`), fault description
  (English text from the decoded Dominus app fault table, 114 codes), `Boiler fault`
  (binary, *problem*) and `Reset available` (binary, `2101` bit 1).

### Zone 1 (and disabled-by-default Zone 2 / Zone 3)

- Room temperature, heating target, heating curve offset (U03), comfort/eco heat & cool,
  humidity and flow setpoints (sliders), plus a heating thermostat.
- Per-zone registers are offset by `+10` per zone (Zone 1 `2011/2015/2210…`,
  Zone 2 `2021/2025/2220…`, Zone 3 `2031/2035/2230…`). Zone 2/3 devices are disabled by
  default; enable the device to bring all its entities online.

### Heating schedule (disabled by default)

- 4 shared day profiles (Cal 1–4) × 4 comfort periods, each a start/end `time`
  (`2310`–`2347`, high byte = hour, low byte = minute; `24:00` shown as `23:59`).
- Weekday → profile assignment for Zone 1 (`2410`–`2416`), plus a
  **Set the same profile for all days** shortcut.

## Installation

### HACS (custom repository)

1. HACS → *Integrations* → ⋮ → *Custom repositories*.
2. Add `https://github.com/jotuera/immergas-dominus`, category *Integration*.
3. Install **Immergas Dominus**, restart Home Assistant.
4. *Settings → Devices & services → Add integration → Immergas Dominus*.

### Manual

Copy `custom_components/immergas_dominus` into your Home Assistant `config/custom_components/`
directory, restart Home Assistant, then add the integration as above.

The first local TCP session can be rejected by the Dominus module (e.g. just after the
mobile app was used); the integration creates the entities anyway and values appear once
the module accepts the session.

## Notes

- Fault descriptions are extracted from the decoded Dominus app label table
  (`LBL-WFC01_IM_MBUS_MPROCOMBOV2.json`, English fields), the same source used for the
  D+/D- and T-/T+ bus tooling.
- Registers confirmed only on the D+/D- bus (schedule, fault flags) are cross-checked but
  may need verification over TCP AUTH on other models.

## Changelog

### 0.3.0

- First public GitHub release. English by default (device names, entities, and **English
  boiler fault descriptions** from the Dominus app), Polish provided as a translation.
- HACS-ready layout (`custom_components/`, `hacs.json`), MIT license, author metadata.

### 0.2.x

- 0.2.10 — "Set the same profile for all days" schedule shortcut.
- 0.2.9 — CO heating schedule (32 `time` entities + 7 weekday selects).
- 0.2.8 — Boiler fault reporting (code, description, active, reset-available).
- 0.2.7 — Heating curve offset (U03) for Zone 2/3.
- 0.2.6 — Zone 2/3 disabled at the device level; setpoints as sliders.
- 0.2.5 — Zone 2/3 entities; dynamic polling.
- 0.2.4 — DHW entities moved onto the main device.
- 0.2.3 — Outdoor `0xFF` = no probe; confirmed operation-mode mapping.
- 0.1.9 — Last-known-good caching, optimistic write updates.

## Brand assets

Bundled Home Assistant brand assets live in `custom_components/immergas_dominus/brand/`.
The icon is original project artwork (red background, white thermostat and wireless
symbols) and does not copy Immergas/Dominus app artwork.

## License

[MIT](LICENSE) © JoTu. Not affiliated with or endorsed by Immergas.
