# OpenTherm over TCP – Immergas boilers without Modbus

**English** · [Polski](opentherm.pl.md) · [Modbus](pdu-map.md) · back to the [README](../README.md)

Boilers whose Dominus module has no Modbus configuration – **VICTRIX ZEUS / AVIO, STAR …** – talk to the module over
OpenTherm (Immergas calls its variant *IMG Bus*). The integration reaches them through the same local TCP port 2000
(*Protocol: OpenTherm* in the setup). Tested in [#2](https://github.com/jotuera/immergas-dominus/issues/2) on a
VICTRIX ZEUS 25 ErP (old Dominus Wi-Fi) and a Victrix Zeus Superior 26 2 ErP (Dominus V2).

## Frame and polling

6 bytes: `[type, Data-ID, value hi, value lo, CRC, CRC]` – a standard OpenTherm READ-DATA / WRITE-DATA with the
16-bit value (temperatures f8.8, i.e. /256). An *indexed* Data-ID (89 module parameters, 11 boiler parameters,
13 fault history) sends the index in the high byte and gets the value in the low byte. The integration keeps one
session, reads the Data-IDs of the enabled entities one by one and then releases the module for ~20 s so the official
app can connect. A Data-ID the boiler answers *unsupported* three times in a row is skipped for an hour; one with
**no reply** costs a timeout every cycle – keep such entities disabled.

## Data-IDs

What the integration reads (R) and writes (W), and what the boilers in #2 answered in the Data-ID scan (✅ answers,
❌ no reply, – not checked). Entities marked *off* are disabled by default – enable them when your boiler answers that
Data-ID.

| Data-ID | Entity | R/W | VICTRIX ZEUS 25 ErP<br>(old Dominus Wi-Fi) | Victrix Zeus Superior 26 2 ErP<br>(Dominus V2) |
|---|---|---|---|---|
| 0 | Fault, Central heating, Domestic hot water, Flame; Mode; Burner starts today / last hour, Burner hours today (computed from the flame) | R/W | ✅ ¹ | ✅ |
| 3 | – (slave config: DHW present / storage tank, member ID 27 = Immergas) | scan | ✅ | ✅ |
| 4 | Boiler reset (button) | W | – | – |
| 5 | Fault code, Boiler fault description; Service request, Low water pressure, Gas / flame fault, Air pressure fault, Water over-temperature | R | ✅ | ✅ |
| 10 / 11 | – (the boiler's own parameters, TSP: read by **Scan Data-IDs**, attribute *boiler_parameters*) | scan | ✅ (42) | ❌ |
| 12 / 13 | Fault history (*off*) – number of entries, each code in the attributes; also read by the scan | R | ✅ (5) | ❌ / ✅ |
| 15 | Boiler max. capacity, Boiler min. modulation | R | ✅ (0 / 0) | ✅ |
| 16 | Room setpoint | R/W | ✅ | ✅ |
| 17 | Modulation level | R | ✅ | ✅ |
| 18 | CH water pressure | R | ❌ | ❌ |
| 19 | DHW flow rate | R | ❌ | ✅ (always 0) |
| 24 | Room temperature | R | ✅ | ❌ |
| 25 / 28 | Flow / Return temperature | R | ✅ | ✅ |
| 26 | DHW temperature | R | ✅ | ✅ |
| 27 | Outside temperature | R | ✅ | ✅ |
| 33 | Exhaust temperature | R | ✅ | ✅ |
| 35 | Fan speed, Fan speed setpoint (*off*) | R | ✅ | ❌ |
| 36 | Flame current (*off*) | R | ✅ (not available) | ❌ |
| 48 / 49 | – (DHW / CH setpoint limits: the sliders follow them) | R | ✅ | ✅ |
| 56 | DHW setpoint | R/W | ✅ | ✅ |
| 57 | Max CH setpoint | R | ✅ | ✅ |
| 89 / n | Dominus module parameters: CH setpoint (17), Heating curve (4), CH temperature offset (5), Outdoor sensor (6), Modulation (7), Room hysteresis (8), Room sensor (9), Building inertia (10), Dominus probe use (11), Frost protection and its temperature (14 / 15), Minimum CH temperature (16) | R/W | ✅ | ✅ |

¹ No reply in the scan (a one-off timeout), but the status entities work. Answered as well, not used yet: 6, 7,
20 (boiler clock), 29, 30, 32 (Superior), 77, 85, 88 (ventilation IDs, both / ZEUS). A scan of your boiler →
**Report Data-ID map** adds a column here.

## Immergas specifics

- **The remote stays in charge.** With a **CAR V2** (on the Dominus terminals) or a **Super Amico** (on the boiler)
  connected, the remote runs the heating. A value written once from Home Assistant (e.g. the DHW setpoint) is **kept by
  the Dominus** and sent to the boiler over the remote's own until the module is power-cycled (#2). Turn on
  **Read only (remote in charge)** (1.6.8): Home Assistant then refuses every write, and the readings stay. The HA
  programs (CH / DHW program, anti-legionella, vacation, automatic Summer / Winter) are paused and cannot be switched
  on (1.6.9).
- **No night mode and no anti-legionella in the boiler.** The VICTRIX ZEUS manual has neither: the night reduction
  comes from the remote (CAR V2 program, chrono-thermostat), and the DHW range ends at 60 °C. Without a remote the
  integration does both in Home Assistant (CH program Eco phase, DHW Comfort / Eco, anti-legionella capped at the
  boiler's DHW maximum from Data-ID 48).
- **E31** "loss of communication with the remote" – the boiler expects the remote it was paired with; while E31 is
  active it ignores CH / DHW / mode commands from the app and from Home Assistant alike.
- **Low byte 0xCA in Data-ID 0** – the "Immergas fix" of other OpenTherm gateways (OTGateway, ESPHome users): without it
  writes to Data-ID 1 / 57 are acknowledged but change nothing. Option **Status frame low byte** (experimental,
  default standard 0x00).
- **CH setpoint** is written as module parameter 17 (Data-ID 89), as the official app does; Data-ID 1 is the control
  setpoint the module recalculates itself.
- **Stored values differ slightly** from the sent ones (a VICTRIX stores 45.0 °C as 44.7): *Last write* counts a
  setpoint within 0.5 °C as taken and reads a mismatch again a few seconds later (1.6.6).
- **Boiler parameters (TSP, Data-ID 10 / 11)** are the boiler's own menu values; Immergas does not publish their
  meaning. OTGW firmware writes TSP 12 before every max-modulation change on Immergas, so 12 is probably the max. CH
  output (P2). A report with your boiler's P / t / A / F menu values next to the scan helps to map them.
- **Fault history** (Data-ID 12 / 13) = the boiler's "last five anomalies" (menu d0.8), codes as in the boiler manual
  (e.g. E89 unstable combustion signal).

## Diagnostics

**Scan Data-IDs** (button, about a minute, polling pauses) → **Supported Data-IDs** lists what answered, what is
unsupported and the raw values, plus the boiler parameters and the fault history. **Last write** reads every write back
(*Taken* / *Acknowledged, not taken*). **Report Data-ID map** creates a notification with a link to a pre-filled GitHub
issue (boiler model, integration version, the scan – no host, MAC or password); nothing is sent automatically.

## Sources

- VICTRIX ZEUS 25 installer manual (fault codes, information menu, P / t / A / F parameters).
- [OTGateway compatibility](https://github.com/Laxilef/OTGateway/wiki/Compatibility) – the Immergas fix, DHW flow not
  supported on Victrix.
- [arduino.ru OpenTherm thermostat thread](https://arduino.ru/forum/programmirovanie/termostat-opentherm-na-esp8266?page=15#comment-649392)
  – the 0xCA low byte and the Immergas write sequence.
- [OTGW firmware](https://github.com/rvdbreemen/OTGW-firmware) – `TP=11:12` for Immergas.
