# File Growth Simulator

Dette tool simulerer en video optager der kontinuerligt skriver til 8 video streams, og "clipper" dem efter en time med _1, _2 osv. bag på filnavnet.

## Funktionalitet

- **Multiple streams**: Simulerer flere samtidige video streams (default 8)
- **Kontinuerlig skrivning**: Skriver konstant data til filerne for at simulere live optagelse
- **Automatic clipping**: Starter automatisk nye filer efter en bestemt tid (default 60 min)
- **Realistic file names**: Bruger format `stream_XX_YYY.mxf` hvor XX er stream nummer og YYY er clip nummer
- **Realistic behavior**: Skriver direkte til .mxf filer som en rigtig videoptager (ingen .tmp filer)
- **Configurable**: Alle parametre kan justeres via command line argumenter

## Hurtig start

### Standard konfiguration (realistisk hastighed):
```cmd
run_simulator.bat
```

### Hurtig test (til udvikling):
```cmd
run_simulator_fast.bat
```

## Manuel brug

```cmd
python file_growth_simulator.py --help
```

### Eksempler:

**Realistisk simulation (langsom):**
```cmd
python file_growth_simulator.py ^
    --output-folder "C:\temp\sdi_recordings" ^
    --stream-count 8 ^
    --write-interval-ms 500 ^
    --chunk-size-kb 64 ^
    --clip-duration-minutes 60 ^
    --new-file-interval-minutes 1
```

**Hurtig test (til udvikling):**
```cmd
python file_growth_simulator.py ^
    --output-folder "C:\temp\sdi_recordings" ^
    --stream-count 3 ^
    --write-interval-ms 100 ^
    --chunk-size-kb 256 ^
    --clip-duration-minutes 2 ^
    --new-file-interval-minutes 0.17
```

## Parametre

| Parameter | Default | Beskrivelse |
|-----------|---------|-------------|
| `--output-folder` | `C:\temp\sdi_recordings` | Mappe hvor filerne skal gemmes |
| `--stream-count` | `8` | Antal samtidige video streams |
| `--write-interval-ms` | `500` | Millisekunder mellem hver skrivning |
| `--chunk-size-kb` | `64` | KB data per skrivning |
| `--clip-duration-minutes` | `60` | Minutter før ny fil startes |
| `--new-file-interval-minutes` | `1` | Interval mellem opstart af streams |

## Filnavns mønster

Filer følger dette mønster:
- **Under optagelse**: `stream_01_001.mxf` (skriver direkte til .mxf fil)
- **Næste clip**: `stream_01_002.mxf`

*Note: Simulerer rigtig videoptager adfærd - skriver direkte til .mxf filer, ingen .tmp filer.*

## Hastigheds estimering

Med default indstillinger:
- **Per stream**: 64KB hver 500ms = ~128 KB/s = ~460 MB/time
- **8 streams**: ~3.7 GB/time total
- **Realistic size**: En times video vil være ~460 MB per stream

## Stop simulatoren

Tryk `Ctrl+C` for at stoppe alle streams pænt. Alle aktive filer vil blive afsluttet og omdøbt korrekt.

## Log output

Simulatoren logger:
- Når nye streams startes
- Når nye filer påbegyndes
- Fremgang hver 10 MB
- Når filer afsluttes og omdøbes

Eksempel output:
```
14:30:15 - INFO - Starter 8 streams i C:\temp\sdi_recordings
14:30:15 - INFO - Stream 1: Startet ny fil stream_01_001.mxf
14:30:30 - INFO - Stream 1: 10.0 MB skrevet til stream_01_001.mxf
14:31:15 - INFO - Stream 2: Startet ny fil stream_02_001.mxf
```