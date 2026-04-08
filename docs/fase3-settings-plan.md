# Fase 3: User Settings i DB + UI

**Dato:** 2026-04-08  
**Status:** Step A i gang  
**Kontekst:** Fase 1 (FileRepository → SQLite) og Fase 2 (Event-log persistence) er færdige. Nu ryddes Settings-modalen op som fundament for editable user settings.

---

## Beslutninger

| Beslutning | Valg |
|---|---|
| Settings i UI (Step B) | source/dest dirs, network mount, tally IP, output folder template, max_concurrent_copies, justin_auto_stop_minutes |
| Justin API URL | Skjult (altid localhost) — kun `auto_stop_minutes` i UI |
| Tally light | Kun `tally_light_switch_ip` |
| Reload Config knap | Fjernes — erstattes af Save-knap i Step B |
| Admin Actions placering | Forbliver i bunden af modal, over Build & Runtime |
| Approach | Strip først (Step A), byg editable settings bagefter (Step B) |
| Platform-felter | `windows_drive_letter` droppes fra UI (ubrugt). `macos_mount_point` vises som "Mount Point" |
| DB-migrering | Alembic `upgrade head` kører automatisk ved app-opstart — PyInstaller-brugere auto-migreres |

---

## Step A: Strip Modal (ren base)

**Formål:** Fjern alle ~40 read-only low-level settings. Resultatet er en minimal modal klar til at modtage editable settings.

**Modal efter Step A:**
1. Placeholder-tekst øverst ("Settings will be configurable here…")
2. Administrative Actions (Scanner Control + Restart App) — **uden** Reload Config
3. Build & Runtime (allernederst, read-only)

### Checklist

- [x] **A1** Strip 10 read-only HTML-sektioner fra `settings_modal.html`:
  - Path Configuration
  - Copy Configuration
  - Growing File Support
  - Storage Monitoring & Thresholds
  - Space Management
  - Network & Retry Configuration
  - Platform Configuration
  - File Management
  - Output Folder Template
  - Logging Configuration
- [x] **A2** Flyt "Build & Runtime" til allernederst i modalen
- [x] **A3** Fjern "Reload Config" kortet fra Administrative Actions (behold Scanner Control + Restart App)
- [x] **A4** Tilføj placeholder-sektion øverst i modalen
- [x] **A5** Fjern `reloadConfig()` + `reloadingConfig` state fra `settingsStore.js`
- [x] **A6** Opdater `SettingsStore` type i `global.d.ts` (fjern `reloadingConfig`)
- [x] **A7** Verificering:
  - [x] 1038 tests grønne (pytest --ignore=scripts)
  - [x] mypy app/ — Success: no issues found in 157 source files
  - [x] lint-imports — bestået (pre-existing stale ignore rule, ikke relateret)
  - [ ] Manuel test: Modal viser KUN placeholder, Admin Actions (2 knapper), Build & Runtime
  - [ ] Ingen JS console errors
  - [ ] Scanner pause/resume virker
  - [ ] Restart App virker

### Berørte filer (Step A)

| Fil | Ændring |
|---|---|
| `app/domains/presentation/templates/components/settings_modal.html` | Strip 10 sektioner, reorder, fjern Reload Config kort |
| `app/domains/presentation/static/js/stores/settingsStore.js` | Fjern `reloadConfig()` + state |
| `app/domains/presentation/static/js/global.d.ts` | Fjern `reloadingConfig` fra SettingsStore type |

---

## Step B: Editable Settings + DB + API + UI

**Formål:** Brugeren kan ændre settings direkte i UI. Env-filer afskaffes for normal brug.

### User Settings (12 stk)

| Setting | Type | Default | Restart? | UI-label | UI-sektion |
|---|---|---|---|---|---|
| `source_directory` | str | (påkrævet) | ✅ | Source Directory | Paths |
| `destination_directory` | str | (påkrævet) | ✅ | Destination Directory | Paths |
| `network_share_url` | str | `""` | ✅ | Network Share URL | Network |
| `enable_auto_mount` | bool | `false` | ✅ | Auto Mount | Network |
| `macos_mount_point` | str | `""` | ✅ | Mount Point | Network |
| `tally_light_switch_ip` | str | `""` | ✅ | Tally Light IP | Hardware |
| `output_folder_template_enabled` | bool | `false` | ❌ | Enable Output Folders | Output Folder |
| `output_folder_rules` | str | `""` | ❌ | Folder Rules | Output Folder |
| `output_folder_default_category` | str | `"OTHER"` | ❌ | Default Category | Output Folder |
| `output_folder_date_format` | str | `"filename[0:6]"` | ❌ | Date Format | Output Folder |
| `max_concurrent_copies` | int | `7` | ✅ | Max Concurrent Copies | Performance |
| `justin_auto_stop_minutes` | int | `0` | ❌ | Auto-stop After (min) | Automation |

> **Droppet fra UI:** `windows_drive_letter` — altid tom i praksis, Windows bruger UNC-stier direkte via `destination_directory`. Feltet bevares i `Settings`-klassen som intern fallback.

### DB-migration & PyInstaller

Appen pakkes med PyInstaller og distribueres som binary til brugere. Alembic migrations **skal** køre automatisk:
- Ved app-opstart: `alembic upgrade head` (programmatisk, via Alembic API)
- Migrations bundles med i PyInstaller-pakken (`alembic/` + `alembic.ini`)
- Brugeren ser aldrig en migration — DB opgraderes transparent fra enhver tidligere version
- Alembic env.py peger på `Settings.database_path` (samme DB-fil som FileRepository)

### Checklist

- [x] **B1** Alembic migration `003_user_settings.py`:
  - Opret `user_settings` tabel (key TEXT PK, value TEXT, updated_at TEXT)
  - Seed med sane defaults for alle 12 settings, så appen virker out-of-the-box
  - Verificeret: auto-migration fungerer (test_migrations_are_idempotent)
- [x] **B1b** Env-fil migration (upgrade path): ved opstart, hvis en setting i DB stadig har default-værdien OG env-filen har en anden værdi → overfør env-værdien til DB. Implementeret i `UserSettingsService.init(env_settings=...)`.
- [x] **B2** `app/domains/shared/settings_service.py` — defaults → DB loader, cache, type coercion
- [x] **B3** CQRS: `UpdateUserSettingsCommand` + `GetUserSettingsQuery` + handlers
- [x] **B4** Registrering i `app/domains/shared/registration.py`
- [x] **B5** REST API: `GET /api/system/user-settings` (alle 12 settings med metadata)
- [x] **B6** REST API: `PUT /api/system/user-settings` (validér, gem i DB, returner `requires_restart`)
- [x] **B7** UI formular i `settings_modal.html`:
  - Input-felter for stier (source, destination, network share, mount point)
  - Toggles for booleans (auto_mount, output_folder_template)
  - Number input for max_concurrent_copies, auto_stop_minutes
  - Textarea for output_folder_rules
  - Global Save-knap
- [x] **B8** "Restart required" banner + "Restart now" knap ved pending ændringer
- [x] ~~**B9** Env-fil migration~~ (erstattet af B1b)
- [x] **B10** `settingsStore.js` — save/edit/dirty-tracking/loadUserSettings logic
- [x] **B11** Tests:
  - [x] `tests/domains/test_settings_service.py` — 25 unit tests for UserSettingsService
  - [x] Alle 1063 tests grønne (1038 eksisterende + 25 nye)
- [x] **B12** Quality gate:
  - [x] `pytest --ignore=scripts` — 1063 passed
  - [x] `mypy app/` — Success: no issues found in 158 source files
  - [x] `lint-imports` — bestået (pre-existing stale ignore rule)
  - [ ] Manuel test: Ændr settings i UI → save → verify
  - [ ] Manuel test: Restart required banner vises for path-ændringer
  - [ ] Manuel test: Fresh install med tom DB

---

## Env-fil deprecation plan

### Status quo
- `Settings(BaseSettings)` i `app/config.py` loader fra hostname-specifik env-fil (f.eks. `AX94025-settings.env`)
- ~50 settings, alle med hardcoded defaults i klassen
- `app/utils/host_config.py` genererer env-filer automatisk ved første start

### Transition (Step B)
- **12 brugervendte settings** → DB (user_settings tabel)
- **~40 interne settings** (chunk sizes, timeouts, thresholds, log paths, justin URL, tally credentials, osv.) → beholdes med hardcoded defaults i `Settings`-klassen. De ændres aldrig af brugere.
- **B1b** migrerer eksisterende env-værdier til DB ved første opstart
- **SettingsService** loader: hardcoded defaults → DB (env-filen springes over for de 12 UI-settings)

### Step C: Fjern env-fil loading (fremtidig oprydning)

Når Step B er udrullet og alle brugere er migreret:

- [ ] **C1** Fjern env-fil loading fra `Settings`-klassen (`SettingsConfigDict(env_file=...)` → fjernes)
- [ ] **C2** Fjern `app/utils/host_config.py` (genererer env-filer — ikke længere nødvendig)
- [ ] **C3** Fjern `POST /api/system/reload-config` endpoint + `ReloadConfigCommand` (env-reload giver ikke mening med DB)
- [ ] **C4** Fjern `GET /api/system/config-info` endpoint + `GetConfigInfoQuery` (viser env-fil info)
- [ ] **C5** Fjern `GetSettingsQuery` + handler (erstattet af SettingsService)
- [ ] **C6** Slet env-filer fra repo (`settings.env`, `mac-settings.env`, `AX94025-settings.env`, `config/`)
- [ ] **C7** `Settings`-klassen reduceres til kun hardcoded defaults for interne settings — ingen env-fil loading

> **Timing:** Step C er en separat oprydning EFTER Step B er stabil i produktion. Env-filen gør ingen skade i mellemtiden — den ignoreres bare for de 12 DB-settings.

### Berørte filer (Step B)

| Fil | Ændring |
|---|---|
| `alembic/versions/003_user_settings.py` | NY — migration |
| `app/domains/shared/settings_service.py` | NY — 3-lags settings loader |
| `app/domains/shared/commands.py` | Tilføj `UpdateUserSettingCommand` |
| `app/domains/shared/queries.py` | Tilføj `GetUserSettingsQuery` |
| `app/domains/shared/config_handlers.py` | Nye handlers for settings CQRS |
| `app/domains/shared/registration.py` | Registrer nye handlers |
| `app/domains/shared/api/config_api.py` | GET/PUT `/api/system/user-settings` |
| `app/config.py` | Merge Settings med DB-values |
| `app/domains/presentation/templates/components/settings_modal.html` | Editable formular |
| `app/domains/presentation/static/js/stores/settingsStore.js` | Save/edit/dirty logic |
| `app/domains/presentation/static/js/global.d.ts` | Opdaterede types |
| `tests/domains/test_settings_service.py` | NY — SettingsService tests |
