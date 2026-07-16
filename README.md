# PhoneBot

Een minimale, **vision-based** Python-basis om een Android-emulator te besturen via ADB:
screenshots ophalen, taps/swipes sturen en simpele template matching met OpenCV.

> Dit is een los experiment naast GnomeBot/Microbot — geen vervanging.
> Deze route werkt **puur op pixels**: geen RuneLite telemetry, geen PacketUtils,
> geen Microbot Agent Server, geen widgets of game-object APIs. De bot ziet
> alleen screenshots en stuurt input via ADB.

## Projectstructuur

```
phonebot/
  README.md
  requirements.txt
  phonebot/            # core package (geen game-specifieke logica)
    __init__.py
    adb.py             # list_devices / require_device / run_adb
    screenshot.py      # capture_png / save_screenshot / screenshot_to_cv2
    input.py           # tap / swipe
    vision.py          # find_template -> Match(x, y, width, height, confidence)
    config.py          # threshold + PHONEBOT_ADB_SERIAL
  scripts/
    check_device.py    # devices tonen
    capture_screen.py  # screenshot -> outputs/screenshot.png
    tap_template.py    # zoek template en tap op het midden
  templates/           # jouw referentie-plaatjes
  outputs/             # opgeslagen screenshots
```

## 1. Emulator starten

Kies één van beide:

- **Android Studio**: open *Device Manager* → maak een virtueel toestel aan → start het.
- **Andere emulator** (BlueStacks, LDPlayer, Genymotion, Waydroid, ...): start het toestel
  en zorg dat ADB-debugging aan staat.

Houd de resolutie stabiel: template matching is gevoelig voor schaal en UI-state.

## 2. ADB installeren / controleren

ADB zit in de Android **platform-tools**.

- Via Android Studio: SDK Manager → *Android SDK Platform-Tools*.
- Los downloaden: Google "SDK Platform Tools", uitpakken, map aan je **PATH** toevoegen.

Check dat `adb` gevonden wordt:

```powershell
adb version
```

## 3. `adb devices` checken

```powershell
adb devices
```

Verwacht iets als:

```
List of devices attached
emulator-5554   device
```

Staat er `offline` of `unauthorized`? Herstart de emulator / autoriseer de verbinding.

Meerdere toestellen? Pin er één met een environment variable:

```powershell
$env:PHONEBOT_ADB_SERIAL = "emulator-5554"
```

## 4. Dependencies installeren

```powershell
cd phonebot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

(De core-package gebruikt alleen `opencv-python` en `numpy`; ADB wordt via
`subprocess` aangeroepen.)

### ⚠️ Windows-valkuil: welke Python?

De nieuwe **MSIX-gebaseerde python.org install** (en de Microsoft Store-Python)
draait in een **sandbox die `%LOCALAPPDATA%` virtualiseert**. Omdat de Android SDK
standaard in `%LOCALAPPDATA%\Android\Sdk` staat, ziet zo'n Python de `adb.exe`
niet — je krijgt dan "ADB not found" terwijl `adb devices` in PowerShell prima werkt.

Herken je dit? Test:

```powershell
python -c "import os; print('Android' in os.listdir(os.environ['LOCALAPPDATA']))"
```

Print dit `False` terwijl de map bestaat, dan zit je in de sandbox. De **betrouwbaarste
fix** werkt in elke shell: kopieer platform-tools naar een map **buiten** `AppData\Local`
(die map is namelijk gevirtualiseerd) en wijs `PHONEBOT_ADB_PATH` daarheen — permanent:

```powershell
# eenmalig: platform-tools naar buiten AppData\Local kopieren
Copy-Item "$env:LOCALAPPDATA\Android\Sdk\platform-tools" "$env:USERPROFILE\Documents\phonebot-adb" -Recurse
# permanent instellen (geldt vanaf een NIEUWE terminal)
setx PHONEBOT_ADB_PATH "$env:USERPROFILE\Documents\phonebot-adb\adb.exe"
```

> Belangrijk: `PHONEBOT_ADB_PATH` naar de adb in `AppData\Local\Android` laten wijzen helpt
> NIET in de sandbox — die locatie is juist onzichtbaar. Kopieer 'm er dus buiten.

Alternatief zonder kopie: installeer een **schone, niet-MSIX Python** (klassieke
python.org-installer of via winget naar Program Files). Dan is er geen sandbox en werkt de
adb-autodetectie vanzelf.

### ADB vinden

Je hoeft `adb` niet per se op je PATH te zetten: de bot zoekt automatisch naar
`adb` op PATH en in de gebruikelijke SDK-locaties. Lukt dat niet, zet dan
`PHONEBOT_ADB_PATH` (zie hierboven) of voeg platform-tools toe aan je PATH.

## 5. Screenshot test draaien

Eerst devices controleren:

```powershell
python scripts/check_device.py
```

Dan een screenshot maken:

```powershell
python scripts/capture_screen.py
```

Dit schrijft `outputs/screenshot.png`. Open dat bestand om te controleren of het klopt.

## 6. Template tap test draaien

1. Knip uit een screenshot een klein, herkenbaar stukje UI (bv. een knop) en sla het op
   in `templates/`, bijvoorbeeld `templates/example.png`.
2. Draai:

```powershell
python scripts/tap_template.py templates/example.png
```

Optioneel een eigen drempel (0.0 - 1.0) meegeven:

```powershell
python scripts/tap_template.py templates/example.png 0.9
```

Exit codes van `tap_template.py`:

| Code | Betekenis                                  |
|------|--------------------------------------------|
| 0    | template gevonden en getapt                |
| 1    | fout (geen device, bestand mist, ...)      |
| 2    | template niet gevonden boven de drempel    |

## 7. Beperkingen

Dit is **vision-based**. Dat betekent:

- **Resolutie en schaal moeten stabiel zijn.** Een template gemaakt op één resolutie
  matcht niet betrouwbaar op een andere.
- **UI-state moet voorspelbaar zijn.** Pop-ups, animaties of thema's kunnen matches breken.
- `find_template` doet geen schaal- of rotatie-invariante matching; het zoekt het beste
  exacte match-punt met genormaliseerde kruiscorrelatie (`TM_CCOEFF_NORMED`).
- Coördinaten zijn pixels op het toestel; taps landen op het **midden** van de match.

## Eerste bot: een simpele loop (woodcutting-stijl)

`scripts/woodcutting.py` is het minimale "eerste bot"-patroon: **zoek template → tap →
wacht → herhaal**. Hetzelfde script werkt voor fishing/mining/etc. — verwissel alleen de
template. Het heeft ingebouwde randomisatie (variabele wachttijd + kleine tap-jitter) en
nette stop-condities.

```powershell
# knip eerst een boom/vis/rots uit een game-screenshot -> templates/tree.png
python scripts/woodcutting.py templates/tree.png
python scripts/woodcutting.py templates/tree.png --threshold 0.8 --min-wait 4 --max-wait 7
python scripts/woodcutting.py templates/tree.png --max-actions 50
```

Stoppen met **Ctrl+C**. Stopt ook automatisch na te veel misses (`--max-misses`, default 5).

Exit codes: `0` = normaal gestopt/klaar, `1` = fout, `2` = te vaak niets gevonden.

> Let op: dit automatiseert een live game-account, wat tegen de voorwaarden van veel games
> ingaat en tot een ban kan leiden. Gebruik het voor experimenteren op een wegwerp-account.

### Slimmere variant: power-chop (`scripts/powerchop.py`)

Chopt tot je inventory vol is en **dropt** dan de logs (tap-to-drop), daarna weer door.
Twee templates: de boom en één log-icoon uit je inventory. Vereist dat **'tap to drop'
AAN staat** in de game-settings (dan is een log droppen simpelweg een tik erop).

```powershell
python scripts/powerchop.py --tree templates/tree.png --log templates/log.png
python scripts/powerchop.py --tree templates/tree.png --log templates/log.png --full 27
```

Per cyclus: is de inventory vol (>= `--full` logs, default 27)? dan alle logs weg-tikken
en opnieuw scannen tot leeg; anders de boom zoeken, tikken en wachten. Stoppen met Ctrl+C.

Twee handige core-helpers die hierbij horen:
- `vision.find_all_templates(screen, template, threshold, max_results)` → lijst van matches
  (bv. tellen hoeveel logs er in de inventory zitten).
- `input.long_press(x, y, duration_ms)` → ingedrukt houden voor het context-menu (nodig als
  'tap to drop' uit staat en je via het long-press-menu wilt droppen).

## Reactieve watcher (`scripts/watch.py`)

Kijkt continu of een template op het scherm verschijnt en tikt er dan op. Dit is waar
vision **betrouwbaar** in is: statische UI. Denk aan auto-continue van dialogen, een
level-up-venster wegklikken, of een knop indrukken zodra die verschijnt.

```powershell
# blijf 'Click here to continue' wegklikken zodra het verschijnt
python scripts/watch.py --watch templates/continue.png

# meerdere dingen tegelijk bewaken
python scripts/watch.py --watch continue.png --watch levelup.png --cooldown 3

# wacht tot iets verschijnt, tik 1x, stop
python scripts/watch.py --watch dialog.png --once
```

Opties: `--threshold` (match-drempel), `--interval` (scan-tempo), `--cooldown`
(min. tijd voor dezelfde template opnieuw triggert, tegen spam-tikken),
`--once` (stop na de eerste tik), `--max-triggers` (stop na N tikken). Ctrl+C stopt.

> Vision is sterk voor statische UI (knoppen, iconen, dialogen), maar onbetrouwbaar voor
> bewegende wereld-objecten (bomen die wuiven/despawnen, met de camera meeschuiven). Voor
> dat laatste lezen client-based bots zoals GnomeBot/Microbot de game intern uit.

## Visuele script-builder (`scripts/build_script.py`)

Bouw een stappen-script door op een emulator-screenshot te klikken (GnomeBot-stijl):

```powershell
python scripts/build_script.py
```

- **Klik** op het beeld → `tap` op dat punt.
- **Sleep** een rechthoek → knipt een template en maakt (afhankelijk van de radio-keuze)
  een `tap_template` of `wait_template` stap.
- Knoppen: wacht toevoegen, volgorde wijzigen, verwijderen, screenshot verversen,
  loop aan/uit, opslaan als `.json`, en direct draaien.

Het script draai je (opnieuw) met de runner:

```powershell
python scripts/run_script.py mijnscript.json --max-loops 20
```

### Stap-types & condities

| Type | Doet |
|------|------|
| `tap` | tik op een vast punt (x, y) |
| `wait` | wacht random tussen `min` en `max` seconden |
| `swipe` | veeg van (x1,y1) naar (x2,y2) |
| `tap_template` | zoek een beeld en tik erop (niet gevonden = overslaan) |
| `wait_template` | **wacht tot** een beeld verschijnt (tot `timeout`), tik er dan op — dit is "if gevonden tik, anders wacht tot het er is" |
| `if_template` | **gevonden → `then`-stappen, anders → `else`-stappen** (mag genest) |

Voorbeeld van een conditie in JSON (if gevonden tik-continue, anders wacht):

```json
{
  "loop": true,
  "steps": [
    {"type": "if_template", "template": "templates/continue.png",
      "then": [{"type": "tap_template", "template": "templates/continue.png"}],
      "else": [{"type": "wait", "min": 1, "max": 2}]}
  ]
}
```

## Run-logboek (`--log`)

`run_script.py`, `watch.py` en `powerchop.py` accepteren `--log`: dan schrijven ze een
**getimed logboek + roterende screenshots** naar `outputs/debug/<naam>_<tijd>/`. Handig om
achteraf te zien wat een script deed en waar het vastliep (bv. een disconnect/ban-scherm).

```powershell
python scripts/run_script.py mijnscript.json --log
python scripts/powerchop.py --tree templates/tree.png --log --keep-frames 30
```

- `log.txt` bewaart de **volledige** actie-geschiedenis met tijdstippen (zo zie je een
  vastloop-lus of waar het stopte).
- `frame_*.png` zijn de **laatste N** screenshots op beslismomenten (`--keep-frames`,
  default 20). Oudste worden gewist, dus de map loopt nooit vol.
- Oude run-mappen worden automatisch opgeruimd (laatste 10 blijven).

> Zonder `--log` worden er **geen** screenshots opgeslagen — de bot leest ze in het geheugen
> en gooit ze meteen weg. De `templates/`-map groeit alleen als je in de builder nieuwe
> regio's sleept (elk kader = één template-bestand).

## Snelle API

```python
from phonebot import adb, screenshot, input as bot_input, vision

serial = adb.require_device()                 # kiest/valideert een toestel
png = screenshot.capture_png(serial)          # bytes
img = screenshot.screenshot_to_cv2(png)       # numpy BGR array
match = vision.find_template(img, template)   # Match | None
if match:
    bot_input.tap(*match.center, serial=serial)
```
