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

Print dit `False` terwijl de map bestaat, dan zit je in de sandbox. Twee oplossingen:

1. **Roep Python via het volledige pad aan** (draait dan zonder sandbox), bijv.:
   ```powershell
   & "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe" scripts\check_device.py
   ```
2. **Of** wijs adb expliciet aan, dan maakt de Python-variant niet uit:
   ```powershell
   $env:PHONEBOT_ADB_PATH = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
   ```

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
