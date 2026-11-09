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
| 6 | Remote DHW setpoint enabled / writable, Remote max CH setpoint enabled / writable (*off*) | R | ❌ | ✅ (0x0000) |
| 10 / 11 | – (the boiler's own parameters, TSP: read by **Scan Data-IDs**, attribute *boiler_parameters*) | scan | ✅ (42) | ❌ |
| 12 / 13 | Fault history (*off*) – number of entries, each code in the attributes; also read by the scan | R | ✅ (5) | ❌ / ✅ |
| 15 | Boiler max. capacity, Boiler min. modulation | R | ✅ (0 / 0) | ✅ |
| 16 | Room setpoint | R/W | ✅ | ✅ |
| 17 | Modulation level | R | ✅ | ✅ |
| 18 | CH water pressure | R | ❌ | ❌ |
| 19 | DHW flow rate | R | ❌ | ✅ (always 0) |
| 20 | Boiler day / time (*off*), the weekday in the attributes | R | ❌ | ✅ |
| 24 | Room temperature | R | ✅ | ❌ |
| 25 / 28 | Flow / Return temperature | R | ✅ | ✅ |
| 26 | DHW temperature | R | ✅ | ✅ |
| 27 | Outside temperature | R | ✅ | ✅ |
| 29 / 30 | Solar cylinder / collector temperature (*off*, empty at 115 °C = no probe) | R | ❌ | ✅ (no probe) |
| 32 | DHW 2 temperature (*off*, empty at 115 °C = no probe) | R | ❌ | ✅ (no probe) |
| 33 | Exhaust temperature | R | ✅ | ✅ |
| 35 | Fan speed, Fan speed setpoint (*off*) | R | ✅ | ❌ |
| 36 | Flame current (*off*) | R | ✅ (not available) | ❌ |
| 48 / 49 | – (DHW / CH setpoint limits: the sliders follow them) | R | ✅ | ✅ |
| 56 | DHW setpoint | R/W | ✅ | ✅ |
| 57 | Max CH setpoint | R | ✅ | ✅ |
| 89 / n | Dominus module parameters: CH setpoint (17), Heating curve (4), CH temperature offset (5), Outdoor sensor (6), Modulation (7), Room hysteresis (8), Room sensor (9), Building inertia (10), Dominus probe use (11), Frost protection and its temperature (14 / 15), Minimum CH temperature (16) | R/W | ✅ | ✅ |

¹ No reply in the scan (a one-off timeout), but the status entities work. Answered as well, not used yet: 7,
77, 85, 88 (ventilation IDs, both / ZEUS). A scan of your boiler →
**Report Data-ID map** adds a column here.

## Boilers and terminals

Where an OpenTherm unit (CAR V2, a third-party OpenTherm room unit or an ESP OpenTherm master) goes on Immergas boilers –
from the installer manuals on immergas.pl and user reports. None of the manuals says "OpenTherm": the CAR V2 bus is
called IMG BUS, a third-party unit is a "commercially available remote". Check the wiring diagram of your boiler first.

> ⚠️ **Check the protocol first – not every Immergas remote bus is OpenTherm.** The CAR V2 speaks two protocols and
> shows which one in its information menu: **VER PI** = **IMG-BUS** (OpenTherm with minor changes – works) or **VER PC**
> = **CAR-BUS** (an older Immergas protocol – **no OpenTherm master can talk to it**, whatever the adapter or the 0xCA
> byte). Without a CAR V2 measure the remote terminals with nothing connected: **up to about 18 V DC = IMG-BUS**,
> **about 24–35 V DC (e.g. 28 V) = CAR-BUS**. Reported CAR-BUS boiler: VICTRIX TT. On a TERA the boiler may also wait
> for the CAR V2 until **P7 = 2** (third-party remote) is set and the boiler power-cycled – not confirmed yet.
> Source: [OTGateway #284](https://github.com/Laxilef/OTGateway/issues/284), CAR V2 manual 1.038958 (technical data).

| Boiler (menu family) | Remote terminals | Notes |
|---|---|---|
| VICTRIX ZEUS 25, EXA 28 1 ErP, OMNIA, OMNIA V2 (G / P / t / A) | 41 / 44, jumper X40 removed | X40 back on 40-41 without a remote. EXA 28: a third-party OpenTherm unit works without changes (users). |
| VICTRIX TERA V2 / V3 (P / t / A / S) | 41 / 44, X40 removed | **P7** = remote protocol: 0 IMG BUS (CAR V2), **2 = third-party remote** (the DHW setpoint and max. flow then stay on the boiler panel), 1 = not available. Users reported P7 = 1 – the Polish manual says 2. Immergas confirms OpenTherm on the TERA V2. |
| VICTRIX EXA 24 X 1 ErP, NIKE 24 ECO (S / P / t) | 41 / 44, X40 removed (NIKE: connector X15) | A user runs a Nest Heat Link here (OT1 on 44, OT2 on 41). |
| VICTRIX ZEUS Superior 26 / 32, HERCULES Condensing 26 / 32 / ABT 32, HERCULES Solar 26 (M1 / M3 / M5) | **41 / 44** (IMG BUS), X40 removed | OpenTherm on 41 / 44 confirmed on a ZEUS Superior 26 2 ErP (an ESP32 + OpenTherm adapter, Home Assistant community); 42 / 43 are the Super CAR terminals, not OpenTherm. HERCULES: 41 / 44 expected (same board family), not confirmed yet. **M3 P33 = ON** keeps CH working without a remote (E31). ABT 32: room thermostats on the zone board X9. *ERR>CM* on the CAR V2 = no communication. |
| New platform: ZEUS Superior 25 / 30 / 35, HERCULES 25 / 35 / 35 ABT / Mini 35 / Solar 25, VICTRIX EXTRA | IMG BUS 44-41, **MODBUS D+ / D−** | The Dominus connects over **Modbus** (menu *Modbus / Type* = Dominus, EXTRA: P.18 = 1). A third-party OpenTherm unit may go on the IMG BUS (*Remote control* = commercial, EXTRA: P.17 = 1), but not together with the Dominus: E145 master conflict. E142 = Dominus unavailable. HERCULES 25 / 35 (manual ST.007903): on the IMG BUS 44-41 jumper X40 **stays**; 40-Z / 41 is the **DIM BUS** (room thermostat of zone 1 or the zone board, X40 removed), not for a remote. |

On every older boiler **E31** (remote lost) puts the boiler in local mode and blocks the heating until it is
power-cycled. The outdoor probe is on 38-39, an on/off thermostat on 40-41. Terminal **21** ("status signal") on the
EXA is for the DIM pump groups switched by the CAR, not OpenTherm. Data that the boiler does not have (pressure, DHW flow,
outdoor temperature without a probe, cooling) reads as 0 or unsupported – the dashboard hides those tiles.

**Every OpenTherm master writes cyclically.** An OpenTherm master (the Dominus module, a CAR V2, an ESP OpenTherm master)
sends the status / enables (Data-ID 0) and the CH setpoint (1) every cycle and the DHW setpoint (56) again and again from
its own memory, not once. That is why a DHW value written by a second master does not stay. Room control with a fast PID
overshoots on these boilers (full output, then the room stays too warm for hours). The Home Assistant programs here
change the flow slowly (curve, self-learning ±1 °C a day).

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

## Replacing the CAR V2

The goal: run the boiler with the Dominus + Home Assistant and remove the CAR V2. What it needs:

1. **Jumper X40 back on boiler terminals 40-41** (or a room thermostat there). The CAR V2 is connected to terminals
   41 / 44 with X40 removed; without the CAR V2 and without X40 the boiler goes to local mode after E31 and does not
   heat (boiler manual).
2. **Clear E31**: power-cycle the boiler so it stops waiting for its remote.
3. **The Dominus probe on terminals 1-2 as the room probe** (*Dominus probe use* = room, *Room sensor* on) – for the
   room setpoint, the Comfort / Eco programs and the room frost protection. The outdoor probe goes to the boiler.
4. ***Read only (remote in charge)* off** and Home Assistant running (the module keeps the last setpoint when HA is down,
   but no phase changes).

The **OpenTherm boiler** card lists these as a checklist (*Running without the CAR V2*).

| CAR V2 | Dominus + Home Assistant |
|---|---|
| Standby / Summer / Winter | Mode (Data-ID 0) |
| Manual (room 10–35 °C), forced automatic | CH program MANUAL, Room setpoint; a manual change holds until the next phase |
| Automatic PR RIS (4 Comfort ranges a day) | CH program AUTO: 4 calendars × 4 ranges, one per weekday |
| Comfort / Economy (20 / 16 °C) | Comfort / Eco room temperatures |
| DHW dial, PR SAN (Comfort / minimum) | DHW setpoint; DHW Comfort / Eco by the DHW calendar, Eco down to the boiler minimum (Data-ID 48) |
| S.RIS max flow, OTC curve 0–9 | CH setpoint (parameter 17), Heating curve |
| ANTIGL room frost protection 0–10 °C | Frost protection and its temperature |
| Info menu | sensors (outdoor, flow, return, DHW, pressure when the boiler reports it) |
| ERR>xx, reset (max. 5 per hour) | Fault code and description, Boiler reset (5 attempts per hour) |
| REGOLAZ: MINRIS, OFFSET, DIMENS | Minimum CH temperature, CH offset, Building inertia |
| AUTO A self-learning | Self-learning (CH offset ±1 °C a day by yesterday's Comfort error) |
| VACANZ (CH and DHW off) | Vacation mode until a date, *Vacation action* Standby (default) or Summer |
| LEGION (maximum for 20 min, 02:00 daily / Monday) | Anti-legionella: the same, capped at the boiler's DHW maximum |
| AMB, MODUL | Room sensor, Modulation |
| RIDOTT OFF / ON (−1 … −40 °C) | Eco phase action: heating off / lower the flow setpoint by *Eco flow reduction* |
| MANUTZ (6–24 months) | Maintenance reminder, Last service, Service done, Maintenance due |
| AMB CR (probe correction ±3 °C) | – (no module parameter) |
| REMOTO, LANGUAGE, cooling, humidity | – (Home Assistant itself; not on these boilers) |

Beyond the CAR V2 (ideas from the Delta Dore TYBOX 137+, 1.6.12):

- **Optimum start** – in the CH program AUTO the Comfort phase starts early: (Comfort − room) / the learned heat-up rate,
  at most *Optimum start: max. lead time* (120 min). Each Comfort heat-up from at least 0.5 °C below measures the rate
  (°C/h, average 70 / 30) until the room is 0.2 °C from Comfort; it starts at 1 °C/h and is kept over a restart
  (attribute `heating_rate`). Needs the room temperature (Data-ID 24).
- **Open window** – *Window sensors* (binary sensors, comma separated): while one is open the room setpoint goes to
  *Open window temperature* (7 °C) and the program writes nothing; when all are closed the program phase (AUTO) or the
  setpoint from before (MANUAL) returns. The sensors are watched, so an opened window acts at once.

## Room thermostat

The boiler does not report a room thermostat over OpenTherm, so **Room thermostat** says what is connected:
**None**, **Physical** (an on/off thermostat on boiler contacts 40-41 – its demand is not visible, only the CH demand)
or **Emulated** – Home Assistant sends the temperature of an HA entity chosen in **Room temperature source**
(e.g. a room sensor) to the module as Data-ID 24 (WRITE-DATA "room temperature", as a room unit sends it), on a change
of 0.1 °C or every 5 minutes; *Read only* blocks it. **Experimental:** whether the Dominus regulator uses it instead of
its own probe has to be confirmed on a real boiler – the *Supported Data-IDs* / *Room temperature* readings show it.
The choice and the entity are in the **Boiler parameters (offline)** card; the **Thermostat** tile of the Connectivity card shows the state. Data-ID 24 is judged by reading it back a minute later (*it works* / *the module does not take it*) – the acknowledgement alone is no proof (a Modbus test got the written value echoed).

**Failsafe (1.6.12):** with no fresh, valid reading of the source entity for **60 minutes** (unavailable, not a number,
not updated) Data-ID 24 is no longer sent – a stale room temperature would keep the regulator on a wrong value. The tile
turns red (*No room temperature source*); sending starts again by itself when the entity reports. The boiler's own frost
protection stays active.

## Boiler menu (declared, offline)

The boiler's own menu (VICTRIX ZEUS 25 manual) cannot be read over OpenTherm yet: the boiler reports 42 transparent
slave parameters (Data-ID 10 / 11), but Immergas does not publish which number is which. Like the Modbus mode, the
integration keeps them as **declared values**, copied once from the boiler menu, empty by default (a *suggested* value
is the factory default). Nothing is written to the boiler; the **Boiler parameters (offline)** card uses them for
hints.

| Menu | Entity (factory default) | Hint on the dashboard |
|---|---|---|
| t0 / t1 | CH min. / max. flow temperature (25 / 85 °C) | next to the CH range the boiler reports (Data-ID 49) |
| t5 | CH ignitions timer, 0–600 s (180 s) | with more than 6 burner starts an hour: lengthen t5 (300–600 s) |
| t6 / t7 | CH ramp timer (180 s) / ignition delay (0 s) | – |
| t4 | DHW priority timing (20 s) | – |
| t2 | DHW thermostat: flow while heating the cylinder (1) | – |
| P0 / P1 / P2 | DHW max. / min. / CH max. output (99 / 0 / 80 %) | P1 next to the min. modulation (Data-ID 15); P2 next to boiler parameter 12 of the scan |
| P6 | pump intermittent / continuous | – |
| A3 / A4 / A5 | pump max. / min. speed, pump mode (9 / 6 / 15) | – |
| P7 | outdoor probe correction (0 K) | – |

**Menu profiles.** Immergas boilers do not share one menu: the same function has another code, range or unit. The
installer manuals give five OpenTherm menu families; **Boiler menu profile** (or a guess from the *Boiler model* text)
picks the codes the card shows. The values are the same entities in every profile.

| Function | ZEUS 25 / EXA 28 / OMNIA | TERA V2 / V3 | EXA 24 X / NIKE | ZEUS Superior 26 / 32 | HERCULES Condensing / Solar 26 |
|---|---|---|---|---|---|
| CH min. / max. flow | t0 / t1 | t0 / t1 | S5 / S6 (EXA) | P66/A / P66/B | P66/A / P66/B |
| Climatic curve (outdoor at max. / min. flow) | – | – | – | P66/C / P66/D | P66/C / P66/D |
| CH ignitions timer | t5, 0–600 s | t4 | t0 | P69, 0–255 s | P69, 0–255 s |
| CH ramp / ignition delay | t6 / t7 | t5 / t6 | t1 / t2 | P70 / P68 | P70 / P68 |
| Wait after DHW | t4 | t3 | – | – | – |
| CH max. / min. output | P2 / P1 (%) | P2 / P1 (%) | S3 / S2 rpm (EXA), S1 / S0 % (NIKE) | P64 / P65 rpm | P64 / P65 rpm |
| DHW max. / min. output | P0 (%) | P0 (%) | S1 / S0 rpm (EXA) | P57 / P62 rpm | P62 / P63 rpm |
| DHW thermostat | t2 | – | – | P71 (−3 / −10 °C) | P71 (−3 / −5 °C solar) |
| Pump mode | P6 | P4 | P2 | P67 | P67 |
| Pump speed / ΔT | A3 / A4, A5 | A1 / A2, A3 | – | P55 | P57 AUTO (ΔT) / FIX |
| Outdoor probe correction | P7 | P5 | S7 (EXA) | P76 | P76 (−15…+14) |
| Remote | – | P7 (0 CAR V2 / 2 third-party) | – | – | M3 P33 CH without a remote |
| Counters | – | – | – | M1 | M1 P12 hours, P13 ignitions |

The Superior codes P68–P76 are read from its manual and still to be confirmed on a real boiler; the HERCULES manual
suggests that P55 there is a reading and the pump is P57 / P67. The VICTRIX ZEUS 26 2 ErP has almost no numbered menu –
use the generic profile. The **new platform** (ZEUS Superior 25 / 30 / 35, HERCULES 25 / 35, VICTRIX EXTRA) is a Modbus
boiler for the Dominus – see [Modbus over TCP](pdu-map.md).

Built-in automatic functions (pump / 3-way valve anti-block every 24 h, radiator frost protection below 4 °C, P.C.B.
self-check every 18 h, automatic venting A7, chimney sweep) need no settings and are not reported over OpenTherm.
Scans together with the menu values (**Report Data-ID map**) will let the integration read them directly.

## Computed in Home Assistant (1.6.14)

From what the module reads, every poll (~45 s), no extra settings; the day / month counters and the gas counter survive
a restart. The *Today · boiler analysis* card shows them (tiles without data stay hidden).

| Group | Entities |
|---|---|
| Hydraulics | Delta T (flow − return), Mean loop temperature, **Control setpoint (Data-ID 1)** – what the module really sends, Flow deviation from the setpoint, Exhaust − return, *Condensing operation* (return below 55 °C while burning), Condensing today (share) |
| Burner and gas | Burner power (est.: modulation between the min. and max. output of Data-ID 15), Heat today, Gas today / heating / DHW and the Gas counter (m³, 10.6 kWh of useful heat per m³), Gas price, Gas cost today, Electricity price, Cylinder volume (0 = no cylinder), Last DHW cycle gas |
| Short cycling | Average burn today, Short burns (< 5 min), Last burn, Last pause, Average modulation, At min. modulation – from the flame flag of each poll, so a lower bound |
| DHW | DHW draws, Last draw, Hot water (litres) and DHW heat today (combi boilers with Data-ID 19, cold water 10 °C); DHW cycles today, Last DHW cycle and its cylinder rise (boilers with a cylinder) |
| State | *Operating state* – one text: "CH · flame 45 % · 52 °C", "DHW", "Fault E10", "Idle" |
| Diagnostics | Pressure drop in 24 h with *Possible leak* (0.2 bar), Flame current (average while burning) with *Low flame current* (2 µA), Fan speed − setpoint (Data-ID 35/36 entities are disabled by default: enable them when the boiler answers) |
| CH supervision | *CH supervision* – is a CH demand really taken up by the boiler: confirmed, DHW priority, flow near the setpoint, fault, no demand, waiting; *CH: boiler not responding* comes on after a set time (*CH supervision - time without response*, default 15 min, longer than the boiler's CH timer). The regulator is in the module, so the demand is inferred from the CH enable bit, the control setpoint (Data-ID 1) and the room temperature against its target; with a physical thermostat on the boiler contacts it cannot be seen and nothing is counted. Diagnosis only, nothing is written |
| Room and building | Room deviation from the target (1 h mean), Time to reach the target, Degree days today / this month (base 18 °C), Heating hours per degree day |

## Diagnostics

**Scan Data-IDs** (button, about a minute, polling pauses) → **Supported Data-IDs** lists what answered, what is
unsupported and the raw values, plus the boiler parameters and the fault history. **Last write** reads every write back
(*Taken* / *Acknowledged, not taken*). **Report Data-ID map** creates a notification with a link to a pre-filled GitHub
issue (boiler model, integration version, the scan – no host, MAC or password); nothing is sent automatically.

## Sources

- VICTRIX ZEUS 25 installer manual (fault codes, information menu, P / t / A / F parameters).
- Installer manuals on immergas.pl (11.2026): VICTRIX EXA 24 X / 28, NIKE 24 ECO, TERA V2 / V3, OMNIA / OMNIA V2,
  HERCULES Condensing / ABT / Solar 26, and the new platform ZEUS Superior 25-35, HERCULES 25 / 35 / Mini / Solar 25, EXTRA.
- [OTGateway compatibility](https://github.com/Laxilef/OTGateway/wiki/Compatibility) – the Immergas fix, DHW flow not
  supported on Victrix.
- [arduino.ru OpenTherm thermostat thread](https://arduino.ru/forum/programmirovanie/termostat-opentherm-na-esp8266?page=15#comment-649392)
  – the 0xCA low byte and the Immergas write sequence.
- [Elektroda: Immergas with a non-CAR controller](https://www.elektroda.pl/rtvforum/topic3843909.html) – terminals
  41 / 44 (EXA), TERA P7, TERA V2 with OpenTherm, Nest Heat Link.
- [esp_domoticz_opentherm_handler](https://github.com/akamming/esp_domoticz_opentherm_handler) – an ESP OpenTherm
  master: cyclic Data-ID 0 / 1 / 56 writes, a room-temperature failsafe.
- [OTGW firmware](https://github.com/rvdbreemen/OTGW-firmware) – `TP=11:12` for Immergas.
