# What the Dominus module exposes over local TCP

**English** · [Polski](pdu-map.pl.md) · back to the [README](../README.md)

The Dominus Wi-Fi module answers on local TCP port **2000** after an authenticated session (module MAC + password).
It reads and writes the boiler through its own bus connection, but only the registers (PDUs) that the official
Dominus app uses. A PDU that is not on the list below usually answers 0 or nothing over TCP, even if it exists on the
boiler bus.

## Frame (Modbus boilers: Magis Combo / Pro and other `*_MBUS_*` configurations)

7 bytes: `[type, PDU hi, PDU lo, value hi, value lo, CRC, CRC]`, 16-bit PDU address, 16-bit signed value. Reads and
writes use different `type` codes; a write is answered with the value the boiler accepted (ACK).

## Main device

| PDU | Meaning | Access | Value |
|---|---|---|---|
| 2000 | Operating mode | read / write | 0 Standby, 1 Summer, 2 Cooling, 3 Winter |
| 2001 | Boiler status flags | read | low byte bit 0 = DHW request (set ~9 min before a DHW cycle) |
| 2095 | DHW setpoint | read / write | °C × 10 |
| 2100 | Fault code | read | 0 = no fault, otherwise E&lt;code&gt; |
| 2101 | Fault flags | read | low byte bit 1 = reset available |
| 3002 | Outdoor temperature | read | °C × 10; 255 = no outdoor probe |
| 3016 | DHW cylinder temperature | read | °C × 10 |
| 4199 | Number of zones | read | 1–3 |

## Zones (zone 2 = +10, zone 3 = +20)

| PDU (zone 1) | Meaning | Access | Value |
|---|---|---|---|
| 2010 | Zone status | read | bit 2 manual, bit 3 heating demand, bit 6 Comfort phase, bit 7 Eco phase |
| 2011 | Room temperature | read | °C × 10; 32767 = no room sensor. The module does not measure it: it comes from a zone panel on D+/D- (physical, or emulated by the hub). There is no panel firmware register over TCP, so a physical and an emulated panel look the same. An on/off room thermostat gives only the heating demand (not tested). |
| 2015 | Room setpoint (target) | read / write | °C × 10 |
| 2017 | Heating curve offset (U03) | read / write | °C × 10 (zones 2/3 inferred from the +10 pattern) |
| 2210 / 2211 | Comfort / Eco heating | read / write | °C × 10 |
| 2214 / 2215 | Comfort / Eco cooling | read / write | °C × 10 |
| 2216 | Humidity setpoint | read / write | % |
| 2217 | Flow setpoint | read / write | °C × 10 |

## Time programs

| PDU | Meaning | Value |
|---|---|---|
| 2310–2347 | Calendars 1–4, each with 4 ranges (start / end) | calendar P base = 2300 + P × 10, range F start = base + (F−1) × 2, end = start + 1; high byte = hour, low byte = minute |
| 2410–2416 | Zone 1: calendar of Monday–Sunday | low byte = 1–4 |
| 2420–2426 / 2430–2436 | Zone 2 / zone 3 | as above |
| 2490–2496 | DHW: calendar of Monday–Sunday | as above (the calendars are shared) |

The boiler keeps one DHW setpoint; its DHW schedule only allows or blocks heating. *DHW Comfort-Eco by schedule* in
the integration switches PDU 2095 between the two values itself.

## Not readable over TCP

Registers that exist on the D+/D- bus but are not in the Dominus app configuration: heat-pump and boiler flow /
return temperatures (3011–3015, 3003), the boiler clock (2300, 2302, 2303), the night function U11, the zone 1
AUTO / MANUAL time-program switch, and everything on the T-/T+ (BMS) and F1/F2 (Samsung NASA) buses – compressor,
COP, refrigerant circuit. For those see the
[IMMERGAS Modbus BMS NASA Hub](https://github.com/jotuera/immergas-modbus-bms-nasa-hub).

## OpenTherm boilers (experimental)

Boilers without the Modbus configuration (VICTRIX ZEUS / AVIO, STAR…) use a 6-byte OpenTherm frame
`[type, Data-ID, hi, lo, CRC, CRC]`. The integration reads Data-ID 0 (status: fault, CH, DHW, flame), 1 (CH setpoint),
5 (fault code), 17 (modulation), 18 (CH pressure), 19 (DHW flow), 25 / 28 (flow / return), 26 (DHW), 27 (outdoor),
56 (DHW setpoint) and 57 (max CH); it writes Data-ID 1 and 56. Values the boiler does not support stay empty.
