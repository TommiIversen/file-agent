# Audio Recording Domain — Implementeringsplan

Nyt `audio_recording` domæne der optager WAV-filer, slavet til Justins optagestatus via EventBus.
Platform-abstraktion (ASIO/Windows, CoreAudio/macOS) med fælles base class.
Settings UI for device, sample rate, spornavne, on/off.
Growing copy udvides til `.wav`.

**5 store faser.**

---

## Fase 1: Platform-abstrakt Recorder Engine

Byg recorder-motoren med base class og platform-backends.
POC'en i `scripts/audio-poc/` er valideret på Windows og bruges som udgangspunkt.

### 1.1 — Base class + backends

- Opret `app/domains/audio_recording/recorder/`
- Abstract base `AudioRecorder` med interface:
  - `start(tracks, samplerate, output_dir)` → `list[Path]`
  - `stop()` → status dict
  - `is_recording` property
  - `list_devices()` → liste af device info
- **Windows**: `AsioRecorder` baseret på POC'ens `AsioThread` + `sounddevice` ASIO backend + `soundfile` WAV writer.
  COM STA-krav bevares via dedikeret tråd.
- **macOS**: `CoreAudioRecorder` — samme `sounddevice`/`soundfile` libs, men med CoreAudio som host API.
  `sounddevice` håndterer det automatisk. Ingen `AsioThread` nødvendig.
- `factory.py`: `sys.platform` check → returnerer korrekt implementation.

### 1.2 — Track-model & navngivning

- Track-model understøtter **mono** og **stereo**:
  ```python
  AudioTrack(
      channels: list[int],   # [3] for mono, [1, 2] for stereo
      label: str,            # "Mic1", "PGM_LR", "DALET_LR"
      mode: "mono" | "stereo"
  )
  ```
- **Mono**: 1 input-kanal → 1-kanal WAV fil
- **Stereo**: 2 input-kanaler → 2-kanal WAV fil (interleaved L/R)
- Filnavne-format: `{justin_filename_prefix}_{label}.wav`
  - Mono eksempel: `260410_1056_10_Mic1.wav` (1ch WAV)
  - Stereo eksempel: `260410_1056_10_PGM_LR.wav` (2ch WAV)
- **Filnavn-præfiks hentes fra Justin API** via `POST /ingest/requestCurrentFilename`:
  - Request: `{"channel": "KAM_1"}`
  - Response: `{"value": "260410_1056_10", "channel": "KAM_1", ...}`
  - `value`-feltet indeholder det aktuelle filnavn-præfiks (dato+tid) som Justin bruger.
  - Audio domain spørger via QueryBus: `await query_bus.execute(GetCurrentFilenameQuery(channel="KAM_1"))` → `"260410_1056_10"`
  - Dermed matcher audio-filnavnene Justins MXF-filnavne 1:1.
- **Fallback**: Hvis API-kaldet fejler, bruges lokalt systemtidspunkt i samme format.
- **Recovery-postfix** ved device-genstart: `_rec2`, `_rec3`
  - Eksempel: `260410_1056_10_Mic1_rec2.wav`

#### Referenceopsætning (Studie 1)

| Kilde | Input-kanal(er) | Label | Format |
|-------|----------------|-------|--------|
| Mix L / Mix R | 1 & 2 | PGM_LR | **Stereo** |
| Mic proc. 1 | 3 | Mic1 | Mono |
| Mic proc. 2 | 4 | Mic2 | Mono |
| Mic proc. 3 | 5 | Mic3 | Mono |
| Mic proc. 4 | 6 | Mic4 | Mono |
| USB (mono) | 7 | USB_mono | Mono |
| Prod-mic proc. | 8 | Mic_prod | Mono |
| Dalet L / Dalet R | 9 & 10 | DALET_LR | **Stereo** |
| Mic 1 | 11 | Mic1_clean | Mono |
| Mic 2 | 12 | Mic2_clean | Mono |
| Mic 3 | 13 | Mic3_clean | Mono |
| Mic 4 | 14 | Mic4_clean | Mono |

Resultat: 12 WAV-filer per optagelse (10 mono + 2 stereo), bruger 14 fysiske input-kanaler.

### 1.3 — Robusthed

- **Device-disconnect**: Detect via `is_broken` Event + callback status → stop cleanly → vent kort → genstart med recovery-postfix.
- **Disk-fejl / lav plads**: Stop cleanly, publicer `SystemEvent`, **ingen** genstart (ikke meningsfuldt).
- **Writer overflow**: Log + tæl, publicer event ved grænseværdi.

---

## Fase 2: Domæne-integration (EventBus + CQRS)

Wire `audio_recording` ind i arkitekturen som et selvstændigt domæne.

### 2.1 — Events

Nye events i `app/core/events/audio_events.py`:

- `AudioRecordingStartedEvent(tracks, session_id)`
- `AudioRecordingStoppedEvent(session_id, files)`
- `AudioRecordingErrorEvent(error, recoverable)`
- `AudioDeviceDisconnectedEvent(device_name)`

### 2.2 — Commands & Queries

- **Commands**: `StartAudioRecordingCommand`, `StopAudioRecordingCommand`
- **Queries**: `GetAudioDevicesQuery`, `GetAudioRecordingStatusQuery`, `GetAudioTrackConfigQuery`

### 2.2b — Ny Query i ingest_monitor domænet

- `GetCurrentFilenameQuery(channel: str)` → `str` (fx `"260410_1056_10"`)
- Handler i `ingest_monitor/query_handlers.py` kalder `IngestApiClient.get_current_filename()`
- Ny metode på `IngestApiClient`:
  ```python
  async def get_current_filename(self, channel_name: str) -> Optional[str]:
      response = await self._client.post(
          "/ingest/requestCurrentFilename",
          json={"channel": channel_name}
      )
      data = response.json()
      return data.get("value")  # fx "260410_1056_10"
  ```
- Audio domain bruger QueryBus til at hente filnavnet (ingen direkte import fra ingest_monitor)

### 2.3 — Slavet til Justin via events

- `event_handlers.py` lytter på `ChannelRecordingStartedEvent` / `ChannelRecordingStoppedEvent`
- **Start-flow**:
  1. `ChannelRecordingStartedEvent` fyrer (første kanal begynder at optage)
  2. Audio domain tjekker `audio_recording_enabled` setting → no-op hvis `false`
  3. Audio domain kalder `await query_bus.execute(GetCurrentFilenameQuery(channel=event.channel_name))`
  4. Modtager filnavn-præfiks fra Justin API (fx `"260410_1056_10"`)
  5. Kombinerer præfiks + track labels → starter optagelse: `260410_1056_10_PGM_LR.wav` (stereo), `260410_1056_10_Mic1.wav` (mono), ...
- **Stop-flow**: Når **alle** kanaler stopper → stop audio.
- Alternativt: Brug `IngestStatusUpdatedEvent` snapshot og reager på `recording_count > 0 → 0` transition.

### 2.4 — Wiring

- `app/domains/audio_recording/registration.py` — registrer alle handlers + event subscriptions.
- `app/dependencies/audio_recording.py` — DI factory.
- Wire i `app/main.py` `_register_domains()` — **efter** ingest_monitor.
- Tilføj lint-imports contracts i `pyproject.toml`:
  - Independence med `file_discovery`, `file_processing`, `tally_light`, `presentation`.

---

## Fase 3: User Settings & UI

### 3.1 — Nye settings

Tilføjes til `USER_SETTINGS_SCHEMA` + Alembic migration:

| Setting | Type | Default | Beskrivelse |
|---------|------|---------|-------------|
| `audio_recording_enabled` | bool | `false` | Master on/off |
| `audio_device_name` | str | `""` | Valgt device |
| `audio_sample_rate` | int | `48000` | 44100 / 48000 / 96000 |
| `audio_tracks` | JSON str | `"[]"` | `[{"channels":[1,2],"label":"PGM_LR","mode":"stereo"}, {"channels":[3],"label":"Mic1","mode":"mono"}, ...]` |

### 3.2 — UI sektion i Settings Modal

- Ny sektion **"Audio Recording"** med:
  - Toggle: Enable/disable.
  - Device-dropdown (populeret via API). På macOS vises CoreAudio devices i stedet for ASIO — `sounddevice` håndterer dette transparent.
  - Sample rate dropdown: 44.1k / 48k / 96k.
- **Dynamisk track-liste**:
  - Hver linje = mono/stereo toggle + input-kanal(er) dropdown + user label tekstfelt + slet-knap.
  - Mono: Én kanal-dropdown. Stereo: To kanal-dropdowns (L + R).
  - "Tilføj spor" knap.
  - Validering: Ingen duplicate input-kanaler på tværs af tracks, labels ikke tomme, unikke labels.

### 3.3 — API endpoints

- `GET /api/audio/devices` — tilgængelige audio devices (via `GetAudioDevicesQuery`).
- `GET /api/audio/status` — aktuel optagestatus.
- Settings CRUD via eksisterende `/api/system/user-settings`.

### 3.4 — Hot-reload

- Ændring af audio settings → reinitialiser recorder (ny device, ny sample rate) uden restart.

---

## Fase 4: Growing Copy → WAV support

### 4.1 — Extension-filter

- `file_scanner.py`: `is_mxf_file()` → `is_accepted_file()` der også accepterer `.wav`.
- Growing file detection og copy strategy er **allerede extension-agnostiske** — ingen ændring nødvendig.

### 4.2 — WAV header-overvejelse

- WAV-filer har total størrelse i headeren. Under growing copy er headeren "forkert" indtil filen lukkes.
- Undersøg om downstream NLE-software kan håndtere dette, eller om en post-copy header-fix er nødvendig.

---

## Fase 5: Presentation & Status i UI

### 5.1 — WebSocket real-time

- `PresentationEventHandlers` subscriber på `AudioRecording*Event`.
- Broadcast recording status, device info, overflow warnings til alle connected clients.

### 5.2 — UI component

- Status-indikator i header: "Audio: Recording 14 tracks @ 48kHz" / "Audio: Off" / "Audio: Device Disconnected".
- Fejl-indikator ved device disconnect eller overflow.

### 5.3 — System Event logging

- Audio start/stop/error/disconnect logges til `SqliteEventStore` → synlig i event-log UI.

---

## Beslutninger

- **`sounddevice` + `soundfile`** bruges på begge platforme (POC valideret, CoreAudio virker automatisk på macOS).
- Audio optager **alle konfigurerede tracks som én session** — ikke per-Justin-kanal.
- Navngivning: Justin date+time prefix + user-defineret label per spor.
- Recovery ved device-disconnect: postfix `_rec2`, `_rec3` → undgår overskrivning.
- WAV-filer skrives til `source_directory` (samme mappe som MXF) → growing copy håndterer videre-kopiering.
- Mapping går **ikke** i stykker ved device-disconnect — konfigurationen er gemt i DB, uafhængig af device-tilstedeværelse.

## Scope exclusions

- VU-meters / level monitoring (kan komme senere).
- Per-kanal audio recording slavet til individuelle Justin-kanaler (alle tracks starter/stopper sammen).
- Audio format-valg (kun WAV PCM_24 for nu).

## Åbne spørgsmål

1. ~~**Justin dato+tid sync**~~ → **AFKLARET**: Vi bruger `POST /ingest/requestCurrentFilename` til at hente det præcise filnavn-præfiks fra Justin. Fallback til lokalt systemtidspunkt ved API-fejl.

2. **Kanal start-logik**: Reagerer vi på *første* kanal-start, eller skal vi have en konfigurerbar trigger (f.eks. "start audio når KAM_1 starter")? *Anbefaling: Første kanal — matcher broadcast-workflow.*

3. **macOS device enumeration**: På macOS viser `sounddevice` alle CoreAudio devices (built-in mic, aggregated devices, etc.). Skal vi filtrere, eller vise alle? *Anbefaling: Vis alle — brugeren vælger selv.*



