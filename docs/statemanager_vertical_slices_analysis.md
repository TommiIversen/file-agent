# StateManager Vertical Slices Analysis
*Tynd Core vs. Vertical Slices Approach*

## 🔍 **StateManager Ansvar Analyse (715 linjer)**

Efter at have gennemgået StateManager's faktiske kode, kan den opdeles i **6 store ansvarområder:**

### **📊 Current StateManager Responsibilities:**

**1. Core Repository (Data Storage) - ~150 linjer**
```python
# Basic CRUD operations:
- _files_by_id: Dict[str, TrackedFile]      # Core storage
- add_file() 
- get_file_by_id()
- update_file_status_by_id()
```

**2. Query & Filtering Engine - ~200 linjer** 
```python
# Complex filtering logic:
- get_active_file_by_path()                 # Active file prioritization  
- get_all_files_for_path()                  # Path-based queries
- _get_current_file_for_path()              # Priority-based selection
- get_statistics()                          # Aggregation queries
```

**3. Business Logic Engine - ~150 linjer**
```python
# Domain-specific logic:
- should_skip_file_processing()             # Cooldown logic

- _is_more_current()                        # Priority logic
- _is_space_error_in_cooldown()            # Space error logic
```

**4. Retry Coordination - ~120 linjer**
```python
# Retry management:
- schedule_retry()                          # Retry scheduling
- cancel_retry()                            # Retry cancellation
- _execute_retry_task()                     # Retry execution
- increment_retry_count()                   # Retry tracking
- cancel_all_retries()                      # Batch operations
```

**5. Pub/Sub Event System - ~50 linjer**
```python
# Event coordination:
- subscribe()                               # Subscriber management
- unsubscribe()                            # Subscriber removal
- _notify()                                # Event publishing
```

**6. Data Cleanup & Maintenance - ~80 linjer**
```python
# Housekeeping operations:
- cleanup_missing_files()                   # File removal
- cleanup_old_files()                       # Age-based cleanup
```

---

## 🎯 **Vertical Slices vs. Tynd Core Anbefaling**

### **✅ ANBEFALING: Vertical Slices Approach**

**Hvorfor IKKE tynd core:**

**Problem med tynd FileRepository core:**
```python
# Tynd core ville tvinge business logic UD i consumers:
class FileRepository:  # Tynd core
    async def get_files(self) -> List[TrackedFile]: pass
    async def add_file(self, file: TrackedFile): pass

# Result: Complex filtering logic spredes OVERALT:
class FileScannerService:
    async def get_ready_files(self):
        all_files = await self.repo.get_files()
        # ⚠️ Duplicated filtering logic in EVERY consumer!
        return [f for f in all_files if f.status == READY and not self._in_cooldown(f)]

class JobProcessor:  
    async def get_ready_files(self):
        all_files = await self.repo.get_files()
        # ⚠️ SAME filtering logic duplicated again!
        return [f for f in all_files if f.status == READY and not self._in_cooldown(f)]
```

**Problem = Duplicated business logic overalt!**

---

## 🏗️ **Vertical Slices Architecture**

### **Anbefalet Struktur:**

```
app/core/file_management/
├── repository/
│   ├── file_repository.py           # Core storage (tynd)
│   └── file_queries.py             # Query optimization
├── slices/
│   ├── file_discovery_slice.py     # Scanner concerns  
│   ├── file_processing_slice.py    # Job processing concerns
│   ├── file_retry_slice.py         # Retry concerns
│   ├── file_monitoring_slice.py    # Statistics & monitoring
│   └── file_lifecycle_slice.py     # Cleanup & maintenance
└── shared/
    ├── file_prioritization.py      # Shared priority logic
    └── file_cooldown.py            # Shared cooldown logic
```

### **Vertical Slice Eksempel:**

```python
# file_discovery_slice.py - Alt hvad FileScannerService skal bruge
class FileDiscoverySlice:
    def __init__(self, repository: FileRepository, event_bus: EventBus):
        self._repository = repository
        self._event_bus = event_bus
    
    async def get_active_file_by_path(self, file_path: str) -> Optional[TrackedFile]:
        """Scanner-specific file lookup with active status filtering"""
        # Encapsulates complex active status logic
        pass
    
    async def should_skip_file_processing(self, file_path: str) -> bool:
        """Scanner-specific skip logic with cooldown"""
        # Encapsulates cooldown and skip logic
        pass
    

```

**Fordele:**
- ✅ **Enkapsulering** - Business logic holdes sammen med use case
- ✅ **No Duplication** - Complex filtering logic defineres ÉT sted
- ✅ **Testability** - Hver slice kan testes isoleret  
- ✅ **SRP Compliance** - Hver slice har ét ansvar
- ✅ **Easy Migration** - Slices kan refactores incrementally

---

## 📋 **Migration Strategy**

### **Fase 1: Core Repository Extraction**
```python
# Tynd core repository (kun data operations):
class FileRepository:
    async def get_by_id(self, file_id: str) -> Optional[TrackedFile]: pass
    async def get_all(self) -> List[TrackedFile]: pass
    async def add(self, file: TrackedFile) -> TrackedFile: pass  
    async def update(self, file: TrackedFile) -> TrackedFile: pass
    async def remove(self, file_id: str) -> bool: pass
```

### **Fase 2: Extract First Vertical Slice**
```python
# Start med FileScannerService's behov:
class FileDiscoverySlice:
    # Flyt alle scanner-relevante metoder fra StateManager
    - get_active_file_by_path()
    - should_skip_file_processing()  
```

### **Fase 3: Extract Remaining Slices**
```python
# Extract andre slices gradvist:
FileProcessingSlice    # JobProcessor needs
FileRetrySlice        # SpaceRetryManager needs  
FileMonitoringSlice   # WebSocket/API needs
FileLifecycleSlice    # Cleanup operations
```

### **Fase 4: Event Integration**
```python
# Add event publishing til hver slice:
class FileDiscoverySlice:
    async def mark_file_ready(self, file_id: str):
        file = await self._repository.update_status(file_id, READY)
        await self._event_bus.publish(FileReadyEvent(file))
```

---

## 🎯 **Konkret Anbefaling**

**JA til Vertical Slices! NEJ til tynd core!**

**Problemet med StateManager er IKKE at den har for mange metoder** - problemet er at den har **for mange forskellige ansvar i samme klasse**.

**Løsning:**
1. **Behold kompleks business logic** (filtering, prioritization, cooldown)
2. **Men opdel efter use cases** (discovery, processing, retry, monitoring)  
3. **Delt repository core** for data operations
4. **Hver slice ejer sit domæne** med complete business logic

**Result:**
- ✅ SRP compliance (hver slice = ét ansvar)
- ✅ No duplicated logic (business logic stays encapsulated)
- ✅ Testable (slice-level testing)
- ✅ Maintainable (domain boundaries)

**StateManager → 5 Vertical Slices = Clean Architecture! 🎯**