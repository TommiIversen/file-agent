# Audio Recording Domain — Implementeringsplan

Nyt `audio_recording` domæne der optager WAV-filer, slavet til Justins optagestatus via EventBus.
Platform-abstraktion (ASIO/Windows, CoreAudio/macOS) med fælles base class.
Settings UI for device, sample rate, spornavne, on/off.
Growing copy udvides til `.wav`.

**5 store faser.**

### Status-overblik

| Fase | Navn | Status |
|------|------|--------|
| 1 | Platform-abstrakt Recorder Engine | ✅ Done |
| 2 | Domæne-integration (EventBus + CQRS) | ✅ Done |
| 3 | User Settings & UI | ✅ Done |
| 4 | Growing Copy → WAV support | ⬜ Ikke startet |
| 5 | Presentation & Status i UI | ⬜ Ikke startet |
| 6 | VU / Peak Metering i UI | ⬜ Ikke startet |

---

## Fase 1: Platform-abstrakt Recorder Engine ✅

Byg recorder-motoren med base class og platform-backends.
POC'en i `scripts/audio-poc/` er valideret på Windows og bruges som udgangspunkt.

> **Implementeret** i `app/domains/audio_recording/recorder/`:
> `base.py`, `callback.py`, `models.py`, `asio_recorder.py`, `coreaudio_recorder.py`, `factory.py`

### 1.1 — Base class + backends ✅

- Opret `app/domains/audio_recording/recorder/`
- Abstract base `AudioRecorder` med interface:
  - `start(tracks, samplerate, output_dir, filename_prefix)` → `list[Path]`
  - `stop()` → status dict
  - `is_recording` property
  - `duration_seconds` property
  - `overflow_count` property
  - `list_devices()` → liste af device info
  - `set_callback(cb: RecorderCallback)` → wire domain adapter
- **Windows**: `AsioRecorder` baseret på POC'ens `AsioThread` + `sounddevice` ASIO backend + `soundfile` WAV writer.
  COM STA-krav bevares via dedikeret tråd.
- **macOS**: `CoreAudioRecorder` — samme `sounddevice`/`soundfile` libs, men med CoreAudio som host API.
  `sounddevice` håndterer det automatisk. Ingen `AsioThread` nødvendig.
- `factory.py`: `sys.platform` check → returnerer korrekt implementation.

#### 1.1b — RecorderCallback protokol (tilføjet under review)

Sync callback-interface som recorder-tråde kalder. Domain-laget implementerer det
og bridger til async EventBus via `loop.call_soon_threadsafe()`.

```python
class RecorderCallback(Protocol):
    def on_started(self, files: list[Path], actual_samplerate: float) -> None: ...
    def on_stopped(self, files: list[Path], duration_seconds: float, overflow_count: int) -> None: ...
    def on_error(self, error_message: str, recoverable: bool) -> None: ...
    def on_overflow_warning(self, dropped_count: int, total_drops: int) -> None: ...
    def on_device_lost(self) -> None: ...
```

Implementeret i `callback.py` (protokol) + `callback_adapter.py` (EventBus bridge).

### 1.2 — Track-model & navngivning ✅

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

### 1.3 — Robusthed ✅

- **WAV header auto-update**: Aktivér `SFC_SET_UPDATE_HEADER_AUTO` (libsndfile kommando `0x1061`) på hver WAV writer ved optagelsesstart.
  Det sikrer at source-filens header altid er korrekt under optagelse.
  ```python
  sf._snd.sf_command(writer._file, 0x1061, sf._ffi.NULL, 1)  # SFC_SET_UPDATE_HEADER_AUTO
  ```
  Med `try/except` fallback hvis private API ændres (version-robusthed).
- **Device-disconnect — Callback Watchdog** (tilføjet under review):
  Base class tracker `_last_callback_time`. En daemon-tråd checker hvert 250ms:
  hvis `now - _last_callback_time > 500ms` → device antages tabt → `on_device_lost()` callback.
  Ved 48kHz/128 frames kommer callbacks hver ~2.7ms, så 500ms er ekstremt konservativt.
  Implementeret i `base.py` (`_start_watchdog` / `_stop_watchdog` / `_touch_watchdog`).
- **Disk-fejl / lav plads** (udvidet under review):
  - **Pre-flight check**: Mindst 1 GB ledig plads kræves ved start. `OSError` kastes ellers.
  - **Runtime**: Writer-tråd fanger `OSError` → sætter `_recording = False` → kalder `on_error(recoverable=False)`.
  - **Ingen** genstart ved diskfejl (ikke meningsfuldt).
- **Atomic start / rollback** (tilføjet under review):
  Hvis ASIO-stream fejler efter WAV-filer er oprettet → writers lukkes → tomme filer slettes.
  Ingen "orphaned" WAV-filer på disk ved fejl.
- **Concurrent start/stop race** (tilføjet under review):
  `asyncio.Lock` i `AudioRecordingService` og `AudioRecordingEventHandler` forhindrer
  parallelle start/stop-kald fra at race.
- **Applikations-shutdown** (tilføjet under review):
  `AudioRecordingService.shutdown()` er wired i `main.py` `_shutdown()` — stopper
  optagelse cleanly ved app-nedlukning.
- **Writer overflow** — to-trins strategi for at bevare audio/video-sync:
  - **Callback → writer kommunikation**: ASIO-callback lægger tuples i køen: `(data_block, dropped_count)`.
    Når køen er fuld, tæller callbacket droppede blokke i en intern counter. Når køen får plads igen,
    sendes næste blok med `dropped_count` sat til antallet af droppede blokke, og counteren nulstilles.
    ```python
    # I ASIO callback:
    try:
        self._audio_q.put_nowait((indata.copy(), self._dropped_since_last))
        self._dropped_since_last = 0
    except queue.Full:
        self._dropped_since_last += 1
        self._overflow_count += 1
    ```
  - **Writer-tråden**: Tjekker `dropped_count` på hver blok. Hvis > 0 → skriver zero-fill
    (`np.zeros(frames * dropped_count, ...)`) før den faktiske data. Bevarer tidslinje-sync.
  - **< 100 akkumulerede drops**: Zero-fill og fortsæt. Ved 48kHz/128 frames er
    én blok ~2.7ms — uhørligt. Log + tæl, publicer warning event.
  - **≥ 100 akkumulerede drops** (vedvarende I/O-problem): ⬜ **Ikke implementeret endnu** — planlagt
    til Fase 4 (Growing Copy). Recovery-postfix mekanikken (`get_recovery_prefix`) eksisterer i
    servicen, men resten (auto-restart ved overflow) bygges når growing-copy er på plads.
    Indtil da: zero-fill + log fortsætter for alle overflow-niveauer.
  - Bufferen er ~11 sekunder (4096 blokke). Overflow kræver ekstremt I/O-pres for at ske.

---

## Fase 2: Domæne-integration (EventBus + CQRS) 🔶

Wire `audio_recording` ind i arkitekturen som et selvstændigt domæne.

### 2.1 — Events ✅

Nye events i `app/core/events/audio_events.py`:

- `AudioRecordingStartedEvent(session_id, tracks, samplerate, files)`
- `AudioRecordingStoppedEvent(session_id, files, duration_seconds, overflow_count)`
- `AudioRecordingErrorEvent(error, recoverable, session_id)`
- `AudioDeviceDisconnectedEvent(device_name)`
- `AudioOverflowWarningEvent(dropped_count, total_drops, session_id)` — tilføjet under review

### 2.2 — Commands & Queries ✅

- **Commands**: `StartAudioRecordingCommand(filename_prefix, session_id)`, `StopAudioRecordingCommand`
- **Queries**: `GetAudioDevicesQuery`, `GetAudioRecordingStatusQuery`, `GetAudioTrackConfigQuery`
- Handlers i `command_handlers.py` og `query_handlers.py`.
- `AudioRecordingService` orkestrerer recorder-livscyklus med `asyncio.Lock`.

### 2.2b — Ny Query i ingest_monitor domænet ⬜ TODO

- `GetCurrentFilenameQuery(channel: str)` er defineret i `app/core/cqrs/shared_queries.py` ✅
- **Mangler**: Handler i `ingest_monitor/query_handlers.py` der kalder `IngestApiClient.get_current_filename()`
- **Mangler**: Ny metode `get_current_filename()` på `IngestApiClient`
- **Mangler**: Registrering i `ingest_monitor/registration.py`
- Fallback i `event_handlers.py` bruger lokalt tidspunkt hvis query fejler ✅
- Spec:
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

### 2.3 — Slavet til Justin via events ✅

- `event_handlers.py` lytter på `ChannelRecordingStartedEvent` / `ChannelRecordingStoppedEvent`
- **Kontekst**: Podcast-studie — alle kanaler starter/stopper nogenlunde samtidig som én session.
  Kanaler opereres **ikke** asynkront. Ved fejl kan en enkelt kanal undlade at optage — det er OK.
- **Start-flow**:
  1. `ChannelRecordingStartedEvent` fyrer (første kanal begynder at optage)
  2. Hvis audio allerede optager → **ignorer** (ingen split, ingen ny fil)
  3. Audio domain tjekker `audio_recording_enabled` setting → no-op hvis `false`
  4. Audio domain kalder `await query_bus.execute(GetCurrentFilenameQuery(channel=event.channel_name))`
  5. Modtager filnavn-præfiks fra Justin API (fx `"260410_1056_10"`)
  6. Kombinerer præfiks + track labels → starter optagelse: `260410_1056_10_PGM_LR.wav` (stereo), `260410_1056_10_Mic1.wav` (mono), ...
- **Stop-flow**: Når **alle** kanaler stopper → stop audio. Nye WAV-filer oprettes ved næste start.
- Alternativt: Brug `IngestStatusUpdatedEvent` snapshot og reager på `recording_count > 0 → 0` transition.
- **Justin-nedbrud → optag videre**:
  Hvis Justin crasher eller forbindelsen ryger, mangler `ChannelRecordingStoppedEvent` —
  men vi stopper **ikke** lydoptagelsen. Lyden er værdifuld, også uden Justin.
  - `IngestOfflineEvent` → optagelsen fortsætter uforstyrret (ingen handler nødvendig —
    fraværet af stop-event er tilstrækkeligt).
  - **Auto-stop er sikkerhedsnettet**: Den eksisterende max-varighed (default 180 min)
    forhindrer uendelig optagelse. Audio lytter på `AutoStopTriggeredEvent` →
    kalder `stop()` cleanly med det samme.
  - **Kill-switch** (`audio_recording_enabled` → `false`) forbliver operatørens manuelle nødbremse.
  - Resultat: Justin ned i 45 min → vi har 45 min ekstra lyd. Auto-stop rammer 180 min → clean stop.
- **Bevidst fravalg**: Krydsende start/stop (kanal A starter ny optagelse mens kanal B kører)
  håndteres **ikke** — audio splitter ikke. Workflowet kræver det ikke for podcast-produktion.

### 2.4 — Wiring ✅

- `app/domains/audio_recording/registration.py` — registrer alle handlers + event subscriptions.
- `app/dependencies/audio_recording.py` — DI factory.
- Wired i `app/main.py` `_register_domains()` — **efter** ingest_monitor.
- Shutdown wired i `app/main.py` `_shutdown()`.
- lint-imports contracts tilføjet i `pyproject.toml`:
  - Independence med `file_discovery`, `file_processing`, `tally_light`, `presentation`.
- **Alle 9 contracts KEPT**, mypy clean, 1077 tests pass.

#### 2.5 — Thread→Async Bridge (tilføjet under review) ✅

`RecorderEventAdapter` i `callback_adapter.py` implementerer `RecorderCallback`-protokollen
og bruger `loop.call_soon_threadsafe(asyncio.ensure_future, event_bus.publish(event))`
til at bridge sync recorder-tråd-callbacks ind i den async EventBus.
Håndterer gracefully lukket event loop ved shutdown.

---

## Fase 3: User Settings & UI ✅

> **Implementeret**: Settings i schema + Alembic 006, API endpoints, Pydantic model,
> hot-reload med state-guard, kill-switch, recorder injection ved startup,
> UI sektion med device-dropdown, sample rate, dynamisk track-builder med validering.

### 3.1 — Nye settings ✅

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
- **State-guard under optagelse**: Hvis `is_recording == True`, afvises ændringer til
  `audio_device_name`, `audio_sample_rate` og `audio_tracks` med en fejlbesked i UI:
  *"Kan ikke ændres mens optagelse er aktiv"*.
  - Implementeres som validation i `UpdateUserSettingsCommandHandler` — tjekker recording-status
    via `GetAudioRecordingStatusQuery` før accept.
  - `audio_recording_enabled` → `false` er den **eneste** undtagelse: den fungerer som **kill-switch**
    og kalder `recorder.stop()` direkte (hård, ren stop). Dette er operatørens sikkerhedsnet
    ved en "fastlåst" optagelse hvor stop-events udebliver.
  - UI'et disabler device/sample rate/tracks felterne visuelt under optagelse.

---

## Fase 4: Growing Copy → WAV support ⬜

### 4.1 — Extension-filter

- `file_scanner.py`: `is_mxf_file()` → `is_accepted_file()` der også accepterer `.wav`.
- Growing file detection og copy strategy er **allerede extension-agnostiske** — ingen ændring nødvendig.

### 4.2 — WAV header-refresh under growing copy

**Problem**: Growing copy kopierer headeren (byte 0–44) én gang i starten og går aldrig tilbage.
Source-headeren opdateres løbende (`SFC_SET_UPDATE_HEADER_AUTO`), men NAS-kopiens header
forbliver forældet — NLE-software vil kun se den længde headeren angav da den blev kopieret.

```
Source (lokal disk):          NAS (destination):
─────────────────────         ─────────────────────
t=0   Header: size=0          Kopierer byte 0-44 → Header: size=0 ✗
t=30  Header: size=1.5GB      RE-COPY header →     Header: size=1.5GB ✓
t=60  Header: size=3.0GB      RE-COPY header →     Header: size=3.0GB ✓
t=end Header: final           Last header copy →   Header: final ✓
```

**Løsning: Periodisk header-refresh i growing copy**

- Kun for `.wav`-filer (MXF har ikke dette problem).
- Hvert N sekunder (f.eks. 30s) under growing copy:
  1. Seek til byte 0 på source og destination.
  2. Re-kopier de første 4096 bytes (4 KB — dækker WAV header + evt. bext/PEAK/PAD chunks).
  3. Seek tilbage til copy-positionen og fortsæt normal kopiering.
- Ved afslutning (static phase slut): Altid kopier headeren én allersidste gang.
- **Triviel operation**: 4 KB seek+write koster ingenting performancemæssigt.
- **Validation før write** (race condition guard): Før headeren skrives til NAS, valideres den:
  ```python
  def _is_valid_wav_header(header: bytes, source_file_size: int) -> bool:
      if header[:4] != b'RIFF':
          return False
      riff_size = int.from_bytes(header[4:8], 'little')
      if riff_size > source_file_size or riff_size < 44:
          return False
      data_pos = header.find(b'data')
      if data_pos < 0 or data_pos + 8 > len(header):
          return False
      data_size = int.from_bytes(header[data_pos+4:data_pos+8], 'little')
      expected_riff = data_size + data_pos + 8 - 4
      return abs(riff_size - expected_riff) < 1024
  ```
  Risikoen for korrupt header er ekstremt lav (4-byte aligned writes er atomiske på NTFS/APFS),
  men validation er billig forsikring. Fejler den → skip denne refresh, prøv igen om 30s.
  NAS-headeren forbliver "forældet men valid" — langt bedre end korrupt.
- Implementeres i `GrowingFileCopyStrategy` som en WAV-specifik hook i copy-loopet.
- **Windows file locking**: Testet og bekræftet — ingen problem. libsndfile bruger C `fopen()` som
  åbner med `FILE_SHARE_READ` på Windows. Growing copy kan læse WAV-filer med standard `open('rb')`
  mens recorder skriver til dem. Alle test bestået (header-read, chunk-read, concurrent read+write).

---

## Fase 5: Presentation & Status i UI ⬜

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

- ~~VU-meters / level monitoring (kan komme senere).~~ → Planlagt som **Fase 6**.
- Per-kanal audio recording slavet til individuelle Justin-kanaler (alle tracks starter/stopper sammen).
- Audio format-valg (kun WAV PCM_24 for nu).

---

## Fase 6: VU / Peak Metering i UI ⬜

Real-time peak-niveauer per track sendt til UI via WebSocket.
14 kanaler → 12 tracks → ~480 bytes JSON, 8 gange/sek = **~3.8 KB/sek**.
Al beregning sker i writer-tråden (ikke audio-callbacken) med numpy vectorized ops.

### Overordnet arkitektur

```
Writer-tråd (base.py)                    Async verden
─────────────────────                    ──────────────
① np.abs(block).max(axis=0)              ④ AudioLevelsEvent
② Akkumuler running-max over ~250ms      ⑤ PresentationEventHandlers
③ callback.on_levels(track_peaks)  ──→   ⑥ WebSocketManager.broadcast
   via call_soon_threadsafe                  ↓
                                          ⑦ Browser: audioStore → DOM
```

### 6.1 — Backend: Peak-beregning i writer-tråden

**Fil**: `app/domains/audio_recording/recorder/base.py`

Ændringer i `_writer_loop()` — efter eksisterende demux-kode:

```python
# Konstant: ~125ms ved 48kHz/128 frames = 47 blokke → 8 Hz updates
_LEVELS_INTERVAL_BLOCKS = 47
```

**Ny state i `__init__`**:
```python
self._peak_acc: Optional[np.ndarray] = None   # shape: (num_columns,)
self._levels_block_count = 0
```

**I `start()`** — efter `_build_channel_map()`:
```python
self._peak_acc = np.zeros(len(self._channel_selectors), dtype=np.float32)
self._levels_block_count = 0
```

**I `_writer_loop()`** — efter den eksisterende demux (`for tw, cols in zip(...)`):
```python
# ── Peak metering (hot path: ~2.5 µs per block) ──
col_peaks = np.abs(block).max(axis=0)            # (num_cols,) float
np.maximum(self._peak_acc, col_peaks, out=self._peak_acc)
self._levels_block_count += 1

if self._levels_block_count >= _LEVELS_INTERVAL_BLOCKS:
    track_peaks: list[dict[str, Any]] = []
    for tw, cols in zip(self._track_writers, self._track_cols):
        track_peaks.append({
            "label": tw.track.label,
            "peaks": [round(float(self._peak_acc[c]), 4) for c in cols],
        })
    if self._callback:
        self._callback.on_levels(track_peaks)
    self._peak_acc[:] = 0.0
    self._levels_block_count = 0
```

**Kostanalyse**:
- `np.abs(block).max(axis=0)` på `(128, 14)`: ~1-2 µs
- `np.maximum(acc, peaks)` på `(14,)`: ~0.5 µs
- **Totalt**: ~2.5 µs/block × 375 blocks/sek = **< 1 ms/sek**. Ubetydeligt.
- Callbacket `on_levels()` fyrer kun hvert 47. block (~8 Hz). Ingen målbar belastning.

### 6.2 — RecorderCallback protokol

**Fil**: `app/domains/audio_recording/recorder/callback.py`

Tilføj ny metode til `RecorderCallback` protokollen:

```python
def on_levels(self, track_peaks: list[dict]) -> None:
    """Peak levels per track.  Called ~4 Hz from writer thread.

    Each dict: {"label": str, "peaks": list[float]}
    Mono tracks have 1 peak, stereo tracks have 2 (L, R).
    Values are 0.0–1.0 (PCM full-scale).  Called ~8 Hz.
    """
    ...
```

### 6.3 — RecorderEventAdapter bridge

**Fil**: `app/domains/audio_recording/callback_adapter.py`

Ny metode der bruger eksisterende `_fire()` mekanisme:

```python
def on_levels(self, track_peaks: list[dict]) -> None:
    self._fire(
        AudioLevelsEvent(
            session_id=self._session_id or "",
            track_peaks=track_peaks,
        )
    )
```

**Bemærk**: `_fire()` bruger allerede `loop.call_soon_threadsafe()` — nul ekstra
synkroniseringskode. Ved 8 Hz er det 8 context-switches/sek, identisk mønster
som eksisterende overflow-warnings.

### 6.4 — Nyt domain event

**Fil**: `app/core/events/audio_events.py`

```python
@dataclass(frozen=True)
class AudioLevelsEvent:
    """Peak levels per track, emitted ~4 Hz during recording."""
    session_id: str
    track_peaks: list[dict]   # [{"label": "PGM_LR", "peaks": [0.82, 0.79]}, ...]
```

Tilføj til `__all__` og import i `callback_adapter.py`.

### 6.5 — Presentation event handler

**Fil**: `app/domains/presentation/event_handlers.py`

Ny subscription i `register()` + handler:

```python
async def handle_audio_levels_event(self, event: AudioLevelsEvent) -> None:
    await self._ws_manager.broadcast_message({
        "type": "audio_levels",
        "data": {
            "tracks": event.track_peaks,
            "session_id": event.session_id,
        }
    })
```

**Registrering**: `event_bus.subscribe(AudioLevelsEvent, handler.handle_audio_levels_event)`
i `registration.py`.

### 6.6 — WebSocket payload

```json
{
  "type": "audio_levels",
  "data": {
    "session_id": "abc-123",
    "tracks": [
      {"label": "PGM_LR", "peaks": [0.8234, 0.7891]},
      {"label": "Mic1",   "peaks": [0.4512]},
      {"label": "Mic2",   "peaks": [0.0023]},
      {"label": "Mic3",   "peaks": [0.3301]},
      {"label": "Mic4",   "peaks": [0.0]},
      {"label": "USB_mono", "peaks": [0.1204]},
      {"label": "Mic_prod", "peaks": [0.5512]},
      {"label": "DALET_LR", "peaks": [0.6723, 0.6801]},
      {"label": "Mic1_clean", "peaks": [0.4498]},
      {"label": "Mic2_clean", "peaks": [0.0019]},
      {"label": "Mic3_clean", "peaks": [0.3288]},
      {"label": "Mic4_clean", "peaks": [0.0]}
    ]
  }
}
```

12 tracks × ~40 bytes/track ≈ **480 bytes** per besked. Ved 8 Hz ≈ **3.8 KB/sek**.
WebSocket-køen (5000 max) absorberer dette trivielt.

### 6.7 — Frontend: Alpine.js audioStore

**Ny fil**: `app/domains/presentation/static/js/stores/audioStore.js`

```javascript
document.addEventListener('alpine:init', () => {
    Alpine.store('audio', {
        recording: false,
        tracks: [],          // [{label, peaks, clip}]
        _decayTimer: null,

        updateLevels(data) {
            this.recording = true;
            this.tracks = data.tracks.map(t => ({
                label: t.label,
                peaks: t.peaks,
                clip: t.peaks.some(p => p >= 0.99),
            }));
        },

        clearLevels() {
            this.recording = false;
            this.tracks = [];
        },
    });
});
```

### 6.8 — Frontend: messageHandler.js

Tilføj ny case i message-routeren:

```javascript
case 'audio_levels':
    Alpine.store('audio').updateLevels(message.data);
    break;

case 'audio_recording_stopped':
    Alpine.store('audio').clearLevels();
    break;
```

### 6.9 — Frontend: Jinja2 component

**Ny fil**: `app/domains/presentation/templates/components/audio_levels_panel.html`

8 LED-segmenter per kanal — broadcast-standard dBFS-skala:

| Segment | Tærskel | ~dBFS | Farve |
|---------|---------|-------|-------|
| 1 | > 0.02 | -34 | Grøn |
| 2 | > 0.05 | -26 | Grøn |
| 3 | > 0.10 | -20 | Grøn |
| 4 | > 0.25 | -12 | Grøn |
| 5 | > 0.45 | -7 | Gul |
| 6 | > 0.65 | -3.7 | Gul |
| 7 | > 0.85 | -1.4 | Rød |
| 8 | > 0.95 | -0.4 | Rød (clip) |

```html
<div x-data x-show="$store.audio.recording" class="...">
  <h3>Audio Levels</h3>
  <template x-for="track in $store.audio.tracks" :key="track.label">
    <div class="flex items-center gap-2">
      <span class="w-20 text-xs truncate" x-text="track.label"></span>
      <template x-for="(peak, i) in track.peaks" :key="i">
        <div class="flex gap-0.5">
          <!-- 8 LED segments: 4× green, 2× yellow, 2× red -->
          <div class="w-1.5 h-3 rounded-sm transition-colors duration-100"
               :class="peak > 0.02 ? 'bg-green-500' : 'bg-gray-700'"></div>
          <div class="w-1.5 h-3 rounded-sm transition-colors duration-100"
               :class="peak > 0.05 ? 'bg-green-500' : 'bg-gray-700'"></div>
          <div class="w-1.5 h-3 rounded-sm transition-colors duration-100"
               :class="peak > 0.10 ? 'bg-green-500' : 'bg-gray-700'"></div>
          <div class="w-1.5 h-3 rounded-sm transition-colors duration-100"
               :class="peak > 0.25 ? 'bg-green-500' : 'bg-gray-700'"></div>
          <div class="w-1.5 h-3 rounded-sm transition-colors duration-100"
               :class="peak > 0.45 ? 'bg-yellow-500' : 'bg-gray-700'"></div>
          <div class="w-1.5 h-3 rounded-sm transition-colors duration-100"
               :class="peak > 0.65 ? 'bg-yellow-500' : 'bg-gray-700'"></div>
          <div class="w-1.5 h-3 rounded-sm transition-colors duration-100"
               :class="peak > 0.85 ? 'bg-red-500' : 'bg-gray-700'"></div>
          <div class="w-1.5 h-3 rounded-sm transition-colors duration-100"
               :class="peak > 0.95 ? 'bg-red-600 brightness-125' : 'bg-gray-700'"></div>
        </div>
      </template>
    </div>
  </template>
</div>
```

Stereo tracks viser L og R segmenter side om side (16 LEDs total).
Clip-segment (8) bruger `brightness-125` for ekstra synlighed.
Clip-hold (rød LED forbliver 2 sek) kan tilføjes med `clip` boolean + `setTimeout` clear.

### 6.10 — Wiring & inkludering

- `templates/index.html`: Inkluder `audio_levels_panel.html` component + load `audioStore.js`
- `views.py`: Ingen ændring (Jinja2 include er nok)
- `registration.py` (presentation): Tilføj event subscription
- `registration.py` (audio_recording): Ingen ændring (callback adapter håndterer det)

### 6.11 — Fil-ændringer oversigt

| Fil | Ændring | Type |
|-----|---------|------|
| `recorder/base.py` | Peak-akk. + emit hvert 93. block i `_writer_loop` | Modify |
| `recorder/callback.py` | Tilføj `on_levels()` til protocol | Modify |
| `callback_adapter.py` | Implementér `on_levels()` → `AudioLevelsEvent` | Modify |
| `core/events/audio_events.py` | Nyt `AudioLevelsEvent` | Modify |
| `presentation/event_handlers.py` | Ny handler `handle_audio_levels_event` | Modify |
| `presentation/registration.py` | Subscribe på `AudioLevelsEvent` | Modify |
| `static/js/stores/audioStore.js` | **Ny fil** — Alpine store | Create |
| `static/js/services/messageHandler.js` | Ny case `audio_levels` | Modify |
| `templates/components/audio_levels_panel.html` | **Ny fil** — LED-meters | Create |
| `templates/index.html` | Include component + load store | Modify |

### 6.12 — Test-strategi

- **Unit test** `_writer_loop` metering: Mock callback, feed N blokke, verificér
  `on_levels` kaldes efter 47 blokke med korrekte peak-værdier.
- **Unit test** `audioStore.js`: Verificér `updateLevels()` parser data korrekt.
- **Integration**: Verificér at `AudioLevelsEvent` propagerer fra writer → EventBus → WebSocket.
- **Mypy / lint-imports**: Ingen nye cross-domain imports. `AudioLevelsEvent` bor i `core/events/`.

### 6.13 — Risici & mitigering

| Risiko | Sandsynlighed | Mitigering |
|--------|---------------|------------|
| GIL-contention fra writer-tråd → event loop | Lav | `call_soon_threadsafe` er lock-free. 8 calls/sek er trivielt. |
| WebSocket backpressure ved mange clients | Lav | Queue dropper ældste besked ved overflow. 8 msg/sek er ingenting vs. eksisterende file_progress traffic. |
| Peak-beregning forsinker WAV writes | Negligibel | ~2.5 µs/block vs. ~2700 µs callback-budget. |
| Clip false positives ved PCM_24→float mapping | Lav | `sounddevice` normaliserer til [-1.0, 1.0]. Threshold 0.99 giver margin. |

### 6.14 — Mulige udvidelser (ikke i scope)

- **Peak hold**: Rød LED forbliver 2 sek efter clip (frontend `setTimeout`).
- **RMS metering**: `np.sqrt(np.mean(block**2, axis=0))` — dyrere, men stadig billigt.
- **Grafisk VU**: Canvas/SVG bar-meters i stedet for LEDs. Kræver mere frontend-kode.
- **Konfigurerbar opdateringsrate**: Setting for `_LEVELS_INTERVAL_BLOCKS`.

---

## Åbne spørgsmål

1. ~~**Justin dato+tid sync**~~ → **AFKLARET**: Vi bruger `POST /ingest/requestCurrentFilename` til at hente det præcise filnavn-præfiks fra Justin. Fallback til lokalt systemtidspunkt ved API-fejl.

2. ~~**Kanal start-logik**~~ → **AFKLARET**: Første kanal-start trigger audio. Alle kanaler starter/stopper nogenlunde samtidig (podcast-workflow). Krydsende start/stop håndteres ikke.

3. ~~**macOS device enumeration**~~ → **AFKLARET**: Vis alle CoreAudio devices — brugeren vælger selv. Implementeret i `CoreAudioRecorder.list_devices()`.

4. ~~**Callback/event bridge**~~ → **AFKLARET**: Sync `RecorderCallback` protokol + `RecorderEventAdapter` med `call_soon_threadsafe`. Se §1.1b og §2.5.

5. ~~**Device disconnect detection**~~ → **AFKLARET**: Callback watchdog i base class (500ms timeout). Se §1.3.



