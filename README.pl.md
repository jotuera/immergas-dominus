# Immergas Dominus

<p align="center">
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS Custom"></a>
  <img src="https://img.shields.io/github/v/tag/jotuera/immergas-dominus?label=version&color=blue" alt="Wersja">
  <img src="https://img.shields.io/badge/HA-2024.1%2B-41BDF5.svg" alt="Home Assistant 2024.1+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-PolyForm%20Noncommercial-blue.svg" alt="Licencja: PolyForm Noncommercial 1.0.0"></a>
</p>

[🇬🇧 English](README.md) · **🇵🇱 Polski**

Autor: **JoTu** ([github.com/jotuera](https://github.com/jotuera))

Integracja niestandardowa Home Assistant do **lokalnego** sterowania kotłem Immergas przez
moduł Wi-Fi **Dominus** — bez chmury, bez MQTT. Home Assistant łączy się bezpośrednio z
modułem Dominus po lokalnym TCP (domyślny port `2000`), używając adresu MAC i hasła modułu.

> **Przetestowane na Immergas Magis Combo, Magis Pro i Trio Hydro Hybrid 8** (konfiguracja
> Dominus `MPROCOMBOV2`). Pełna lista w sekcji [Obsługiwane modele](#obsługiwane-modele).

> **Kompatybilność — dwa protokoły.** Magis Combo / Pro (configi `*_MBUS_*`) używają
> 7-bajtowego protokołu **Modbus** — w pełni wspierane. Kotły, których config Dominus nie
> ma flagi `modbus` — np. **VICTRIX ZEUS / AVIO**, STAR — używają 6-bajtowego protokołu
> **OpenTherm**; od 0.4.0 jest **eksperymentalny tryb OpenTherm** (wybierany w config flow).
> **Odczyt potwierdzony na VICTRIX ZEUS 25 ErP**; od 0.4.1 także **eksperymentalny zapis**
> (nastawa CO / CWU, tryb) wymagający potwierdzenia. Zob. zgłoszenie
> [#2](https://github.com/jotuera/immergas-dominus/issues/2).

Interfejs jest **domyślnie po angielsku**, z pełnym tłumaczeniem **polskim** (oraz czeskim).
Wersja i autor integracji są też pokazane na stronie każdego urządzenia Dominus w Home
Assistant (pole *Oprogramowanie*, np. `0.3.3 — JoTu`).

## Funkcje

- Połączenie lokalne po TCP, kreator konfiguracji (host/IP, port, MAC i hasło Dominus).
- Bez chmury, bez MQTT, bez sniffera, bez surowych/diagnostycznych encji PDU.
- Pamięć ostatniej dobrej wartości i dynamiczny polling — odpytywane są tylko rejestry
  **włączonych** encji.

### Urządzenie główne

- Sensory: temperatura zewnętrzna (`3002`, `0xFF` = brak sondy), temperatura zasobnika CWU (`3016`).
- Wybór trybu pracy (`2000`): Standby / Lato / Chłodzenie / Zima.
- Nastawa CWU (`2095`) i termostat CWU.
- **Raportowanie błędów kotła** (jak apka Dominus): kod błędu (`2100`), opis błędu
  (własne teksty projektu, 113 kodów, w języku Home Assistanta), `Błąd kotła`
  (binary, *problem*) oraz `Reset dostępny` (binary, `2101` bit 1).
- `Żądanie CWU` (binary, `2001` bit 0) — zapala się ~9 min przed cyklem CWU.

### Strefa 1 (oraz wyłączone domyślnie Strefa 2 / Strefa 3)

- Temperatura pokojowa, zadana ogrzewania, offset krzywej grzewczej (U03), komfort/eco
  grzanie i chłodzenie, nastawy wilgotności i przepływu (suwaki) oraz termostat.
- `Żądanie grzania` (binary, `2010` bit 3) i `Faza programu` (ręczny/komfort/eko).
- Rejestry per strefa mają offset `+10` na strefę (Strefa 1 `2011/2015/2210…`,
  Strefa 2 `2021/2025/2220…`, Strefa 3 `2031/2035/2230…`). Urządzenia Strefa 2/3 są
  wyłączone domyślnie; włącz urządzenie, aby uaktywnić wszystkie jego encje.

### Harmonogram ogrzewania (wyłączony domyślnie)

- 4 współdzielone profile dzienne (Cal 1–4) × 4 przedziały komfortu, każdy jako para
  początek/koniec typu `time` (`2310`–`2347`, starszy bajt = godzina, młodszy = minuta;
  `24:00` pokazywane jako `23:59`).
- Przypisanie profilu do dnia tygodnia dla Strefy 1/2/3 oraz CWU (`2410`–`2496`), plus
  skrót **Ustaw ten sam profil dla wszystkich dni**.

## Dashboard

Integracja ma własne karty dashboardu (te same co w
[IMMERGAS Modbus BMS NASA Hub](https://github.com/jotuera/immergas-modbus-bms-nasa-hub), w okrojonym widoku). Nic więcej
nie trzeba instalować: utwórz nowy dashboard (*Ustawienia → Dashboardy → Dodaj dashboard*), otwórz go, *⋮ → Edytuj
dashboard → ⋮ → Edytor konfiguracji* i wpisz

```yaml
strategy:
  type: custom:immergas-dominus
```

- **Teraz** – czego kocioł potrzebuje (ogrzewanie / ciepła woda), tryb, faza programu, nastawy CO i CWU, temperatura
  zewnętrzna, Strefy 1 i zasobnika CWU, aktywny błąd.
- **Nastawy** – Strefa 1 i CWU z −/+ oraz profilami Komfort / Eko.
- **Tryb pracy** – Standby / Lato / Zima / Chłodzenie (dotknij 2×), faza programu Strefy 1, offset krzywej (U03),
  CWU Komfort / Eko wg harmonogramu.
- **Harmonogram** – cztery kalendarze i dni tygodnia dla CO i CWU (najpierw włącz urządzenie *Heating schedule*).
- **Łączność** – moduł Dominus (ostatni udany odczyt, nieudane odpytania) i kocioł za nim.

Danych pompy ciepła (sprężarka, COP, zasilanie / powrót pompy, energia) nie da się odczytać przez Dominusa – do tego
służy hub.

## Obsługiwane modele

Wszystkie kotły, których moduł Dominus używa konfiguracji **`WFC01_IM_MBUS_MPROCOMBOV2`**,
mają tę samą mapę rejestrów i działają tak samo.

**Przetestowane — potwierdzone, że działają:**

- Magis Combo / Magis Pro-Combo V2
- Magis Pro
- Trio Hydro Hybrid 8 — zgłoszone przez @FrancescoC87 ([#3](https://github.com/jotuera/immergas-dominus/issues/3))

**Ta sama konfiguracja — powinny działać** (nietestowane pojedynczo; wg `CFGS` apki Dominus):

- Magis Hercules Pro
- Magis Hercules Pro Mini
- Magis Hercules Mini Hydro
- Trio Pack
- Trio Hydro

(Warianty `MPROCOMBOV2_8N2` = Magis Hercules i `MPROCOMBOV2_SYS` = gestore di sistema mają
tę samą mapę z drobną różnicą transmisji/adresowania.)

**Nie pokryte — inna konfiguracja Dominus / mapa rejestrów:**

- **VICTRIX ZEUS / AVIO**, STAR — protokół **OpenTherm** (zob. eksperymentalny tryb
  OpenTherm wyżej, [#2](https://github.com/jotuera/immergas-dominus/issues/2)).
- **TRIO** (`MBUS`), **SUPERIOR** (`SCP01`), **MAIOR / EXTRA** (`HDBC65`) — inne
  konfiguracje Modbus z własnymi mapami rejestrów.

Jeśli Twój kocioł używa configu `MPROCOMBOV2`, a nie ma go na liście, prawie na pewno
zadziała — otwórz zgłoszenie, żeby potwierdzić.

## Instalacja

### HACS (niestandardowe repozytorium)

1. HACS → *Integracje* → ⋮ → *Niestandardowe repozytoria*.
2. Dodaj `https://github.com/jotuera/immergas-dominus`, kategoria *Integration*.
3. Zainstaluj **Immergas Dominus**, zrestartuj Home Assistant.
4. *Ustawienia → Urządzenia i usługi → Dodaj integrację → Immergas Dominus*.

### Ręcznie

Skopiuj `custom_components/immergas_dominus` do katalogu `config/custom_components/` w
Home Assistant, zrestartuj HA, a następnie dodaj integrację jak wyżej.

Pierwsza sesja lokalna TCP może zostać odrzucona przez moduł Dominus (np. tuż po użyciu
aplikacji mobilnej); integracja i tak utworzy encje, a wartości pojawią się, gdy moduł
przyjmie sesję.

## Uwagi

- Opisy błędów to własne teksty projektu (11 języków), wspólne z IMMERGAS Modbus BMS NASA Hub;
  kody błędów i ich znaczenie odpowiadają dokumentacji kotła.
- Rejestry potwierdzone tylko na magistrali D+/D- (harmonogram, flagi błędów) są
  sprawdzone krzyżowo, ale na innych modelach mogą wymagać weryfikacji przez TCP AUTH.

## Historia zmian

### 1.1.0

- **Dashboard**: integracja udostępnia karty Immergas Hub i ładuje je w Home Assistancie; nowy dashboard ze
  `strategy: {type: custom:immergas-dominus}` pokazuje karty Teraz, Nastawy, Tryb pracy, Harmonogram i Łączność.

### 1.0.0

- **Nowa licencja**: PolyForm Noncommercial 1.0.0 (bezpłatnie do użytku osobistego i innego niekomercyjnego).
- **Własne opisy błędów kotła** (`2100`), 113 kodów w 11 językach, napisane dla tego projektu, wspólne
  z [IMMERGAS Modbus BMS NASA Hub](https://github.com/jotuera/immergas-modbus-bms-nasa-hub). Kod 0 pokazuje
  „Brak błędów”.
- **Zapis już nie odskakuje**: po potwierdzonym zapisie moduł potrafi jeszcze przez odczyt lub dwa podawać starą
  wartość; przez 30 s taki odczyt nie cofa zapisanej wartości.
- **Presety Komfort / Eko** w termostatach stref: preset pokazuje fazę programu strefy (`2010`), wybór ustawia
  zadaną strefy na jej nastawę Komfort / Eko (`2210`/`2211`, chłodzenie `2214`/`2215`).
- **Diagnostyka połączenia**: `Ostatni udany odczyt` i `Nieudane odpytania` (atrybut `missing_in_last_poll`).
- Wcześniejsze wersje rozwojowe (0.2–0.6) zbudowały wszystko z rozdziału *Funkcje*: tryb pracy, strefy 1–3,
  harmonogramy CO i CWU, CWU Komfort / Eko, raportowanie błędów, eksperymentalny tryb OpenTherm, 11 języków.

## Zasoby graficzne

Dołączone zasoby brandowe Home Assistant znajdują się w
`custom_components/immergas_dominus/brand/`. Ikona to oryginalna grafika projektu
(czerwone tło, biały termostat i symbole bezprzewodowe) i nie kopiuje grafik Immergas/Dominus.

## Licencja

[PolyForm Noncommercial 1.0.0](LICENSE) © JoTu: bezpłatnie do użytku osobistego i innego niekomercyjnego – w domu,
dla własnego kotła, do nauki i badań. **Użycie komercyjne** (instalatorzy, sprzedawcy, wbudowanie w płatny produkt)
wymaga osobnej licencji – skontaktuj się przez GitHub. Zobacz też [CONTRIBUTING](CONTRIBUTING.md).
Niezwiązane z Immergas ani nierekomendowane przez Immergas.
