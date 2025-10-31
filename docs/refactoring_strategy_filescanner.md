# Refactoring Strategy Guide: FileScannerService Domain Extraction

## TL;DR - Start Strategy 🎯

**Anbefaling: Start med Domain Event Bus (Mediator pattern)**

Ikke FileScanner først - det vil skabe kaos! Start med fundamentet først, så domænerne kan kommunikere løst koblet.

## Detaljeret Analyse af Tilgange

### **🚨 Hvorfor IKKE starte med FileScanner?**

**StateManager har 13+ direkter dependencies:**
```python
# StateManager bruges OVERALT i systemet:
- FileScannerService → StateManager      # File discovery
- WebSocketManager → StateManager        # Real-time UI updates  
- JobQueueService → StateManager         # Job coordination
- SpaceRetryManager → StateManager       # Retry logic
- JobProcessor → StateManager            # Job execution
- GrowingFileDetector → StateManager     # File growth tracking
- FileCopierService → StateManager       # Copy coordination
- API endpoints → StateManager           # REST API data
- WebSocket handlers → StateManager      # Live updates
- Test suites → StateManager             # 324 test linjer!

# FileScanner har 15+ direkte StateManager kald:
await self.state_manager.add_file(...)
await self.state_manager.update_file_status_by_id(...)  
await self.state_manager.is_file_stable(...)
# ... og mange flere
```

**Problem:** Hvis du starter med StateManager refactoring først, skal du samtidig opdatere:
- **13+ service dependencies** der bruger StateManager
- **324 linjer test kode** der tester StateManager
- **Alle pub/sub subscribers** (WebSocketManager etc.)
- **Dependency injection** i dependencies.py
- **API endpoints** der kalder StateManager direkte

Det bliver en **MEGA Big Bang refactoring** = ekstrem højrisiko!

---

## 🎯 **DEFINITIV: Event Bus Først! StateManager Sidst!**

Efter dependency-analyse er svaret **krystalklart:**

### **📊 StateManager Dependency Count:**
- **13+ services** bruger StateManager direkte
- **324 linjer** test kode afhænger af StateManager  
- **Pub/Sub system** med WebSocket subscribers
- **API endpoints** kalder StateManager direkte
- **Dependency injection** i dependencies.py

**StateManager refactoring = Breaking change for HELE systemet!**

### **✅ Event Bus Infrastructure Tilgang:**

**Fordele med Event Bus først:**
- ✅ **Zero Breaking Changes** - Events tilføjes parallelt
- ✅ **Gradual Migration** - StateManager beholder sin interface
- ✅ **Risk Mitigation** - Kan rulles tilbage øjeblikkeligt
- ✅ **Test Parallel** - Ny events kan testes uden at påvirke eksisterende
- ✅ **Service Independence** - Andre services behøver ikke ændres

### **Fase 1: Event Infrastructure (1-2 dage)**

**Skab fundamentet for løs kobling:**

```python
# 1. Event Bus (= Mediator pattern, ja!)
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

# 2. Base Domain Events
@dataclass
class FileDiscoveredEvent(DomainEvent):
    file_path: str
    file_size: int
    timestamp: datetime

@dataclass  
class FileStableEvent(DomainEvent):
    file_id: str
    file_path: str
    
@dataclass
class FileStatusChangedEvent(DomainEvent):
    file_id: str
    old_status: FileStatus
    new_status: FileStatus
```

**Fordele:**
- ✅ Kan implementeres parallelt med eksisterende kod
- ✅ Ingen breaking changes
- ✅ Starter loose coupling mønster

### **Fase 2: StateManager Event Integration (2-3 dage)**

**Gradvis integration af events i StateManager:**

```python
class StateManager:
    def __init__(self, event_bus: DomainEventBus):
        self._event_bus = event_bus
        # ... existing code
    
    async def add_file(self, file_path: str, file_size: int) -> TrackedFile:
        # Existing logic...
        tracked_file = TrackedFile(...)
        
        # NEW: Publish event
        await self._event_bus.publish(
            FileDiscoveredEvent(file_path, file_size, datetime.now())
        )
        
        return tracked_file
    
    async def update_file_status_by_id(self, file_id: str, status: FileStatus):
        old_status = self._files_by_id[file_id].status
        # Existing logic...
        
        # NEW: Publish event  
        await self._event_bus.publish(
            FileStatusChangedEvent(file_id, old_status, status)
        )
```

### **Fase 3: FileScanner Domain Extraction (3-4 dage)**

**Nu hvor events er etableret, kan FileScanner refactores:**

```python
# NY struktur:
app/
  domains/
    file_discovery/
      __init__.py
      scanner_service.py        # FileScanner logic
      growing_detector.py       # GrowingFileDetector  
      file_metadata.py         # Metadata utilities
      events.py                # Discovery events
    
    file_processing/
      __init__.py
      file_state_repository.py # StateManager → File state del
      retry_coordinator.py     # StateManager → Retry del  
      events.py               # Processing events
```

---

## 🔄 **Event Bus = Mediator Pattern? JA!**

**Event Bus ER en implementering af Mediator pattern:**

```python
# Klassisk Mediator interface:
class Mediator(ABC):
    @abstractmethod
    async def notify(self, sender: str, event: str): pass

# Event Bus = Type-safe Mediator implementation:
class DomainEventBus(Mediator):
    async def notify(self, sender: str, event: DomainEvent):
        # Type-safe event handling med subscribers
```

**Fordele ved Event Bus over simpel Mediator:**
- ✅ **Type Safety** - Events har stærke typer
- ✅ **Decoupling** - Publishers kender ikke subscribers  
- ✅ **Testability** - Events kan mockes/asserts
- ✅ **Traceability** - Event log for debugging

---

## 📋 **Definitiv Migration Roadmap:**

### **Fase 1: Event Infrastructure (Lavest Risiko)**
```
✅ Week 1-2: DomainEventBus implementation (isoleret)
✅ Week 3: StateManager gradvis event integration (additive)
✅ Week 4: Test parallel event flow (ingen breaking changes)
```

### **Fase 2: Service Decoupling (Medium Risiko)**  
```
✅ Week 5-6: Scanner domain extraction via events
✅ Week 7-8: Job processing via events
✅ Week 9: WebSocket decoupling via events
```

### **Fase 3: StateManager Split (Højest Risiko - Sidst!)**
```
⚠️ Week 10-12: StateManager refactoring (når alle andre bruger events)
⚠️ Week 13-14: Migration af sidste dependencies
⚠️ Week 15: Cleanup og final integration
```

---

## 🎯 **Konkret Næste Skridt**

**IKKE** start med FileScanner! **Start med Event Bus:**

1. **Skab `app/core/events/`** directory
2. **Implementer DomainEventBus** (50-75 linjer)
3. **Definer 3-5 core events** (FileDiscovered, FileStable, etc.)
4. **Tilføj event publishing til StateManager** (gradvis)
5. **Test event flow** fungerer parallelt med eksisterende system

**Kun når event infrastrukturen er stabil**, start FileScanner refactoring.

## ⚠️ **Risk Mitigation**

**Event Bus tilgang mindsker risiko:**
- ✅ **Incremental** - Ingen big bang changes
- ✅ **Parallel** - Gammel og ny kod kan køre sammen  
- ✅ **Rollback** - Events kan slås fra hvis problemer
- ✅ **Testable** - Event publishing kan testes isoleret

**FileScanner-first tilgang = højrisiko:**
- ❌ **Big Bang** - Mange komponenter skal ændres samtidig
- ❌ **Cascade** - StateManager dependencies skaber kædereaktion
- ❌ **Downtime** - Scanner må stoppes under refactoring

---

## � **DEFINITIV KONKLUSION**

**ALDRIG start med StateManager refactoring først!**

**StateManager = Central Hub for ALT:**
- 13+ services afhænger af det
- 324 linjer test kode 
- Pub/sub system med subscribers
- API endpoints  
- Dependency injection

**StateManager refactoring først = System nedlukning!**

### **✅ KORREKT RÆKKEFØLGE:**

1. **🟢 Event Bus først** - Zero breaking changes, parallel implementation
2. **🟡 Service decoupling** - Gradvis migration til events
3. **🔴 StateManager sidst** - Når alle andre bruger events

**Event Bus giver dig løs kobling UDEN at ødelægge noget!**

StateManager kan blive ved med at fungere mens du bygger event infrastruktur rundt om det. 

**Bottom line:** Start med infrastruktur, ikke core components! 🏗️⚡