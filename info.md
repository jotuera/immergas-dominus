# Immergas Dominus

Local Home Assistant integration for an Immergas boiler via the **Dominus** Wi-Fi module —
direct local TCP, no cloud and no MQTT.

**Tested on Immergas Magis Combo and Magis Pro** (MPROCOMBOV2). Other Immergas models
using the same Dominus module may work but are not verified.

- Operation mode, DHW and per-zone heating setpoints (sliders), thermostats.
- Boiler fault reporting with the project's own descriptions in 11 languages.
- Optional CO heating schedule (day profiles + weekday assignment), disabled by default.

> ⚠️ **The Dominus module accepts only ONE local connection at a time.** Home Assistant and the
> official Dominus app share it — force-close the app on the phone before changing settings from
> Home Assistant, and never connect two integrations to the same module.

English by default, full Polish translation. Configure with the Dominus module host/IP,
port `2000`, MAC and password.

Author: **JoTu** — https://github.com/jotuera
