# Modbus over TCP – what the Dominus module exposes

**English** · [Polski](pdu-map.pl.md) · [OpenTherm](opentherm.md) · back to the [README](../README.md)

Boilers whose Dominus module uses a Modbus configuration (`*_MBUS_*`, e.g. **`WFC01_IM_MBUS_MPROCOMBOV2`**: Magis
Combo / Pro-Combo V2, Magis Pro) – the **main protocol** of the integration (*Protocol: Modbus* in the setup).

The Dominus Wi-Fi module answers on local TCP port **2000** after an authenticated session (module MAC + password).
It reads and writes the boiler through its own bus connection (D+/D-), but only the registers (PDUs) that the
official Dominus app uses. A PDU that is not on the list below usually answers 0 or nothing over TCP, even if it
exists on the boiler bus. The module serves one TCP client at a time: Home Assistant polls about every 45 s, only the
PDUs of enabled entities, and the official app can still connect in between.

## Frame

7 bytes: `[type, PDU hi, PDU lo, value hi, value lo, CRC, CRC]`, 16-bit PDU address, 16-bit signed value. Reads and
writes use different `type` codes; a write is answered with the value the boiler accepted (ACK), and the integration
shows that value, not the requested one. Temperatures are °C × 10.

## Main device

| PDU | Meaning | R/W | Value | Entity |
|---|---|---|---|---|
| 2000 | Operating mode | R/W | 0 Standby, 1 Summer, 2 Cooling, 3 Winter | Operation mode (select), mode of the thermostats |
| 2001 | Boiler status flags | R | low byte bit 0 = DHW request (set ~9 min before a DHW cycle) | DHW request |
| 2095 | DHW setpoint | R/W | °C × 10 | DHW target, DHW (thermostat) |
| 2100 | Fault code | R | 0 = no fault, otherwise E&lt;code&gt; | Boiler fault code, Boiler fault description, Boiler fault |
| 2101 | Fault flags | R | low byte bit 1 = reset available | Reset available |
| 3002 | Outdoor temperature | R | °C × 10; 255 = no outdoor probe | Outdoor temperature |
| 3016 | DHW cylinder temperature | R | °C × 10 | DHW tank temperature, DHW (thermostat) |
| 4199 | Number of zones | R | 1–3 | Number of zones |

## Zones (zone 2 = +10, zone 3 = +20)

| PDU (zone 1) | Meaning | R/W | Value | Entity |
|---|---|---|---|---|
| 2010 | Zone status | R | bit 2 manual, bit 3 heating demand, bit 6 Comfort phase, bit 7 Eco phase | Zone 1 status, Zone 1 heating demand, Zone 1 program phase |
| 2011 | Room temperature | R | °C × 10; 32767 = no room sensor | Zone 1 room temperature, Zone 1 thermostat |
| 2015 | Room setpoint (target) | R/W | °C × 10 | Zone 1 heating target, Zone 1 thermostat |
| 2017 | Heating curve offset (U03) | R/W | °C × 10 (zones 2/3 inferred from the +10 pattern) | Zone 1 heating curve offset |
| 2210 / 2211 | Comfort / Eco heating | R/W | °C × 10 | Zone 1 comfort heat / eco heat, thermostat presets |
| 2214 / 2215 | Comfort / Eco cooling | R/W | °C × 10 | Zone 1 comfort cool / eco cool |
| 2216 | Humidity setpoint | R/W | % | Zone 1 humidity target |
| 2217 | Flow setpoint | R/W | °C × 10 | Zone 1 flow target |

**Room temperature (2011)** is not measured by the module: it comes from a zone panel on D+/D- (physical, or emulated
by the hub). There is no panel firmware register over TCP, so a physical and an emulated panel look the same. An
on/off room thermostat gives only the heating demand (not tested).

**Room thermostat.** The Dominus does not report it; the **Thermostat** tile of the Connectivity card shows what the
declared **A31 room control** (Boiler parameters, offline) says: RP – the zone panel only, RPT – the panel gives the
temperature and setpoint and the room thermostat switches heating, RT – the room thermostat only. **Writing the room
temperature over TCP does not work:** a test on a Magis Pro-Combo V2 (05.11.2026) got PDU 2011 echoed as the
acknowledgement while 2011 kept the zone panel's value. A room temperature from Home Assistant needs the zone panel
emulated on D+/D- – the hub does it (its *Zone 1 temperature source*: the boiler took the new value within 20 s).

## Time programs

| PDU | Meaning | Value | Entity |
|---|---|---|---|
| 2310–2347 | Calendars 1–4, each with 4 ranges (start / end) | calendar P base = 2300 + P × 10, range F start = base + (F−1) × 2, end = start + 1; high byte = hour, low byte = minute | Calendar P range F start / end (time, disabled by default) |
| 2410–2416 | Zone 1: calendar of Monday–Sunday | low byte = 1–4 | Zone 1 — Monday … Sunday, Zone 1 — same profile for all days |
| 2420–2426 / 2430–2436 | Zone 2 / zone 3 | as above | – |
| 2490–2496 | DHW: calendar of Monday–Sunday | as above (the calendars are shared) | used by DHW Comfort-Eco by schedule |

The boiler keeps one DHW setpoint; its DHW schedule only allows or blocks heating. *DHW Comfort-Eco by schedule* in
the integration switches PDU 2095 between the two values itself.

## Answered, meaning unknown

Found by the **PDU scanner** on a Magis Pro-Combo V2 (range 2000–2016): **2012 = 570** and **2016 = 300**. 2012 is also
written by the boiler on the D+/D- bus (570). If you know what they mean, or your boiler answers other PDUs, use
**Report PDU map** (below).

## Not readable over TCP

Registers that exist on the D+/D- bus but are not in the Dominus app configuration: heat-pump and boiler flow /
return temperatures (3011–3015, 3003), the boiler clock (2300, 2302, 2303), the night function U11, the zone 1
AUTO / MANUAL time-program switch, and everything on the T-/T+ (BMS) and F1/F2 (Samsung NASA) buses – compressor,
COP, refrigerant circuit. For those see the
[IMMERGAS Modbus BMS NASA OpenTherm HUB](https://github.com/jotuera/immergas-modbus-bms-nasa-opentherm-hub).

What the boiler has no PDU for, the integration keeps **in Home Assistant**: statistics, vacation, automatic Summer /
Winter, alerts and the declared boiler parameters (heating curve R02–R13, T02, T05, I01–I10, A31, P07, anti-legionella
P13–P17) – see *Statistics and automations* in the README.

## Map your boiler

The Dominus device has a **PDU scanner** (1.6.6) in *Diagnostic* / *Configuration*: set **PDU scan from** / **PDU scan
to** (up to 2000 PDUs, e.g. 2000–2999) and the **Boiler model** (rating plate), press **Scan PDUs** (about a second per
PDU, the normal polling continues; press again to stop). **Report PDU map** creates a notification with a link to a
**pre-filled GitHub issue** (model, integration version, the map – no host, MAC or password). Nothing is sent
automatically. A PDU the boiler does not provide usually reads 0, so the zeros are listed separately.

## Gas boilers (Modbus)

The new Immergas platform – VICTRIX ZEUS Superior 25 / 30 / 35, HERCULES 25 / 35 / 35 ABT / Mini 35 / Solar 25 and
VICTRIX EXTRA – connects the Dominus over the same Modbus bus (boiler menu *Modbus / Type* = **Dominus**; EXTRA:
P.18 = 1). The map above comes from a MAGIS heat pump; which PDUs a gas boiler answers is **not confirmed yet** – the
mode (2000), the zone and DHW setpoints (2015 / 2095), the fault code (2100) and the time programs are expected to be
the same, because the Dominus app shows them for every boiler.

Set **Device type** = *Gas boiler* (1.6.13): the operation mode and the climates drop *Cooling*, and the dashboard
hides what only a heat pump has – Comfort / Eco cooling, the humidity setpoint, the cooling curve R10–R13, the night
function U11 and the boiler integration I01–I10. Then run the **PDU scanner** and send the report, so the map can be
confirmed for your boiler.

Without a Dominus the same boilers can be run as a Modbus **BMS** slave (*Type* = BMS) by the ESPHome
[hub](https://github.com/jotuera/immergas-modbus-bms-nasa-opentherm-hub/blob/main/docs/gas-boiler-bms.md) – a different
register map (0–1027); BMS and Dominus exclude each other.

## OpenTherm boilers

Boilers without the Modbus configuration (VICTRIX ZEUS / AVIO, STAR …) use OpenTherm through the same module:
see [OpenTherm over TCP](opentherm.md).
