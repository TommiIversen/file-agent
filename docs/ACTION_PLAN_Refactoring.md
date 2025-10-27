# File-Agent Refactoring Action Plan
*Handlingsplan for Arkitektonisk Evolution - 22. oktober 2025*

## 📈 **Current Status (27. Oktober 2025)**

- **Fase 1 & 2 er implementeret:** Event Bus'en er bygget og fuldt integreret. `StateManager` modtager og publicerer events.
- **Fase 3 er påbegyndt:**
  - ✅ `JobQueueService` er nu 100% event-drevet via `FileReadyEvent`.
  - ✅ `WebSocketManager` er event-drevet og lytter på `FileStatusChangedEvent` for real-time UI updates.
  - ✅ `FileScanner` er blevet refaktoreret til at være den primære kilde til `FileDiscoveredEvent`, hvilket er en forbedring af den oprindelige plan.
- **Parallel-kørsel:** Det nye event-system kører parallelt med det gamle pub/sub i `StateManager`, hvilket sikrer stabilitet under overgangen.


## 🎯 **KLAR BESLUTNING: Event Bus Først!**

Efter omfattende arkitektonisk analyse er strategien **krystalklart defineret:**

### **📊 Nøgletal:**
- **94 Python filer** (~13,800 linjer total)
- **90% kode genbrug** mulig med korrekt tilgang
- **StateManager (715 linjer)** = Primær refactoring target
- **13+ services** afhænger direkte af StateManager
- **324 linjer test kode** skal opdateres ved StateManager ændringer

---

## 🚨 **KRITISK: Ikke Start med StateManager!**

**StateManager = Central Hub:**
- 13+ services bruger det direkte
- Pub/Sub system med WebSocket subscribers  
- API endpoints kalder det direkte
- Dependency injection bygget omkring det

**StateManager refactoring først = System nedlukning = Mega Big Bang = Ekstrem risiko!**

---

## ✅ **KORREKT TILGANG: Event Bus Foundation**

### **Fase 1: Event Infrastructure (Week 1-4) - LAVEST RISIKO**

**Start med løs kobling infrastructure:**

```python
# app/core/events/domain_event.py
@dataclass
class DomainEvent:
    timestamp: datetime = field(default_factory=datetime.now)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

# app/core/events/event_bus.py  
class DomainEventBus:
    def __init__(self):
        self._handlers: Dict[Type, List[Callable]] = {}
    
    def subscribe(self, event_type: Type, handler: Callable):
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
    
    async def publish(self, event: DomainEvent):
        handlers = self._handlers.get(type(event), [])
        for handler in handlers:
            await handler(event)

# app/core/events/file_events.py
@dataclass
class FileDiscoveredEvent(DomainEvent):
    file_path: str
    file_size: int

@dataclass  
class FileStatusChangedEvent(DomainEvent):
    file_id: str
    old_status: FileStatus
    new_status: FileStatus

@dataclass
class FileReadyEvent(DomainEvent):
    file_id: str
    file_path: str
    
@dataclass
class NetworkFailureDetectedEvent(DomainEvent):
    detected_by: str
    error_message: str
```

**Fordele:**
- ✅ **Zero Breaking Changes** - Parallelt med eksisterende system
- ✅ **Risk-Free** - Kan rulles tilbage øjeblikkeligt
- ✅ **Test Isolation** - Event flow kan testes separat

---

### **Fase 2: StateManager Event Integration (Week 3-4) - ADDITIVE**

**Gradvis tilføj event publishing til eksisterende StateManager:**

```python
# Opdater StateManager UDEN at bryde eksisterende interface:
class StateManager:
    def __init__(self, cooldown_minutes: int = 60, event_bus: Optional[DomainEventBus] = None):
        # Existing initialization...
        self._event_bus = event_bus  # Optional dependency
    
    async def add_file(self, file_path: str, file_size: int) -> TrackedFile:
        # EXISTING logic UNCHANGED
        tracked_file = TrackedFile(...)
        self._files_by_id[tracked_file.id] = tracked_file
        
        # NEW: Optional event publishing (non-breaking)
        if self._event_bus:
            await self._event_bus.publish(
                FileDiscoveredEvent(file_path, file_size)
            )
        
        # Existing _notify() call unchanged
        await self._notify(FileStateUpdate(...))
        return tracked_file
```

**Test Parallel Event Flow:**
```python
# Test at events virker parallelt med eksisterende pub/sub:
async def test_parallel_event_flow():
    event_bus = DomainEventBus()
    state_manager = StateManager(event_bus=event_bus)
    
    received_events = []
    event_bus.subscribe(FileDiscoveredEvent, lambda e: received_events.append(e))
    
    # Existing functionality unchanged
    tracked_file = await state_manager.add_file("/test/file.mxf", 1024)
    
    # NEW events work in parallel
    assert len(received_events) == 1
    assert received_events[0].file_path == "/test/file.mxf"
```

---

### **Fase 3: Service Decoupling (Week 5-9) - MEDIUM RISIKO**

**Gradvis migration af services til event-driven communication:**

**Week 5-6: Scanner Domain Extraction**
```python
# app/domains/file_discovery/
├── scanner_service.py          # Extracted fra file_scanner.py
├── growing_detector.py         # Extracted fra growing_file_detector.py  
├── file_metadata.py           # Metadata utilities
├── stability_checker.py       # Stability logic
└── events.py                  # Discovery-specific events

# Event-driven scanner:
class FileDiscoveryService:
    def __init__(self, event_bus: DomainEventBus):
        self._event_bus = event_bus
        event_bus.subscribe(NetworkFailureDetectedEvent, self._pause_scanning)
        event_bus.subscribe(NetworkRecoveryEvent, self._resume_scanning)
```

**Week 7-8: Job Processing via Events**
```python
# app/domains/file_processing/
├── job_processor.py           # Refactored til event-driven
├── copy_coordinator.py        # Copy orchestration
└── network_failure_handler.py # Network detection logic

# Event-driven job processing:
class JobProcessor:
    def __init__(self, event_bus: DomainEventBus):
        event_bus.subscribe(FileReadyEvent, self._process_file)
        event_bus.subscribe(NetworkFailureDetectedEvent, self._pause_processing)
```

**Week 9: WebSocket Decoupling**
```python
# app/domains/presentation/
├── websocket_manager.py       # Pure connection management
├── event_handlers.py          # Domain event → WebSocket mapping
└── presentation_api.py        # Domain-agnostic API

# Event-driven WebSocket:
class PresentationEventHandlers:
    def __init__(self, websocket_manager: WebSocketManager):
        self._websocket_manager = websocket_manager
    
    async def handle_file_status_changed(self, event: FileStatusChangedEvent):
        await self._websocket_manager.broadcast({
            "type": "file_status_update",
            "file_id": event.file_id,
            "status": event.new_status.value
        })
```

---

### **Fase 4: StateManager Vertical Slices (Week 10-15) - HØJEST RISIKO**

**Nu hvor alle andre bruger events, kan StateManager deles op:**

```python
# app/core/file_management/
├── repository/
│   └── file_repository.py           # Tynd data storage (kun CRUD)
├── slices/
│   ├── file_discovery_slice.py     # Scanner concerns + business logic
│   ├── file_processing_slice.py    # Job processing concerns
│   ├── file_retry_slice.py         # Retry logic + coordination  
│   ├── file_monitoring_slice.py    # Statistics & WebSocket concerns
│   └── file_lifecycle_slice.py     # Cleanup & maintenance
└── shared/
    ├── file_prioritization.py      # Shared priority logic
    └── file_cooldown.py            # Shared cooldown logic
```

**Vertical Slice Eksempel:**
```python
# file_discovery_slice.py - BEHOLD kompleks business logic!
class FileDiscoverySlice:
    def __init__(self, repository: FileRepository, event_bus: EventBus):
        self._repository = repository
        self._event_bus = event_bus
    
    async def get_active_file_by_path(self, file_path: str) -> Optional[TrackedFile]:
        """Scanner-specific file lookup with complex active status filtering"""
        # FLYTTER eksisterende _get_active_file_for_path logic herover
        # INGEN duplication - business logic forbliver encapsulated
        pass
    
    async def should_skip_file_processing(self, file_path: str) -> bool:
        """Scanner-specific skip logic with cooldown"""
        # FLYTTER eksisterende should_skip_file_processing logic
        pass
    
    async def is_file_stable(self, file_id: str, stable_time: int) -> bool:
        """Scanner-specific stability detection"""
        # FLYTTER eksisterende is_file_stable logic
        pass
```

---

## 📋 **Konkret Migrationsplan**

### **Dette skal skrives (Kun ~500 nye linjer!):**

**Week 1-2: Event Infrastructure (~200 linjer)**
```
✅ app/core/events/domain_event.py           # ~50 linjer
✅ app/core/events/event_bus.py             # ~75 linjer  
✅ app/core/events/file_events.py           # ~75 linjer
```

**Week 3-4: StateManager Integration (~100 linjer)**
```
✅ Tilføj optional event_bus parameter til StateManager
✅ Tilføj event publishing til add_file(), update_file_status_by_id()
✅ Test parallel event flow
```

**Week 5-9: Service Extraction (~200 linjer integration)**
```
✅ FLYT eksisterende kode til domains/ folders
✅ Opdater imports og dependency injection
✅ Event handler registration
```

**Resten af koden (90%) = File movement og import updates!**

---

## 🎯 **Kritiske Implementeringsdetaljer**

### **Dependency Injection Update:**
```python
# app/dependencies.py - Tilføj event bus til DI container:
def get_event_bus() -> DomainEventBus:
    if "event_bus" not in _singletons:
        _singletons["event_bus"] = DomainEventBus()
    return _singletons["event_bus"]

def get_state_manager() -> StateManager:
    if "state_manager" not in _singletons:
        settings = get_settings()
        event_bus = get_event_bus()  # Inject event bus
        _singletons["state_manager"] = StateManager(
            cooldown_minutes=settings.space_error_cooldown_minutes,
            event_bus=event_bus  # NEW parameter
        )
    return _singletons["state_manager"]
```

### **Network Failure Real-Time Flow:**
```python
# Real-world scenarie: NAS går ned under kopi
# T+0ms:    FileCopyExecutor encounters network error  
# T+5ms:    NetworkErrorDetector identifies network failure
# T+10ms:   NetworkFailureDetectedEvent published via event bus
# T+15ms:   FileScanner receives event, pauses scanning IMMEDIATELY  
# T+20ms:   JobProcessor receives event, stops processing new files
# T+25ms:   WebSocket handler receives event, notifies UI
# T+30ms:   Total system coordination complete

# Vs. current approach:
# T+0ms:    FileCopyExecutor error, file marked FAILED
# T+30000ms: StorageMonitor discovers network down (30s later!)
# Result: 30 seconds of continued scanning and queue flooding
```

### **Rollback Safety:**
```python
# Event bus kan slås fra øjeblikkeligt:
class StateManager:
    def __init__(self, event_bus: Optional[DomainEventBus] = None):
        self._event_bus = event_bus
        self._event_publishing_enabled = True  # Feature flag
    
    async def add_file(self, file_path: str, file_size: int) -> TrackedFile:
        # Existing logic unchanged...
        
        # Event publishing med rollback safety:
        if self._event_bus and self._event_publishing_enabled:
            try:
                await self._event_bus.publish(FileDiscoveredEvent(...))
            except Exception as e:
                logging.error(f"Event publishing failed: {e}")
                # System continues without events
```

---

## ⚠️ **Critical Success Factors**

### **1. Incremental Testing:**
```python
# Test hver fase isoleret:
# Phase 1: Event bus functionality
# Phase 2: Parallel event flow with existing pub/sub  
# Phase 3: Event-driven service communication
# Phase 4: StateManager slice functionality
```

### **2. Feature Flags:**
```python
# Enablement controls for hver fase:
ENABLE_EVENT_BUS = True
ENABLE_EVENT_DRIVEN_SCANNER = False  
ENABLE_STATEMANAGER_SLICES = False
```

### **3. Monitoring:**
```python
# Event flow logging for debugging:
class DomainEventBus:
    async def publish(self, event: DomainEvent):
        logging.info(f"Publishing {type(event).__name__}: {event.event_id}")
        # ... publish logic
        logging.info(f"Published to {len(handlers)} handlers")
```

---

## 🎉 **Expected Outcomes**

### **Efter Week 4 (Event Infrastructure):**
- ✅ Løs kobling infrastructure etableret
- ✅ StateManager publishes events parallelt med pub/sub
- ✅ Zero breaking changes til eksisterende system

### **Efter Week 9 (Service Decoupling):**
- ✅ Sub-second network failure response (vs. 30 second current)
- ✅ Event-driven scanner pause/resume
- ✅ Real-time WebSocket updates via events
- ✅ Decoupled presentation layer

### **Efter Week 15 (StateManager Slices):**
- ✅ SOLID compliance - No god objects
- ✅ 5 focused slices vs. 1 monolithic class
- ✅ Testability - Slice-level unit testing
- ✅ Maintainability - Clear domain boundaries

---

## 📝 **Daily Implementation Checklist**

### **Week 1 Tasks:**
```
Day 1: ✅ Create app/core/events/ structure
Day 2: ✅ Implement DomainEventBus with subscription logic
Day 3: ✅ Define core file events (Discovered, StatusChanged, Ready)
Day 4: ✅ Unit test event bus functionality
Day 5: ✅ Integration test: Event publishing without breaking existing
```

### **Week 2 Tasks:**
```
Day 1: ✅ Add optional event_bus parameter to StateManager
Day 2: ✅ Implement event publishing in add_file()
Day 3: ✅ Implement event publishing in update_file_status_by_id()
Day 4: ✅ Test parallel operation: events + existing pub/sub
Day 5: ✅ Update dependency injection to wire event bus
```

### **Ready to Proceed Criteria:**
```
✅ Event bus publishes events reliably
✅ StateManager operates normally with AND without event bus
✅ No performance degradation in existing functionality  
✅ Rollback procedure tested and working
✅ All existing tests still pass
```

---

## 🎯 **Bundlinie**

**Du har nu en komplet, risk-mitigated handlingsplan!**

**Key Points:**
1. **Event Bus FØRST** - Zero breaking changes
2. **StateManager SIDST** - Når alle andre bruger events  
3. **90% code reuse** - Det er reorganization, ikke rewrite
4. **Incremental rollbacks** - Safety på hver fase
5. **Real-world benefits** - Sub-second network failure response

**Start med Week 1, Day 1: Create app/core/events/ structure** 🚀

**Event Bus = Foundation for maintainable, loosely-coupled architecture!**