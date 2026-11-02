# Co moduł Dominus udostępnia po lokalnym TCP

[English](pdu-map.md) · **Polski** · powrót do [README](../README.pl.md)

Moduł Wi-Fi Dominus odpowiada na lokalnym porcie TCP **2000** po uwierzytelnionej sesji (MAC modułu + hasło).
Czyta i zapisuje kocioł przez własne połączenie z magistralą, ale tylko te rejestry (PDU), których używa oficjalna
apka Dominus. PDU spoza poniższej listy zwykle odpowiada po TCP zerem albo wcale, nawet jeśli istnieje na magistrali
kotła.

## Ramka (kotły Modbus: Magis Combo / Pro i inne konfiguracje `*_MBUS_*`)

7 bajtów: `[typ, PDU hi, PDU lo, wartość hi, wartość lo, CRC, CRC]`, 16-bitowy adres PDU, 16-bitowa wartość ze
znakiem. Odczyt i zapis mają różne kody `typ`; zapis wraca z wartością przyjętą przez kocioł (ACK).

## Urządzenie główne

| PDU | Znaczenie | Dostęp | Wartość |
|---|---|---|---|
| 2000 | Tryb pracy | odczyt / zapis | 0 Standby, 1 Lato, 2 Chłodzenie, 3 Zima |
| 2001 | Flagi stanu kotła | odczyt | młodszy bajt bit 0 = żądanie CWU (ok. 9 min przed cyklem CWU) |
| 2095 | Nastawa CWU | odczyt / zapis | °C × 10 |
| 2100 | Kod błędu | odczyt | 0 = brak, inaczej E&lt;kod&gt; |
| 2101 | Flagi błędu | odczyt | młodszy bajt bit 1 = reset dostępny |
| 3002 | Temperatura zewnętrzna | odczyt | °C × 10; 255 = brak sondy |
| 3016 | Temperatura zasobnika CWU | odczyt | °C × 10 |
| 4199 | Liczba stref | odczyt | 1–3 |

## Strefy (strefa 2 = +10, strefa 3 = +20)

| PDU (strefa 1) | Znaczenie | Dostęp | Wartość |
|---|---|---|---|
| 2010 | Status strefy | odczyt | bit 2 ręczny, bit 3 żądanie grzania, bit 6 faza Komfort, bit 7 faza Eko |
| 2011 | Temperatura pokoju | odczyt | °C × 10; 32767 = brak czujnika |
| 2015 | Zadana pokoju | odczyt / zapis | °C × 10 |
| 2017 | Offset krzywej (U03) | odczyt / zapis | °C × 10 (strefy 2/3 wyprowadzone ze wzoru +10) |
| 2210 / 2211 | Komfort / Eko grzanie | odczyt / zapis | °C × 10 |
| 2214 / 2215 | Komfort / Eko chłodzenie | odczyt / zapis | °C × 10 |
| 2216 | Zadana wilgotności | odczyt / zapis | % |
| 2217 | Zadana zasilania | odczyt / zapis | °C × 10 |

## Programy czasowe

| PDU | Znaczenie | Wartość |
|---|---|---|
| 2310–2347 | Kalendarze 1–4, każdy z 4 zakresami (start / koniec) | baza kalendarza P = 2300 + P × 10, start zakresu F = baza + (F−1) × 2, koniec = start + 1; starszy bajt = godzina, młodszy = minuta |
| 2410–2416 | Strefa 1: kalendarz poniedziałku–niedzieli | młodszy bajt = 1–4 |
| 2420–2426 / 2430–2436 | Strefa 2 / strefa 3 | jak wyżej |
| 2490–2496 | CWU: kalendarz poniedziałku–niedzieli | jak wyżej (kalendarze są wspólne) |

Kocioł ma jedną nastawę CWU, a jego harmonogram CWU tylko zezwala na grzanie albo je blokuje. *CWU Komfort-Eko wg
harmonogramu* w integracji sama przełącza PDU 2095 między dwiema wartościami.

## Niedostępne po TCP

Rejestry, które są na magistrali D+/D-, ale nie ma ich w konfiguracji apki Dominus: temperatury zasilania i powrotu
pompy ciepła i kotła (3011–3015, 3003), zegar kotła (2300, 2302, 2303), funkcja nocna U11, przełącznik AUTO / MANUAL
programu czasowego Strefy 1 oraz wszystko z magistral T-/T+ (BMS) i F1/F2 (Samsung NASA) – sprężarka, COP, obieg
chłodniczy. Do tego służy [IMMERGAS Modbus BMS NASA Hub](https://github.com/jotuera/immergas-modbus-bms-nasa-hub).

## Kotły OpenTherm (eksperymentalnie)

Kotły bez konfiguracji Modbus (VICTRIX ZEUS / AVIO, STAR…) używają 6-bajtowej ramki OpenTherm
`[typ, Data-ID, hi, lo, CRC, CRC]`. Integracja czyta Data-ID 0 (status: błąd, CO, CWU, płomień), 1 (nastawa CO),
5 (kod błędu), 17 (modulacja), 18 (ciśnienie CO), 19 (przepływ CWU), 25 / 28 (zasilanie / powrót), 26 (CWU),
27 (zewnętrzna), 56 (nastawa CWU) i 57 (maks. CO); zapisuje Data-ID 1 i 56. Wartości, których kocioł nie obsługuje,
zostają puste.
