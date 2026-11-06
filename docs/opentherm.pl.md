# OpenTherm po TCP – kotły Immergas bez Modbusa

[English](opentherm.md) · **Polski** · [Modbus](pdu-map.pl.md) · powrót do [README](../README.pl.md)

Kotły, których moduł Dominus nie ma konfiguracji Modbus – **VICTRIX ZEUS / AVIO, STAR …** – rozmawiają z modułem przez
OpenTherm (Immergas nazywa swoją odmianę *IMG Bus*). Integracja dociera do nich przez ten sam lokalny port TCP 2000
(*Protokół: OpenTherm* przy konfiguracji). Przetestowane w [#2](https://github.com/jotuera/immergas-dominus/issues/2)
na VICTRIX ZEUS 25 ErP (stary Dominus Wi-Fi) i Victrix Zeus Superior 26 2 ErP (Dominus V2).

## Ramka i odpytywanie

6 bajtów: `[typ, Data-ID, wartość hi, wartość lo, CRC, CRC]` – standardowe OpenTherm READ-DATA / WRITE-DATA
z 16-bitową wartością (temperatury f8.8, czyli /256). Data-ID *indeksowany* (89 parametry modułu, 11 parametry kotła,
13 historia błędów) wysyła indeks w starszym bajcie i dostaje wartość w młodszym. Integracja trzyma jedną sesję, czyta
po kolei Data-ID włączonych encji, a potem na ~20 s zwalnia moduł, żeby mogła się połączyć oficjalna apka. Data-ID,
na który kocioł trzy razy z rzędu odpowie „nieobsługiwany”, jest pomijany przez godzinę; taki **bez odpowiedzi**
kosztuje timeout w każdym cyklu – trzymaj jego encje wyłączone.

## Data-ID

Co integracja czyta (R) i zapisuje (W) oraz co odpowiedziały kotły z #2 w skanie Data-ID (✅ odpowiada, ❌ brak
odpowiedzi, – nie sprawdzano). Encje oznaczone *off* są domyślnie wyłączone – włącz je, jeśli Twój kocioł odpowiada
na dany Data-ID.

| Data-ID | Encja | R/W | VICTRIX ZEUS 25 ErP<br>(stary Dominus Wi-Fi) | Victrix Zeus Superior 26 2 ErP<br>(Dominus V2) |
|---|---|---|---|---|
| 0 | Błąd, Ogrzewanie CO, CWU, Płomień; Tryb; Starty palnika dziś / ostatnia godzina, Czas pracy palnika dziś (liczone z płomienia) | R/W | ✅ ¹ | ✅ |
| 3 | – (konfiguracja kotła: CWU jest / zasobnik, member ID 27 = Immergas) | skan | ✅ | ✅ |
| 4 | Reset kotła (przycisk) | W | – | – |
| 5 | Kod błędu, Opis błędu kotła; Żądanie serwisu, Niskie ciśnienie wody, Błąd gazu / płomienia, Błąd ciśnienia powietrza, Przegrzanie wody | R | ✅ | ✅ |
| 6 | Zdalna nastawa CWU dostępna / zapisywalna, Zdalna maks. nastawa CO dostępna / zapisywalna (*off*) | R | ❌ | ✅ (0x0000) |
| 10 / 11 | – (własne parametry kotła, TSP: czyta je **Skanuj Data-ID**, atrybut *boiler_parameters*) | skan | ✅ (42) | ❌ |
| 12 / 13 | Historia błędów (*off*) – liczba wpisów, każdy kod w atrybutach; czyta ją też skan | R | ✅ (5) | ❌ / ✅ |
| 15 | Moc maks. kotła, Modulacja min. kotła | R | ✅ (0 / 0) | ✅ |
| 16 | Zadana temperatura pokoju | R/W | ✅ | ✅ |
| 17 | Poziom modulacji | R | ✅ | ✅ |
| 18 | Ciśnienie wody CO | R | ❌ | ❌ |
| 19 | Przepływ CWU | R | ❌ | ✅ (zawsze 0) |
| 20 | Dzień / godzina kotła (*off*), dzień tygodnia w atrybutach | R | ❌ | ✅ |
| 24 | Temperatura pokoju | R | ✅ | ❌ |
| 25 / 28 | Temperatura zasilania / powrotu | R | ✅ | ✅ |
| 26 | Temperatura CWU | R | ✅ | ✅ |
| 27 | Temperatura zewnętrzna | R | ✅ | ✅ |
| 29 / 30 | Temperatura zasobnika / kolektora solarnego (*off*, puste przy 115 °C = brak czujnika) | R | ❌ | ✅ (brak czujnika) |
| 32 | Temperatura CWU 2 (*off*, puste przy 115 °C = brak czujnika) | R | ❌ | ✅ (brak czujnika) |
| 33 | Temperatura spalin | R | ✅ | ✅ |
| 35 | Obroty wentylatora, Zadane obroty wentylatora (*off*) | R | ✅ | ❌ |
| 36 | Prąd jonizacji płomienia (*off*) | R | ✅ (niedostępny) | ❌ |
| 48 / 49 | – (limity nastaw CWU / CO: suwaki się do nich dostosowują) | R | ✅ | ✅ |
| 56 | Zadana CWU | R/W | ✅ | ✅ |
| 57 | Maks. zadana CO | R | ✅ | ✅ |
| 89 / n | Parametry modułu Dominus: Zadana CO (17), Krzywa grzewcza (4), Offset temperatury CO (5), Sonda zewnętrzna (6), Modulacja (7), Histereza pokojowa (8), Czujnik pokojowy (9), Bezwładność budynku (10), Sonda Dominusa mierzy (11), Ochrona przed zamarzaniem i jej temperatura (14 / 15), Minimalna temperatura CO (16) | R/W | ✅ | ✅ |

¹ Brak odpowiedzi w skanie (jednorazowy timeout), ale encje statusu działają. Odpowiadają też, jeszcze nieużywane: 7,
77, 85, 88 (ID wentylacji, oba / ZEUS). Skan Twojego kotła → **Zgłoś mapę
Data-ID** dodaje tu kolumnę.

## Kotły i zaciski

Gdzie podłącza się urządzenie OpenTherm (CAR V2, regulator OpenTherm innej firmy albo master ESP) w kotłach Immergas –
według instrukcji instalatora z immergas.pl i relacji użytkowników. Żadna instrukcja nie używa słowa „OpenTherm”:
magistrala CAR V2 to IMG BUS, a regulator innej firmy to „zdalne sterowanie dostępne w handlu”. Najpierw sprawdź schemat
swojego kotła.

| Kocioł (rodzina menu) | Zaciski regulatora | Uwagi |
|---|---|---|
| VICTRIX ZEUS 25, EXA 28 1 ErP, OMNIA, OMNIA V2 (G / P / t / A) | 41 / 44, zdjęta zworka X40 | Bez regulatora X40 z powrotem na 40-41. EXA 28: regulator OpenTherm innej firmy działa bez przeróbek (użytkownicy). |
| VICTRIX TERA V2 / V3 (P / t / A / S) | 41 / 44, zdjęta X40 | **P7** = protokół zdalnego sterowania: 0 IMG BUS (CAR V2), **2 = pilot innej firmy** (nastawa CWU i maks. zasilanie zostają wtedy na panelu kotła), 1 = niedostępne. Użytkownicy podawali P7 = 1 – polska instrukcja mówi 2. Immergas potwierdza OpenTherm w TERA V2. |
| VICTRIX EXA 24 X 1 ErP, NIKE 24 ECO (S / P / t) | 41 / 44, zdjęta X40 (NIKE: złącze X15) | Użytkownik ma tu Nest Heat Link (OT1 na 44, OT2 na 41). |
| VICTRIX ZEUS Superior 26 / 32, HERCULES Condensing 26 / 32 / ABT 32, HERCULES Solar 26 (M1 / M3 / M5) | **42 / 43**, zdjęta X40 | **M3 P33 = ON** pozwala grzać CO bez pilota (E31). ABT 32: termostaty pokojowe na karcie stref X9. *ERR>CM* na CAR V2 = brak komunikacji. |
| Nowa platforma: ZEUS Superior 25 / 30 / 35, HERCULES 25 / 35 / 35 ABT / Mini 35 / Solar 25, VICTRIX EXTRA | IMG BUS 44-41, **MODBUS D+ / D−** | Dominus łączy się po **Modbusie** (menu *Modbus / Typ* = Dominus, EXTRA: P.18 = 1). Regulator OpenTherm innej firmy może iść na IMG BUS (*Zdalne sterowanie* = urządzenie z handlu, EXTRA: P.17 = 1), ale nie razem z Dominusem: E145 konflikt mastera. E142 = Dominus niedostępny. |

W każdym starszym kotle **E31** (utrata pilota) przełącza kocioł na pracę lokalną i blokuje ogrzewanie do odłączenia
zasilania. Sonda zewnętrzna jest na 38-39, termostat on/off na 40-41. Zacisk **21** („sygnał stanu”) w EXA służy do grup
pompowych DIM załączanych przez CAR, a nie do OpenTherm. Dane, których kocioł nie ma (ciśnienie, przepływ CWU, temp.
zewnętrzna bez sondy, chłodzenie), czytają się jako 0 albo brak obsługi – tablica ukrywa te kafelki.

**Każdy master OpenTherm zapisuje cyklicznie.** Master OpenTherm (moduł Dominusa, CAR V2, master ESP) wysyła status /
zezwolenia (Data-ID 0) i nastawę CO (1) co cykl, a nastawę CWU (56) raz po raz z własnej pamięci, nie jednorazowo.
Dlatego wartość CWU zapisana przez drugiego mastera się nie utrzymuje. Regulacja pokojowa szybkim PID-em daje na tych
kotłach przeregulowanie (pełna moc, potem w pokoju za ciepło przez kilka godzin). Programy Home Assistant zmieniają tu
zasilanie powoli (krzywa, samouczenie ±1 °C na dobę).

## Specyfika Immergas

- **Steruje pilot.** Z podłączonym **CAR V2** (na zaciskach Dominusa) albo **Super Amico** (na kotle) ogrzewaniem
  kieruje pilot. Wartość raz zapisana z Home Assistant (np. nastawa CWU) jest **zapamiętywana przez Dominusa** i wysyłana
  do kotła ponad nastawą pilota, aż do odłączenia zasilania modułu (#2). Włącz **Tylko odczyt (steruje pilot)** (1.6.8):
  Home Assistant odrzuca wtedy każdy zapis, a odczyty zostają. Programy HA (program CO / CWU, antylegionella, urlop,
  automatyczne Lato / Zima) są wstrzymane i nie da się ich włączyć (1.6.9).
- **Kocioł nie ma trybu nocnego ani antylegionelli.** Instrukcja VICTRIX ZEUS nie zawiera żadnego z nich: obniżenie
  nocne daje pilot (program CAR V2, chronotermostat), a zakres CWU kończy się na 60 °C. Bez pilota integracja robi oba
  w Home Assistant (faza Eko programu CO, CWU Komfort / Eko, antylegionella ograniczona do maksimum CWU kotła z Data-ID 48).
- **E31** „utrata komunikacji z pilotem” – kocioł oczekuje pilota, z którym był sparowany; dopóki E31 jest aktywny,
  ignoruje polecenia CO / CWU / trybu zarówno z apki, jak i z Home Assistant.
- **Młodszy bajt 0xCA w Data-ID 0** – „poprawka Immergas” innych bramek OpenTherm (OTGateway, użytkownicy ESPHome): bez
  niej zapisy do Data-ID 1 / 57 są potwierdzane, ale nic nie zmieniają. Opcja **Bajt LB ramki statusu** (eksperymentalna,
  domyślnie standard 0x00).
- **Nastawa CO** jest zapisywana jako parametr modułu 17 (Data-ID 89), tak jak robi to oficjalna apka; Data-ID 1 to
  zadana sterująca, którą moduł przelicza sam.
- **Zapisane wartości różnią się nieco** od wysłanych (VICTRIX zapisuje 45,0 °C jako 44,7): *Ostatni zapis* uznaje
  nastawę w granicy 0,5 °C za przyjętą i niezgodność czyta ponownie po kilku sekundach (1.6.6).
- **Parametry kotła (TSP, Data-ID 10 / 11)** to wartości z menu kotła; Immergas nie publikuje ich znaczenia. Firmware
  OTGW przed każdą zmianą maks. modulacji zapisuje w Immergasie TSP 12, więc 12 to najpewniej maks. moc CO (P2).
  Zgłoszenie z wartościami menu P / t / A / F Twojego kotła obok skanu pomaga je dopasować.
- **Historia błędów** (Data-ID 12 / 13) = „pięć ostatnich anomalii” kotła (menu d0.8), kody jak w instrukcji kotła (np.
  E89 niestabilny sygnał spalania).

## Zastąpienie CAR V2

Cel: kocioł prowadzony przez Dominusa i Home Assistant, CAR V2 zdjęty. Co jest potrzebne:

1. **Mostek X40 z powrotem na zaciskach 40-41 kotła** (albo termostat pokojowy). CAR V2 podłącza się do zacisków
   41 / 44 po zdjęciu X40; bez CAR V2 i bez X40 kocioł po E31 przechodzi w tryb lokalny i nie grzeje (instrukcja kotła).
2. **Skasować E31**: odłączyć i włączyć zasilanie kotła, żeby przestał czekać na pilota.
3. **Sonda Dominusa na zaciskach 1-2 jako sonda pokojowa** (*Sonda Dominusa mierzy* = pokój, *Czujnik pokojowy*
   włączony) – dla zadanej pokoju, programów Komfort / Eko i ochrony przed zamarzaniem. Sonda zewnętrzna idzie do kotła.
4. ***Tylko odczyt (steruje pilot)* wyłączone** i działający Home Assistant (moduł trzyma ostatnią nastawę, gdy HA nie
   działa, ale faz nie zmienia).

Karta **Kocioł OpenTherm** pokazuje to jako listę kontrolną (*Praca bez CAR V2*).

| CAR V2 | Dominus + Home Assistant |
|---|---|
| Stand-by / Lato / Zima | Tryb (Data-ID 0) |
| Ręczny (pokój 10–35 °C), wymuszony automatyczny | Program CO MANUAL, Zadana temperatura pokoju; ręczna zmiana trzyma do następnej fazy |
| Automatyczny PR RIS (4 zakresy Komfort na dobę) | Program CO AUTO: 4 kalendarze × 4 zakresy, jeden na dzień tygodnia |
| Komfort / Ekonomiczny (20 / 16 °C) | Temperatury pokoju Komfort / Eko |
| Pokrętło CWU, PR SAN (Komfort / minimum) | Zadana CWU; CWU Komfort / Eko wg kalendarza CWU, Eko do minimum kotła (Data-ID 48) |
| S.RIS maks. zasilanie, krzywa OTC 0–9 | Zadana CO (parametr 17), Krzywa grzewcza |
| ANTIGL ochrona pomieszczenia 0–10 °C | Ochrona przed zamarzaniem i jej temperatura |
| Menu informacji | sensory (zewnętrzna, zasilanie, powrót, CWU, ciśnienie, gdy kocioł je podaje) |
| ERR>xx, reset (maks. 5 na godzinę) | Kod i opis błędu, Reset kotła (5 prób na godzinę) |
| REGOLAZ: MINRIS, OFFSET, DIMENS | Minimalna temperatura CO, Offset temperatury CO, Bezwładność budynku |
| AUTO A samouczenie | Samouczenie (offset CO ±1 °C na dobę wg błędu Komfortu z poprzedniego dnia) |
| VACANZ (CO i CWU wył.) | Tryb wyjazdowy do daty, *Działanie urlopu* Stand-by (domyślnie) albo Lato |
| LEGION (maksimum przez 20 min, 02:00 codziennie / w poniedziałek) | Antylegionella: to samo, ograniczona do maksimum CWU kotła |
| AMB, MODUL | Czujnik pokojowy, Modulacja |
| RIDOTT OFF / ON (−1 … −40 °C) | Faza Eko: wyłącz ogrzewanie / obniż zadaną zasilania o *Obniżenie zasilania w Eko* |
| MANUTZ (6–24 mies.) | Przypomnienie o przeglądzie, Ostatni przegląd, Przegląd wykonany, Przegląd wymagany |
| AMB CR (korekta sondy ±3 °C) | – (brak parametru modułu) |
| REMOTO, LANGUAGE, chłodzenie, wilgotność | – (robi to sam Home Assistant; nie w tych kotłach) |

## Termostat pokojowy

Kocioł nie zgłasza termostatu pokojowego przez OpenTherm, więc **Termostat pokojowy** mówi, co jest podłączone:
**Brak**, **Fizyczny** (termostat on/off na zaciskach kotła 40-41 – jego żądania nie widać, tylko żądanie CO) albo
**Emulowany** – Home Assistant wysyła do modułu temperaturę encji HA wybranej w **Źródło temperatury pokoju** (np.
czujnika pokojowego) jako Data-ID 24 (WRITE-DATA „temperatura pokoju”, tak jak wysyła ją regulator pokojowy), przy
zmianie o 0,1 °C albo co 5 minut; *Tylko odczyt* to blokuje. **Eksperymentalne:** czy regulator Dominusa użyje jej
zamiast własnej sondy, trzeba potwierdzić na prawdziwym kotle. Wybór i encja są w karcie **Parametry pieca (offline)**; kafel **Termostat** w karcie Łączność pokazuje stan. Data-ID 24
jest oceniany po odczycie zwrotnym minutę później (*działa* / *moduł nie przyjmuje*) – samo potwierdzenie niczego nie
dowodzi (test Modbus dał echo zapisanej wartości).

**Zabezpieczenie (1.6.12):** gdy encja źródłowa przez **60 minut** nie poda świeżej, poprawnej wartości (niedostępna,
nie liczba, brak aktualizacji), Data-ID 24 przestaje być wysyłany – stara temperatura trzymałaby regulator na złej
wartości. Kafel robi się czerwony (*Brak źródła temperatury*); wysyłanie wraca samo, gdy encja się odezwie. Własna
ochrona przeciwzamrożeniowa kotła działa dalej.

## Menu kotła (deklarowane, offline)

Własnego menu kotła (instrukcja VICTRIX ZEUS 25) nie da się jeszcze odczytać przez OpenTherm: kocioł podaje 42
parametry (Data-ID 10 / 11), ale Immergas nie publikuje, który numer jest który. Jak w trybie Modbus, integracja trzyma
je jako **wartości deklarowane**, przepisane raz z menu kotła, domyślnie puste (wartość *sugerowana* to ustawienie
fabryczne). Nic nie trafia do kotła; karta **Parametry pieca (offline)** używa ich do podpowiedzi.

| Menu | Encja (ustawienie fabryczne) | Podpowiedź na dashboardzie |
|---|---|---|
| t0 / t1 | min. / maks. temperatura zasilania CO (25 / 85 °C) | obok zakresu CO podawanego przez kocioł (Data-ID 49) |
| t5 | blokada ponownego zapłonu CO, 0–600 s (180 s) | przy ponad 6 startach palnika na godzinę: wydłuż t5 (300–600 s) |
| t6 / t7 | rampa mocy CO (180 s) / opóźnienie zapłonu (0 s) | – |
| t4 | czekanie po CWU przed CO (20 s) | – |
| t2 | termostat CWU: zasilanie przy grzaniu zasobnika (1) | – |
| P0 / P1 / P2 | maks. moc CWU / min. moc / maks. moc CO (99 / 0 / 80 %) | P1 obok min. modulacji (Data-ID 15); P2 obok parametru kotła 12 ze skanu |
| P6 | pompa przerywana / ciągła | – |
| A3 / A4 / A5 | maks. / min. prędkość pompy, tryb pompy (9 / 6 / 15) | – |
| P7 | korekta sondy zewnętrznej (0 K) | – |

**Profile menu.** Kotły Immergas nie mają jednego menu: ta sama funkcja ma inny kod, zakres albo jednostkę. Instrukcje
instalatora dają pięć rodzin menu OpenTherm; **Profil menu kotła** (albo zgadywanie z pola *Model kotła*) wybiera kody,
które pokazuje karta. Wartości to te same encje w każdym profilu.

| Funkcja | ZEUS 25 / EXA 28 / OMNIA | TERA V2 / V3 | EXA 24 X / NIKE | ZEUS Superior 26 / 32 | HERCULES Condensing / Solar 26 |
|---|---|---|---|---|---|
| Min. / maks. zasilanie CO | t0 / t1 | t0 / t1 | S5 / S6 (EXA) | P66/A / P66/B | P66/A / P66/B |
| Krzywa (temp. zewn. przy maks. / min. zasilaniu) | – | – | – | P66/C / P66/D | P66/C / P66/D |
| Blokada ponownego zapłonu | t5, 0–600 s | t4 | t0 | P69, 0–255 s | P69, 0–255 s |
| Rampa / opóźnienie zapłonu | t6 / t7 | t5 / t6 | t1 / t2 | P70 / P68 | P70 / P68 |
| Czekanie po CWU | t4 | t3 | – | – | – |
| Maks. / min. moc CO | P2 / P1 (%) | P2 / P1 (%) | S3 / S2 rpm (EXA), S1 / S0 % (NIKE) | P64 / P65 rpm | P64 / P65 rpm |
| Maks. / min. moc CWU | P0 (%) | P0 (%) | S1 / S0 rpm (EXA) | P57 / P62 rpm | P62 / P63 rpm |
| Termostat CWU | t2 | – | – | P71 (−3 / −10 °C) | P71 (−3 / −5 °C solar) |
| Praca pompy | P6 | P4 | P2 | P67 | P67 |
| Prędkość pompy / ΔT | A3 / A4, A5 | A1 / A2, A3 | – | P55 | P57 AUTO (ΔT) / FIX |
| Korekta sondy zewnętrznej | P7 | P5 | S7 (EXA) | P76 | P76 (−15…+14) |
| Pilot | – | P7 (0 CAR V2 / 2 inna firma) | – | – | M3 P33 CO bez pilota |
| Liczniki | – | – | – | M1 | M1 P12 godziny, P13 zapłony |

Kody Superior P68–P76 są odczytane z jego instrukcji i czekają na potwierdzenie na prawdziwym kotle; instrukcja
HERCULES sugeruje, że P55 jest tam odczytem, a pompą sterują P57 / P67. VICTRIX ZEUS 26 2 ErP prawie nie ma
numerowanego menu – dla niego profil ogólny. **Nowa platforma** (ZEUS Superior 25 / 30 / 35, HERCULES 25 / 35, VICTRIX
EXTRA) to dla Dominusa kocioł Modbus – patrz [Modbus po TCP](pdu-map.pl.md).

Funkcje automatyczne kotła (ochrona pompy i zaworu 3-drogowego co 24 h, ochrona grzejników poniżej 4 °C, autotest
płytki co 18 h, odpowietrzanie A7, kominiarz) nie wymagają ustawień i nie są zgłaszane przez OpenTherm. Skany razem
z wartościami z menu (**Zgłoś mapę Data-ID**) pozwolą integracji czytać je bezpośrednio.

## Diagnostyka

**Skanuj Data-ID** (przycisk, ok. minuty, odpytywanie pauzuje) → **Obsługiwane Data-ID** pokazuje, co odpowiedziało,
co jest nieobsługiwane, surowe wartości oraz parametry kotła i historię błędów. **Ostatni zapis** odczytuje każdy zapis
z powrotem (*Przyjęty* / *Potwierdzony, nieprzyjęty*). **Zgłoś mapę Data-ID** tworzy powiadomienie z linkiem do gotowego
zgłoszenia na GitHubie (model kotła, wersja integracji, skan – bez hosta, MAC i hasła); nic nie jest wysyłane
automatycznie.

## Źródła

- Instrukcja instalatora VICTRIX ZEUS 25 (kody błędów, menu informacyjne, parametry P / t / A / F).
- Instrukcje instalatora z immergas.pl (11.2026): VICTRIX EXA 24 X / 28, NIKE 24 ECO, TERA V2 / V3, OMNIA / OMNIA V2,
  HERCULES Condensing / ABT / Solar 26 oraz nowa platforma ZEUS Superior 25-35, HERCULES 25 / 35 / Mini / Solar 25, EXTRA.
- [Zgodność OTGateway](https://github.com/Laxilef/OTGateway/wiki/Compatibility) – poprawka Immergas, brak przepływu CWU
  w Victrix.
- [Wątek arduino.ru o termostacie OpenTherm](https://arduino.ru/forum/programmirovanie/termostat-opentherm-na-esp8266?page=15#comment-649392)
  – młodszy bajt 0xCA i sekwencja zapisów Immergas.
- [Elektroda: Immergas z innym sterownikiem niż CAR](https://www.elektroda.pl/rtvforum/topic3843909.html) – zaciski
  41 / 44 (EXA), TERA P7, TERA V2 z OpenTherm, Nest Heat Link.
- [esp_domoticz_opentherm_handler](https://github.com/akamming/esp_domoticz_opentherm_handler) – master OpenTherm na
  ESP: cykliczne zapisy Data-ID 0 / 1 / 56, zabezpieczenie temperatury pokoju.
- [Firmware OTGW](https://github.com/rvdbreemen/OTGW-firmware) – `TP=11:12` dla Immergas.
