# Changelog

**English** · [Polski](CHANGELOG.pl.md)

The full history is in the README, section [Changelog](README.md#changelog), and every release has its notes on
[GitHub Releases](https://github.com/jotuera/immergas-dominus/releases). The latest versions in short:

| Version | Highlights |
|---|---|
| 1.6.39 | Hub cards 0.93.3: assumed DHW flow rate; the hub diagram animates the shared return during DHW |
| 1.6.38 | Hub cards 0.93.2: assumed flow rate in the Boiler parameters (offline) card (MAGIS without T-/T+) |
| 1.6.37 | Hub cards 0.93.1: the diagram's DHW setpoint falls back to D05 |
| 1.6.36 | Hub cards 0.93.0: hub dashboard for a MAGIS without T-/T+ (copies of the boiler menu values) |
| 1.6.35 | Hub cards 0.92.2: installations without T-/T+ – circulator follows the compressor, strategy option `variant: pro` |
| 1.6.34 | Hub cards 0.92.1: the *No faults* texts are recognised in all 11 languages (no false fault banner) |
| 1.6.33 | VICTRIX MAIOR TT: own *Boiler menu profile* (no t3 / t4, t2 = DHW thermostat), listed with the OpenTherm boilers; hub cards 0.92.0 |
| 1.6.32 | Now card: the last 6 h strip joins runs split by a defrost, so a defrost is not counted as new starts; hub cards 0.91.9 |
| 1.6.31 | ZEUS Superior / HERCULES: the target calculated from P66 is rounded like the boiler does it (outdoor to a whole degree, the result in whole degrees); hub cards 0.91.8 |
| 1.6.30 | Frontend: hub cards 0.91.7 (no Dominus changes) |
| 1.6.29 | Diagram: the note box wraps its text onto two lines and no longer covers the heating pipe; hub cards 0.91.6 |
| 1.6.28 | 23 more boiler fault descriptions in 11 languages; OpenTherm: module OTC setpoint on the weather curve card; hub cards 0.91.5 |
| 1.6.27 | OpenTherm: VICTRIX TT and Maior TT in the ZEUS 25 / OMNIA menu profile; docs: the other Modbus configurations of the app; hub cards 0.91.4 |
| 1.6.26 | OpenTherm: boiler menu profiles checked against the manuals: EXA 28 / 32 moved to the S / P / t family, new VICTRIX HYBRID profile, OMNIA V2 named, TERA short-cycling hint fixed; hub cards 0.91.3 |
| 1.6.25 | OpenTherm: read-only diagnostics of module parameters 0 and 1 (Dominus in control, thermostat input, control timer) |
| 1.6.24 | OpenTherm: gas or electricity and last DHW cycle cards; Modbus dashboard: Connectivity under Charts, settings under Automations; hub cards 0.91.2 |
| 1.6.23 | OpenTherm: CH target calculated from the boiler curve P66 (ZEUS Superior, HERCULES), hub cards 0.90.1 |
| 1.6.22 | card themes: Automatic, Light, Dark and the built-in Mocha Neon, vivid colours by default, hub cards 0.90.0 |
| 1.6.21 | OpenTherm dashboard: Online settings and Boiler parameters under Automations, side by side, hub cards 0.89.4 |
| 1.6.20 | OpenTherm diagram: heating temperature held during DHW, CH limit shown as max., hub cards 0.89.3 |
| 1.6.19 | readable cards on a light Home Assistant theme, hub cards 0.89.2 |
| 1.6.18 | cards fully translated into 9 languages (998 missing texts), OpenTherm dashboard: Connectivity under Charts, hub cards 0.88.0 |
| 1.6.17 | OpenTherm: CH supervision with an alarm when the boiler does not take up the demand, hub cards 0.87.0 |
| 1.6.16 | entity names in all 11 languages, wiring diagrams in the README, hub cards 0.86.0 |
| 1.6.15 | OpenTherm: *Running without the CAR V2* fits a weather-compensated boiler; IMG BUS terminals 41 / 44 in the hint |
| 1.6.14 | *Today · analysis* card; more Modbus statistics (comfort, building, phases, DHW); OpenTherm computed values |
| 1.6.13 | device type (heat pump / gas boiler) in the Modbus mode |
| 1.6.0 – 1.6.12 | the OpenTherm mode: Data-ID map, programs and regulator in Home Assistant, read-only mode for a remote in charge, boiler menu profiles |
| 1.0 – 1.5 | the Modbus integration for MAGIS PRO / COMBO V2: mode, setpoints, zones, schedules, faults, dashboard cards |
