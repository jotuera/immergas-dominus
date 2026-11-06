# Modbus po TCP – co udostępnia moduł Dominus

[English](pdu-map.md) · **Polski** · [OpenTherm](opentherm.pl.md) · powrót do [README](../README.pl.md)

Kotły, których moduł Dominus ma konfigurację Modbus (`*_MBUS_*`, np. **`WFC01_IM_MBUS_MPROCOMBOV2`**: Magis Combo /
Pro-Combo V2, Magis Pro) – **główny protokół** integracji (*Protokół: Modbus* przy konfiguracji).

Moduł Wi-Fi Dominus odpowiada na lokalnym porcie TCP **2000** po uwierzytelnionej sesji (MAC modułu + hasło). Czyta
i zapisuje kocioł przez własne połączenie z magistralą (D+/D-), ale tylko te rejestry (PDU), których używa oficjalna
apka Dominus. PDU spoza poniższej listy zwykle odpowiada po TCP zerem albo wcale, nawet jeśli istnieje na magistrali
kotła. Moduł obsługuje jednego klienta TCP naraz: Home Assistant odpytuje co ok. 45 s, tylko PDU włączonych encji,
a oficjalna apka może się połączyć w przerwach.

## Ramka

7 bajtów: `[typ, PDU hi, PDU lo, wartość hi, wartość lo, CRC, CRC]`, 16-bitowy adres PDU, 16-bitowa wartość ze
znakiem. Odczyt i zapis mają różne kody `typ`; zapis wraca z wartością przyjętą przez kocioł (ACK) i to ją pokazuje
integracja, nie wartość żądaną. Temperatury to °C × 10.

## Urządzenie główne

| PDU | Znaczenie | R/W | Wartość | Encja |
|---|---|---|---|---|
| 2000 | Tryb pracy | R/W | 0 Standby, 1 Lato, 2 Chłodzenie, 3 Zima | Tryb pracy (select), tryb termostatów |
| 2001 | Flagi stanu kotła | R | młodszy bajt bit 0 = żądanie CWU (ok. 9 min przed cyklem CWU) | Żądanie CWU |
| 2095 | Nastawa CWU | R/W | °C × 10 | Zadana CWU, Termostat CWU |
| 2100 | Kod błędu | R | 0 = brak, inaczej E&lt;kod&gt; | Kod błędu kotła, Opis błędu kotła, Błąd kotła |
| 2101 | Flagi błędu | R | młodszy bajt bit 1 = reset dostępny | Reset dostępny |
| 3002 | Temperatura zewnętrzna | R | °C × 10; 255 = brak sondy | Temperatura zewnętrzna |
| 3016 | Temperatura zasobnika CWU | R | °C × 10 | Temperatura zasobnika CWU, Termostat CWU |
| 4199 | Liczba stref | R | 1–3 | Liczba stref |

## Strefy (strefa 2 = +10, strefa 3 = +20)

| PDU (strefa 1) | Znaczenie | R/W | Wartość | Encja |
|---|---|---|---|---|
| 2010 | Status strefy | R | bit 2 ręczny, bit 3 żądanie grzania, bit 6 faza Komfort, bit 7 faza Eko | Strefa 1 status, Strefa 1 żądanie grzania, Strefa 1 faza programu |
| 2011 | Temperatura pokoju | R | °C × 10; 32767 = brak czujnika | Strefa 1 temperatura pokojowa, Strefa 1 termostat |
| 2015 | Zadana pokoju | R/W | °C × 10 | Strefa 1 zadana ogrzewania, Strefa 1 termostat |
| 2017 | Offset krzywej (U03) | R/W | °C × 10 (strefy 2/3 wyprowadzone ze wzoru +10) | Strefa 1 offset krzywej grzewczej |
| 2210 / 2211 | Komfort / Eko grzanie | R/W | °C × 10 | Strefa 1 komfort grzanie / eco grzanie, presety termostatu |
| 2214 / 2215 | Komfort / Eko chłodzenie | R/W | °C × 10 | Strefa 1 komfort chłodzenie / eco chłodzenie |
| 2216 | Zadana wilgotności | R/W | % | Strefa 1 zadana wilgotności |
| 2217 | Zadana zasilania | R/W | °C × 10 | Strefa 1 zadana zasilania |

**Temperaturę pokoju (2011)** moduł nie mierzy sam: pochodzi z panelu strefy na D+/D- (fizycznego albo emulowanego
przez hub). Po TCP nie ma rejestru wersji panelu, więc panel fizyczny i emulowany wyglądają tak samo. Termostat
pokojowy on/off daje tylko żądanie grzania (nie testowane).

**Termostat pokojowy.** Dominus go nie zgłasza; kafel **Termostat** w karcie Łączność pokazuje to, co mówi deklarowany
**sposób sterowania A31** (Parametry pieca, offline): RP – sam panel strefy, RPT – panel daje temperaturę i nastawę,
a termostat pokojowy włącza i wyłącza grzanie, RT – sam termostat pokojowy. **Zapis temperatury pokoju przez TCP nie
działa:** test na Magis Pro-Combo V2 (05.11.2026) – moduł odesłał PDU 2011 jako potwierdzenie, ale 2011 zostało przy
wartości z panelu strefy. Temperaturę z Home Assistant kocioł dostaje tylko przez panel strefy emulowany na D+/D- – robi to
hub (jego *Źródło temperatury Strefy 1*: kocioł przyjął nową wartość w ciągu 20 s).

## Programy czasowe

| PDU | Znaczenie | Wartość | Encja |
|---|---|---|---|
| 2310–2347 | Kalendarze 1–4, każdy z 4 zakresami (start / koniec) | baza kalendarza P = 2300 + P × 10, start zakresu F = baza + (F−1) × 2, koniec = start + 1; starszy bajt = godzina, młodszy = minuta | Kalendarz P zakres F start / koniec (time, domyślnie wyłączone) |
| 2410–2416 | Strefa 1: kalendarz poniedziałku–niedzieli | młodszy bajt = 1–4 | Strefa 1 — Poniedziałek … Niedziela, Strefa 1 — ten sam profil dla wszystkich dni |
| 2420–2426 / 2430–2436 | Strefa 2 / strefa 3 | jak wyżej | – |
| 2490–2496 | CWU: kalendarz poniedziałku–niedzieli | jak wyżej (kalendarze są wspólne) | używa go CWU Komfort-Eko wg harmonogramu |

Kocioł ma jedną nastawę CWU, a jego harmonogram CWU tylko zezwala na grzanie albo je blokuje. *CWU Komfort-Eko wg
harmonogramu* w integracji sama przełącza PDU 2095 między dwiema wartościami.

## Odpowiadają, znaczenie nieznane

Znalezione **skanerem PDU** na Magis Pro-Combo V2 (zakres 2000–2016): **2012 = 570** i **2016 = 300**. 2012 kocioł
zapisuje też na magistrali D+/D- (570). Jeśli wiesz, co oznaczają, albo Twój kocioł odpowiada na inne PDU, użyj
**Zgłoś mapę PDU** (niżej).

## Niedostępne po TCP

Rejestry, które są na magistrali D+/D-, ale nie ma ich w konfiguracji apki Dominus: temperatury zasilania i powrotu
pompy ciepła i kotła (3011–3015, 3003), zegar kotła (2300, 2302, 2303), funkcja nocna U11, przełącznik AUTO / MANUAL
programu czasowego Strefy 1 oraz wszystko z magistral T-/T+ (BMS) i F1/F2 (Samsung NASA) – sprężarka, COP, obieg
chłodniczy. Do tego służy [IMMERGAS Modbus BMS NASA Hub](https://github.com/jotuera/immergas-modbus-bms-nasa-hub).

To, czego kocioł nie ma w PDU, integracja trzyma **w Home Assistant**: statystyki, urlop, automatyczne Lato / Zima,
alerty i deklarowane parametry kotła (krzywa R02–R13, T02, T05, I01–I10, A31, P07, antylegionella P13–P17) – zob.
*Statystyki i automatyki* w README.

## Zmapuj swój kocioł

Urządzenie Dominus ma **skaner PDU** (1.6.6) w *Diagnostyce* / *Konfiguracji*: ustaw **Skan PDU od** / **Skan PDU do**
(do 2000 PDU, np. 2000–2999) i **Model kotła** (z tabliczki), naciśnij **Skanuj PDU** (ok. sekundy na PDU, zwykłe
odpytywanie trwa dalej; ponowne naciśnięcie zatrzymuje). **Zgłoś mapę PDU** tworzy powiadomienie z linkiem do
**gotowego zgłoszenia na GitHubie** (model, wersja integracji, mapa – bez hosta, MAC i hasła). Nic nie jest wysyłane
automatycznie. PDU, którego kocioł nie udostępnia, zwykle daje 0, więc zera są wypisane osobno.

## Kotły gazowe (Modbus)

Nowa platforma Immergas – VICTRIX ZEUS Superior 25 / 30 / 35, HERCULES 25 / 35 / 35 ABT / Mini 35 / Solar 25 i VICTRIX
EXTRA – łączy Dominusa tą samą magistralą Modbus (menu kotła *Modbus / Typ* = **Dominus**; EXTRA: P.18 = 1). Mapa
powyżej pochodzi z pompy ciepła MAGIS; które PDU odpowiadają w kotle gazowym, **nie jest jeszcze potwierdzone** –
tryb (2000), nastawy strefy i CWU (2015 / 2095), kod błędu (2100) i programy czasowe powinny być te same, bo aplikacja
Dominus pokazuje je dla każdego kotła.

Ustaw **Typ urządzenia** = *Kocioł gazowy* (1.6.13): tryb pracy i termostaty tracą *Chłodzenie*, a tablica ukrywa to,
co ma tylko pompa ciepła – Komfort / Eko chłodzenia, zadaną wilgotność, krzywą chłodzenia R10–R13, funkcję nocną U11 i
integrację kotła I01–I10. Potem uruchom **skaner PDU** i wyślij raport, żeby potwierdzić mapę dla Twojego kotła.

Bez Dominusa te same kotły może prowadzić jako slave Modbus **BMS** (*Typ* = BMS)
[hub](https://github.com/jotuera/immergas-modbus-bms-nasa-hub/blob/main/docs/gas-boiler-bms.pl.md) ESPHome – inna mapa
rejestrów (0–1027); BMS i Dominus się wykluczają.

## Kotły OpenTherm

Kotły bez konfiguracji Modbus (VICTRIX ZEUS / AVIO, STAR …) używają przez ten sam moduł OpenTherm: zob.
[OpenTherm po TCP](opentherm.pl.md).
