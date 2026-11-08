# Immergas Dominus

Local Home Assistant integration for Immergas boilers and heat pumps through the **Dominus** Wi-Fi module – direct
local TCP, no cloud and no MQTT.

- **Modbus** (MAGIS PRO / COMBO V2, MAGIS Pro, other `MPROCOMBOV2` units) and **OpenTherm** (VICTRIX ZEUS, TERA, EXA,
  OMNIA …): operation mode, DHW and zone setpoints, thermostats, faults with the project's own descriptions in
  11 languages.
- A ready **dashboard** (one line: `strategy: type: custom:immergas-dominus`) with the hub cards: Now, Setpoints, Mode,
  Schedule, Curve, Today · analysis, Calibration, Automations.
- Programs and statistics computed in Home Assistant (OpenTherm: CH / DHW programs, anti-legionella, vacation, summer /
  winter; gas, condensing, short cycling, DHW draws).
- Wiring diagrams in the README: Modbus with an optional room thermostat, OpenTherm with and without the CAR V2.

> ⚠️ **The Dominus module accepts only ONE local connection at a time.** Home Assistant and the official Dominus app
> share it – close the app before changing settings from Home Assistant, and never connect two integrations to the
> same module.

Configure with the Dominus module host / IP, port `2000`, MAC and password. Entity names in 11 languages.

Author: **JoTu** – https://github.com/jotuera
