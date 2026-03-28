# Test Plan — Refaktorering for Testbarhed

**Dato:** 2026-03-27  
**Baseline:** 312 tests, 51% coverage  
**Regel:** Refaktorering over mocks. Vi udtrækker ren logik så den kan testes uden mocks.

---

## Oversigt: Filer der mangler tests

| # | Fil | Coverage | Linjer | Ren logik der kan udtrækkes | Prioritet |
|---|-----|----------|--------|----------------------------|-----------|
| 1 | `file_discovery/file_discovery_slice.py` | 15% | 151 | Fil-selektion, cooldown-logik, prioritering | 🔴 Høj |
| 2 | `file_processing/space_retry_manager.py` | 15% | 151 | Retry-beslutninger, grænser, timer-abstraktion | 🔴 Høj |
| 3 | `storage/storage_checker.py` | 17% | 137 | Status-evaluering, diskplads-beregning | 🔴 Høj |
| 4 | `file_processing/consumer/job_space_manager.py` | 25% | 53 | Pladsmangel-klassificering, netværksdetektion | 🔴 Høj |
| 5 | `file_discovery/growing_file_detector.py` | 29% | 75 | Vækst-analyse, stabilitetsdetektion | 🔴 Høj |
| 6 | `file_processing/consumer/job_copy_executor.py` | 29% | 85 | Fejl-klassificering, state-transitions | 🟡 Medium |
| 7 | `file_processing/consumer/job_finalization_service.py` | 31% | 48 | Finaliserings-guards, preconditions | 🟡 Medium |
| 8 | `file_processing/space_checker.py` | 32% | 41 | Pladsberechning, margin-logik | 🟡 Medium |
| 9 | `file_discovery/file_scanner_service.py` | 37% | 43 | Tynd adapter — lav prioritet | 🟢 Lav |
| 10 | `file_discovery/file_scanner.py` | 40% | 194 | Fil-filtreringslogik, stabilitetstjek | 🟡 Medium |
| 11 | `file_processing/job_queue.py` | 44% | 114 | Network-recovery-beslutning | 🟡 Medium |
| 12 | `storage/storage_monitor/storage_monitor.py` | 54% | 193 | Recovery/unavailable-detektion | 🟢 Lav |

---

## Prioritet 1: File Discovery Slice (15% → ~80%)

### Problemer
- `get_active_file_by_path()`, `get_current_file_for_path()`, `get_files_by_status()` kalder alle `file_repository.get_all()` og filtrerer in-memory
- Sorteringslogik (prioritet + tid) er duplikeret i 3 metoder
- Cooldown-check bruger `datetime.now()` direkte — kan ikke testes med specifikke tidspunkter
- `_is_more_current()` er ren logik men tæt koblet til klassen

### Refaktorering: Udtræk `FileSelectionLogic`

```python
# NY FIL: app/domains/file_discovery/file_selection_logic.py

class FileSelectionLogic:
    """Ren logik: sortér og vælg filer — INGEN mocks nødvendige."""

    ACTIVE_STATUSES = {
        FileStatus.DISCOVERED, FileStatus.GROWING, FileStatus.READY,
        FileStatus.READY_TO_START_GROWING, FileStatus.IN_QUEUE,
        FileStatus.COPYING, FileStatus.WAITING_FOR_NETWORK,
        FileStatus.WAITING_FOR_SPACE,
    }

    ACTIVE_PRIORITIES = {
        FileStatus.COPYING: 1, FileStatus.IN_QUEUE: 2,
        FileStatus.WAITING_FOR_NETWORK: 3, FileStatus.WAITING_FOR_SPACE: 4,
        FileStatus.READY: 5, FileStatus.READY_TO_START_GROWING: 6,
        FileStatus.GROWING: 7, FileStatus.DISCOVERED: 8,
    }

    @staticmethod
    def sort_key(file: TrackedFile) -> tuple:
        """Sorteringsnøgle: laveste prioritet + nyeste tid først."""
        priority = FileSelectionLogic.ACTIVE_PRIORITIES.get(file.status, 99)
        time_val = -(file.discovered_at.timestamp() if file.discovered_at else 0)
        return (priority, time_val)

    @staticmethod
    def select_active_for_path(
        all_files: list[TrackedFile], file_path: str
    ) -> TrackedFile | None:
        candidates = [
            f for f in all_files
            if f.file_path == file_path and f.status in FileSelectionLogic.ACTIVE_STATUSES
        ]
        return min(candidates, key=FileSelectionLogic.sort_key) if candidates else None

    @staticmethod
    def select_current_for_path(
        all_files: list[TrackedFile], file_path: str
    ) -> TrackedFile | None:
        candidates = [f for f in all_files if f.file_path == file_path]
        return min(candidates, key=FileSelectionLogic.sort_key) if candidates else None

    @staticmethod
    def is_more_current(file_a: TrackedFile, file_b: TrackedFile) -> bool:
        """Returner True hvis file_a er mere aktuel end file_b."""
        return FileSelectionLogic.sort_key(file_a) < FileSelectionLogic.sort_key(file_b)

    @staticmethod
    def deduplicate_by_path(
        all_files: list[TrackedFile],
    ) -> dict[str, TrackedFile]:
        """Returner mest aktuelle fil per sti."""
        result: dict[str, TrackedFile] = {}
        for f in all_files:
            current = result.get(f.file_path)
            if not current or FileSelectionLogic.is_more_current(f, current):
                result[f.file_path] = f
        return result
```

### Refaktorering: Udtræk `CooldownChecker`

```python
# NY FIL: app/domains/file_discovery/cooldown_checker.py

class CooldownChecker:
    """Ren logik: cooldown-håndtering — INGEN mocks nødvendige."""

    @staticmethod
    def is_in_cooldown(
        error_timestamp: datetime,
        cooldown_minutes: int,
        current_time: datetime,
    ) -> tuple[bool, float]:
        """Returner (is_in_cooldown, minutter_tilbage)."""
        cooldown = timedelta(minutes=cooldown_minutes)
        elapsed = current_time - error_timestamp
        in_cooldown = elapsed < cooldown
        remaining = max(0, (cooldown - elapsed).total_seconds() / 60)
        return in_cooldown, remaining

    @staticmethod
    def should_skip_space_error(
        tracked_file: TrackedFile,
        cooldown_minutes: int,
        current_time: datetime,
    ) -> tuple[bool, str]:
        """Returner (should_skip, reason)."""
        if tracked_file.status != FileStatus.SPACE_ERROR:
            return False, ""
        if not tracked_file.space_error_at:
            return False, ""
        in_cd, remaining = CooldownChecker.is_in_cooldown(
            tracked_file.space_error_at, cooldown_minutes, current_time
        )
        if in_cd:
            return True, f"Space error cooldown: {remaining:.1f} min remaining"
        return False, ""
```

### Tests der kan skrives UDEN mocks
- `test_sort_key_priorities` — COPYING < IN_QUEUE < READY < DISCOVERED
- `test_sort_key_time_tiebreaker` — nyeste fil vinder ved samme status
- `test_select_active_for_path` — finder korrekt aktiv fil
- `test_select_active_returns_none_when_all_terminal` — COMPLETED/FAILED ignoreres
- `test_select_current_includes_terminal` — inkluderer alle statusser
- `test_is_more_current` — sammenligner to filer korrekt
- `test_deduplicate_by_path` — kun én fil per sti
- `test_cooldown_active` — fil i cooldown returnerer True
- `test_cooldown_expired` — fil efter cooldown returnerer False
- `test_cooldown_no_space_error` — ikke-SPACE_ERROR returnerer False
- `test_cooldown_no_timestamp` — manglende `space_error_at` returnerer False
- **Estimat: ~15 tests, 0 mocks**

---

## Prioritet 2: Growing File Detector (29% → ~85%)

### Problemer
- `check_file_growth_status()` blander filsystem-kald (`aiofiles.os.path.getsize`) med ren beslutningslogik
- `datetime.now()` brugt direkte — kan ikke teste tidsbaserede grænser
- Vækstrate-beregning, stabilitets-timeout og min-size-logik er alt sammen ren matematik

### Refaktorering: Udtræk `GrowthStatusAnalyzer`

```python
# NY FIL: app/domains/file_discovery/growth_status_analyzer.py

class GrowthStatusAnalyzer:
    """Ren logik: bestem filvækststatus — INGEN mocks nødvendige."""

    @staticmethod
    def determine_status(
        current_size: int,
        previous_size: int,
        growth_stable_since: datetime | None,
        current_time: datetime,
        min_size_bytes: int,
        stability_timeout_seconds: int,
    ) -> FileStatus:
        """Ren funktion: returnerer anbefalet FileStatus."""
        is_growing = current_size > previous_size

        if is_growing:
            if current_size >= min_size_bytes:
                return FileStatus.READY_TO_START_GROWING
            return FileStatus.GROWING

        # Filen vokser ikke
        if growth_stable_since is None:
            return FileStatus.GROWING  # Netop stoppet, vent på stabilitet

        stable_seconds = (current_time - growth_stable_since).total_seconds()
        if stable_seconds >= stability_timeout_seconds:
            return FileStatus.READY
        return FileStatus.GROWING  # Stadig ustabil

    @staticmethod
    def calculate_growth_rate_mbps(
        current_size: int,
        first_seen_size: int,
        elapsed_seconds: float,
    ) -> float:
        """Ren funktion: beregn vækstrate i MB/s."""
        if elapsed_seconds <= 0 or first_seen_size <= 0:
            return 0.0
        size_diff_mb = (current_size - first_seen_size) / (1024 * 1024)
        return size_diff_mb / elapsed_seconds

    @staticmethod
    def determine_stability_timestamp(
        current_size: int,
        previous_size: int,
        growth_stable_since: datetime | None,
        current_time: datetime,
    ) -> datetime | None:
        """Ren funktion: bestem hvornår filen blev stabil."""
        if current_size > previous_size:
            return None  # Stadig vokser
        if growth_stable_since is None:
            return current_time  # Netop stoppet
        return growth_stable_since  # Allerede stabil
```

### Tests der kan skrives UDEN mocks
- `test_growing_file_returns_growing` — size øget, under min_size
- `test_growing_file_above_min_returns_ready_to_start` — size øget, over min_size
- `test_stable_file_returns_ready` — ikke vokset, stabil længe nok
- `test_recently_stopped_returns_growing` — ikke vokset, growth_stable_since=None
- `test_not_stable_long_enough_returns_growing` — stabil men under timeout
- `test_growth_rate_calculation` — normal case
- `test_growth_rate_zero_elapsed` — edge case
- `test_stability_timestamp_still_growing` — returnerer None
- `test_stability_timestamp_just_stopped` — returnerer current_time
- `test_stability_timestamp_already_stable` — returnerer original
- **Estimat: ~12 tests, 0 mocks**

---

## Prioritet 3: Storage Checker (17% → ~75%)

### Problemer
- Alt er filsystem-I/O: `aiofiles.os.path.exists()`, `shutil.disk_usage()`, test-fil-oprettelse
- `_evaluate_status()` er den ENESTE rene metode, men den er privat og tæt koblet
- Status-evaluering (OK/WARNING/CRITICAL/ERROR) er ren matematik men begravet i I/O-kode

### Refaktorering: Udtræk `StorageStatusEvaluator` + `FilesystemProbe`

```python
# NY FIL: app/domains/storage/storage_status_evaluator.py

class StorageStatusEvaluator:
    """Ren logik: evaluér disk-status — INGEN mocks nødvendige."""

    @staticmethod
    def evaluate(
        free_gb: float,
        total_gb: float,
        warning_threshold_gb: float,
        critical_threshold_gb: float,
        is_accessible: bool,
        has_write_access: bool,
    ) -> StorageStatus:
        if not is_accessible:
            return StorageStatus.ERROR
        if not has_write_access:
            return StorageStatus.CRITICAL
        if free_gb < critical_threshold_gb:
            return StorageStatus.CRITICAL
        if free_gb < warning_threshold_gb:
            return StorageStatus.WARNING
        return StorageStatus.OK

    @staticmethod
    def build_error_message(
        is_accessible: bool,
        has_write_access: bool,
        free_gb: float,
        critical_threshold_gb: float,
    ) -> str | None:
        if not is_accessible:
            return "Path is not accessible"
        if not has_write_access:
            return "No write access"
        if free_gb < critical_threshold_gb:
            return f"Critical: only {free_gb:.1f} GB free"
        return None
```

### Tests der kan skrives UDEN mocks
- `test_evaluate_ok` — tilgængelig, har plads
- `test_evaluate_warning` — under warning-grænse
- `test_evaluate_critical_space` — under critical-grænse
- `test_evaluate_critical_no_write` — ingen skriveadgang
- `test_evaluate_error_not_accessible` — sti findes ikke
- `test_error_message_not_accessible` — korrekt besked
- `test_error_message_no_write` — korrekt besked
- `test_error_message_critical` — korrekt besked
- `test_error_message_ok_returns_none` — ingen besked
- **Estimat: ~10 tests, 0 mocks**

---

## Prioritet 4: Space Checker (32% → ~85%)

### Problemer
- `check_space_for_file()` kalder `storage_monitor.get_destination_info()` direkte
- Pladsberegning (safety margin + minimum after copy) er ren matematik
- Fejlbeskeder er template-baserede — ren string-logik

### Refaktorering: Udtræk `SpaceCalculator`

```python
# NY FIL: app/domains/file_processing/space_calculator.py

class SpaceCalculator:
    """Ren logik: diskplads-beregning — INGEN mocks nødvendige."""

    def __init__(
        self,
        safety_margin_gb: float,
        min_free_after_copy_gb: float,
    ):
        self.safety_margin_bytes = int(safety_margin_gb * 1024**3)
        self.min_free_after_bytes = int(min_free_after_copy_gb * 1024**3)

    def required_space(self, file_size_bytes: int) -> int:
        """Returner minimum nødvendig ledig plads i bytes."""
        return file_size_bytes + self.safety_margin_bytes + self.min_free_after_bytes

    def has_sufficient_space(
        self, available_bytes: int, file_size_bytes: int
    ) -> bool:
        return available_bytes >= self.required_space(file_size_bytes)

    def shortage_bytes(
        self, available_bytes: int, file_size_bytes: int
    ) -> int:
        """Returner antal bytes vi mangler (0 hvis nok plads)."""
        required = self.required_space(file_size_bytes)
        return max(0, required - available_bytes)

    def format_reason(
        self,
        available_bytes: int,
        file_size_bytes: int,
        has_space: bool,
    ) -> str:
        available_gb = available_bytes / (1024**3)
        required_gb = self.required_space(file_size_bytes) / (1024**3)
        file_gb = file_size_bytes / (1024**3)
        if has_space:
            return (
                f"OK: {available_gb:.1f} GB ledig, "
                f"kræver {required_gb:.1f} GB (fil: {file_gb:.1f} GB)"
            )
        shortage_gb = self.shortage_bytes(available_bytes, file_size_bytes) / (1024**3)
        return (
            f"Utilstrækkelig plads: {available_gb:.1f} GB ledig, "
            f"mangler {shortage_gb:.1f} GB (fil: {file_gb:.1f} GB)"
        )
```

### Tests der kan skrives UDEN mocks
- `test_required_space_includes_margins` — file + safety + min_free
- `test_sufficient_space_exact_match` — præcis nok plads
- `test_sufficient_space_with_surplus` — mere end nok
- `test_insufficient_space` — for lidt plads
- `test_shortage_calculation` — korrekt antal manglende bytes
- `test_shortage_zero_when_enough` — 0 hvis der er plads
- `test_format_reason_ok` — formaterer OK-besked
- `test_format_reason_shortage` — formaterer mangel-besked
- `test_zero_file_size` — edge case
- `test_large_file_overflow` — stor fil (~TB)
- **Estimat: ~12 tests, 0 mocks**

---

## Prioritet 5: Space Retry Manager (15% → ~70%)

### Problemer
- `_execute_retry_task()` bruger `asyncio.sleep()` direkte — blokerer tests
- Retry-grænser og beslutningslogik er blandet med asynkron task-håndtering
- Lock + task-dict management er kompleks og svær at teste isoleret

### Refaktorering: Udtræk `RetryDecision` + `RetryLimitChecker`

```python
# NY FIL: app/domains/file_processing/retry_logic.py

class RetryLimitChecker:
    """Ren logik: skal vi give op? — INGEN mocks nødvendige."""

    @staticmethod
    def should_give_up(
        current_retry_count: int, max_retries: int
    ) -> tuple[bool, str]:
        if current_retry_count >= max_retries:
            return True, f"Oversteget max retries ({max_retries})"
        return False, ""

    @staticmethod
    def calculate_delay_seconds(
        retry_count: int,
        base_delay: int = 1800,
        max_delay: int = 3600,
    ) -> int:
        """Eksponentiel backoff: 30m, 60m, 60m, 60m..."""
        delay = min(base_delay * (2 ** (retry_count - 1)), max_delay)
        return delay


class RetryDecision:
    """Ren logik: skal retry fortsætte? — INGEN mocks nødvendige."""

    @staticmethod
    def should_retry_proceed(
        tracked_file: TrackedFile | None,
        expected_status: FileStatus = FileStatus.WAITING_FOR_SPACE,
    ) -> tuple[bool, str]:
        if tracked_file is None:
            return False, "Fil ikke fundet"
        if tracked_file.status != expected_status:
            return False, f"Status ændret til {tracked_file.status.value}"
        return True, ""


class SpaceShortageClassifier:
    """Ren logik: klassificér type af pladsmangel — INGEN mocks nødvendige."""

    @staticmethod
    def classify(reason: str) -> tuple[str, bool]:
        """Returner (issue_type, is_retryable)."""
        lower = reason.lower()
        if "not accessible" in lower:
            return "NETWORK", False
        if "insufficient" in lower or "space" in lower:
            return "SPACE", True
        return "UNKNOWN", False
```

### Tests der kan skrives UDEN mocks
- `test_should_give_up_at_max` — retry_count == max
- `test_should_not_give_up_below_max` — retry_count < max
- `test_delay_first_retry` — 30 min
- `test_delay_second_retry` — 60 min
- `test_delay_caps_at_max` — aldrig over max
- `test_retry_proceed_file_none` — False
- `test_retry_proceed_wrong_status` — False
- `test_retry_proceed_correct_status` — True
- `test_classify_network` — "not accessible" → NETWORK
- `test_classify_space` — "insufficient space" → SPACE
- `test_classify_unknown` — andre fejl → UNKNOWN
- **Estimat: ~13 tests, 0 mocks**

---

## Prioritet 6: Job Copy Executor (29% → ~70%)

### Problemer
- Fejlhåndtering er manuelt kodet for hver fejltype (NetworkError, FileCopyError, FileNotFound)
- State-transition + event-publishing mønster gentages 4 gange
- `_log_copy_result()` er ren logik men resten er I/O-tungt

### Refaktorering: Intet nyt at udtrække
`JobErrorClassifier` (86% coverage) håndterer allerede fejlklassificering. Den lave coverage skyldes primært at selve kopieringsflowet kræver integration med `FileStateMachine` og `GrowingFileCopyStrategy`. Disse er allerede abstraheret — tests kan bruge in-memory FileRepository + rigtig FileStateMachine.

### Tests (med minimale mocks — kun copy_strategy)
- `test_initialize_copy_status_transitions_to_copying` — state machine
- `test_execute_copy_success` — mock copy_strategy, verify state
- `test_execute_copy_file_not_found` — verify REMOVED status
- `test_handle_copy_failure_network_error` — verify WAITING_FOR_NETWORK
- `test_handle_copy_failure_generic_error` — verify FAILED
- `test_get_copy_executor_info` — ren logik
- **Estimat: ~8 tests, 1 mock (copy_strategy)**

---

## Prioritet 7: Job Finalization Service (31% → ~80%)

### Problemer
- Precondition-check (`COMPLETED_DELETE_FAILED`-guard) er ren logik men begravet i async-metode
- Tre finalize-metoder gentager samme mønster: get file → guard → transition → event

### Tests (med in-memory repo + rigtig state machine)
- `test_finalize_success_happy_path` — COPYING → COMPLETED
- `test_finalize_success_skips_completed_delete_failed` — guard
- `test_finalize_success_file_not_found` — returnerer tidligt
- `test_finalize_failure_transitions_to_failed` — COPYING → FAILED
- `test_finalize_max_retries` — verify error message
- `test_finalize_success_publishes_event` — FileCopyCompletedEvent
- **Estimat: ~8 tests, 0 mocks (bruger in-memory repo + state machine)**

---

## Prioritet 8: Job Queue Network Recovery (44% → ~65%)

### Refaktorering: Udtræk `NetworkRecoveryDecision`

```python
# Tilføj til: app/domains/file_processing/retry_logic.py

class NetworkRecoveryDecision:
    """Ren logik: bestem status efter netværksgenopretning."""

    @staticmethod
    def determine_recovery_status(
        tracked_file: TrackedFile,
    ) -> tuple[FileStatus, str]:
        if tracked_file.growth_rate_mbps and tracked_file.growth_rate_mbps > 0:
            return (
                FileStatus.READY_TO_START_GROWING,
                "Var voksende fil — genoptag growing copy",
            )
        return FileStatus.DISCOVERED, "Genvurdér for kopiering"
```

### Tests der kan skrives UDEN mocks
- `test_recovery_growing_file` — voksende fil → READY_TO_START_GROWING
- `test_recovery_static_file` — statisk fil → DISCOVERED
- `test_recovery_zero_growth_rate` — 0.0 → DISCOVERED
- `test_recovery_none_growth_rate` — None → DISCOVERED
- **Estimat: ~4 tests, 0 mocks**

---

## Samlet Oversigt

| Prioritet | Ny ren-logik-klasse | Fil | Tests (0 mocks) | Tests (minimale mocks) |
|-----------|--------------------|----|-----------------|----------------------|
| 1 | `FileSelectionLogic` | `file_discovery/file_selection_logic.py` | ~10 | — |
| 1 | `CooldownChecker` | `file_discovery/cooldown_checker.py` | ~5 | — |
| 2 | `GrowthStatusAnalyzer` | `file_discovery/growth_status_analyzer.py` | ~12 | — |
| 3 | `StorageStatusEvaluator` | `storage/storage_status_evaluator.py` | ~10 | — |
| 4 | `SpaceCalculator` | `file_processing/space_calculator.py` | ~12 | — |
| 5 | `RetryLimitChecker` | `file_processing/retry_logic.py` | ~5 | — |
| 5 | `RetryDecision` | `file_processing/retry_logic.py` | ~3 | — |
| 5 | `SpaceShortageClassifier` | `file_processing/retry_logic.py` | ~5 | — |
| 6 | — (eksisterende) | `consumer/job_copy_executor.py` | — | ~8 |
| 7 | — (eksisterende) | `consumer/job_finalization_service.py` | — | ~8 |
| 8 | `NetworkRecoveryDecision` | `file_processing/retry_logic.py` | ~4 | — |
| **Total** | **8 nye klasser** | **6 nye filer** | **~66** | **~16** |

### Forventet resultat
- **~82 nye tests** (66 uden mocks + 16 med minimale mocks)
- **312 → ~394 tests**
- **Coverage: 51% → ~68%**
- **8 nye rene logik-klasser** der er 100% testbare uden mocks
- **Ingen broken tests** — eksisterende kode bruger de nye klasser

---

## Arbejdsrækkefølge

1. **Opret rene logik-klasser** (P1–P5) — ingen ændring af eksisterende kode
2. **Skriv tests for rene klasser** — 0 mocks, hurtige, deterministiske
3. **Refaktorér eksisterende kode** til at bruge de nye klasser
4. **Skriv integrationstests** for P6–P7 med in-memory repo + state machine
5. **Kør alle tests** — verificér 0 brud
