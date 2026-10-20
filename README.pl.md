# Immergas Dominus

<p align="center">
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS Custom"></a>
  <img src="https://img.shields.io/github/v/tag/jotuera/immergas-dominus?label=version&color=blue" alt="Wersja">
  <img src="https://img.shields.io/badge/HA-2024.1%2B-41BDF5.svg" alt="Home Assistant 2024.1+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="Licencja: MIT"></a>
</p>

[🇬🇧 English](README.md) · **🇵🇱 Polski**

Autor: **JoTu** ([github.com/jotuera](https://github.com/jotuera))

Integracja niestandardowa Home Assistant do **lokalnego** sterowania kotłem Immergas przez
moduł Wi-Fi **Dominus** — bez chmury, bez MQTT. Home Assistant łączy się bezpośrednio z
modułem Dominus po lokalnym TCP (domyślny port `2000`), używając adresu MAC i hasła modułu.

> **Przetestowane na Immergas Magis Combo i Magis Pro** (konfiguracja Magis PRO COMBO V2,
> MPROCOMBOV2). Inne modele Immergas z tym samym modułem Dominus mogą działać, ale nie są
> zweryfikowane.

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
  (angielski tekst z rozszyfrowanej tablicy apki Dominus, 114 kodów), `Błąd kotła`
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

- Opisy błędów pochodzą z rozszyfrowanej tablicy etykiet apki Dominus
  (`LBL-WFC01_IM_MBUS_MPROCOMBOV2.json`, pola angielskie) — tego samego źródła, co
  narzędzia do magistral D+/D- i T-/T+.
- Rejestry potwierdzone tylko na magistrali D+/D- (harmonogram, flagi błędów) są
  sprawdzone krzyżowo, ale na innych modelach mogą wymagać weryfikacji przez TCP AUTH.

## Historia zmian

### 0.3.3

Nowe encje tylko do odczytu, rozszyfrowane z rejestrów już odpytywanych po TCP (dekodowanie
bitów potwierdzone na żywo na magistrali D+/D-):

- **Żądanie grzania Strefy 1** — binary sensor (status strefy `2010`, bit 3).
- **Faza programu Strefy 1** — sensor (`2010`, bity 2/6/7): `ręczny` / `komfort` / `eko`
  wewnętrznego harmonogramu kotła.
- **Status Strefy 2 / Strefy 3** — sensory diagnostyczne (`2020` / `2030`).

### 0.3.2

- **Żądanie CWU** — binary sensor (flagi statusu `2001`, bit 0): aktywny, gdy cykl CWU
  jest w toku przygotowań (ustawiany ~9 min przed przełączeniem zaworu 3-drogowego na CWU).

### 0.3.1

- Nowe odkrycia z mapy rejestrów magistrali D+/D-, potwierdzone jako czytelne po TCP:
  - **Status strefy** (`2010`) i **Liczba stref** (`4199`) — diagnostyka.
  - Przypisanie dni → profil rozszerzone o **CWU** (`2490`–`2496`) i **Strefy 2/3**
    (`2420`–`2436`), obok Strefy 1, na urządzeniu harmonogramu.
  - Korekta: temperatura pokojowa `32767` (0x7FFF) = „brak czujnika" → zgłaszana jako
    nieznana zamiast fałszywego `3276,7 °C`.
- Tłumaczenie czeskie (`cs.json`), autorstwa **harykx** (#1).

### 0.3.0

- Pierwsze publiczne wydanie na GitHub. Domyślnie angielski (nazwy urządzeń, encje oraz
  **angielskie opisy błędów** z apki Dominus), polski jako tłumaczenie.
- Układ pod HACS (`custom_components/`, `hacs.json`), licencja MIT, dane autora.

### 0.2.x

- 0.2.10 — skrót harmonogramu „ten sam profil dla wszystkich dni".
- 0.2.9 — harmonogram ogrzewania CO (32 encje `time` + 7 selectów dni).
- 0.2.8 — raportowanie błędów kotła (kod, opis, aktywny, reset dostępny).
- 0.2.7 — offset krzywej grzewczej (U03) dla Stref 2/3.
- 0.2.6 — Strefy 2/3 wyłączone na poziomie urządzenia; nastawy jako suwaki.
- 0.2.5 — encje Stref 2/3; dynamiczny polling.
- 0.2.4 — encje CWU przeniesione na urządzenie główne.
- 0.2.3 — `0xFF` zewn. = brak sondy; potwierdzone mapowanie trybu pracy.
- 0.1.9 — pamięć ostatniej dobrej wartości, optymistyczne aktualizacje po zapisie.

## Zasoby graficzne

Dołączone zasoby brandowe Home Assistant znajdują się w
`custom_components/immergas_dominus/brand/`. Ikona to oryginalna grafika projektu
(czerwone tło, biały termostat i symbole bezprzewodowe) i nie kopiuje grafik Immergas/Dominus.

## Licencja

[MIT](LICENSE) © JoTu. Niezwiązane z Immergas ani nierekomendowane przez Immergas.
