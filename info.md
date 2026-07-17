# Immergas Dominus

Local Home Assistant integration for an Immergas boiler via the **Dominus** Wi-Fi module —
direct local TCP, no cloud and no MQTT.

**Tested on Immergas Magis Combo and Magis Pro** (MPROCOMBOV2). Other Immergas models
using the same Dominus module may work but are not verified.

- Operation mode, DHW and per-zone heating setpoints (sliders), thermostats.
- Boiler fault reporting with English descriptions from the Dominus app fault table.
- Optional CO heating schedule (day profiles + weekday assignment), disabled by default.

English by default, full Polish translation. Configure with the Dominus module host/IP,
port `2000`, MAC and password.

Author: **JoTu** — https://github.com/jotuera
