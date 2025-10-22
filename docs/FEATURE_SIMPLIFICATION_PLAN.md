# Feature Simplification Plan: Remove Copy Strategy Complexity
*Simplify før Refactoring - Growing File Only Strategy*

## 🎯 **Problemanalyse: Copy Strategy Kompleksitet**

**Nuværende System:**
- `NormalFileCopyStrategy` - Traditionel fil kopiering
- `GrowingFileCopyStrategy` - Kopiering under fil skrivning  
- `CopyStrategyFactory` - Vælger strategi baseret på `is_growing_file` flag
- `enable_growing_file_support` - Feature toggle i settings

**Problem:** Unødvendig kompleksitet! Growing file strategy kan håndtere ALT.

---

## ✅ **SMART TILGANG: Simplify FØRST, Refactor EFTER**

Du har helt ret! Det er **meget bedre** at simplificere funktionalitet først, før du refactorer arkitekturen.

### **Hvorfor Growing File Strategy Kan Erstatte ALT:**

```python
# Growing file strategy håndterer begge scenarios:

# Scenario 1: Normal fil (ikke under skrivning)
# → Growing detector detekterer: "File er stabil, ikke growing"  
# → GrowingFileCopyStrategy kopierer normalt (samme som normal strategy)

# Scenario 2: Growing fil (under skrivning)
# → Growing detector detekterer: "File grows stadig"
# → GrowingFileCopyStrategy kopierer i chunks med retry logic
```

**Growing strategy = Superset af normal strategy capabilities!**

---

## 📋 **Simplifikations Plan (FØR Refactoring)**

### **Phase A: Feature Removal (Week 0)**

**Step 1: Remove Strategy Selection Logic**
```python
# app/services/copy_strategies.py
class CopyStrategyFactory:
    def __init__(self, settings: Settings, state_manager: StateManager):
        self.settings = settings
        self.state_manager = state_manager
        self.file_copy_executor = FileCopyExecutor(settings)
        
        # SIMPLIFIED: Only one strategy
        self.copy_strategy = GrowingFileCopyStrategy(
            settings, state_manager, self.file_copy_executor
        )

    def get_strategy(self, tracked_file: TrackedFile) -> FileCopyStrategy:
        # SIMPLIFIED: Always return growing strategy
        return self.copy_strategy
        
    # Remove: get_available_strategies() - no longer needed
```

**Step 2: Remove Normal Strategy Class**
```python
# DELETE ENTIRE CLASS: NormalFileCopyStrategy
# Keep only: GrowingFileCopyStrategy
```

**Step 3: Remove Feature Toggle**
```python
# app/config.py
# DELETE: enable_growing_file_support: bool = False

# app/services/scanner/file_scanner.py  
# Remove condition: if config.enable_growing_file_support and settings:
# Always create: self.growing_file_detector = GrowingFileDetector(settings, state_manager)
```

**Step 4: Simplify Model**
```python
# app/models.py
# DELETE field: is_growing_file: bool = Field(default=False)
# Growing status can be determined dynamically via file stability logic
```

---

### **Step 5: Update Growing Strategy to Handle All Files**
```python
# app/services/copy_strategies.py
class GrowingFileCopyStrategy(FileCopyStrategy):
    
    def supports_file(self, tracked_file: TrackedFile) -> bool:
        # SIMPLIFIED: Supports ALL files
        return True
    
    async def copy_file(self, source_path: str, dest_path: str, tracked_file: TrackedFile) -> bool:
        """Unified copy strategy that handles both growing and stable files"""
        
        # Check if file is currently growing
        is_currently_growing = await self._is_file_currently_growing(tracked_file)
        
        if is_currently_growing:
            logging.info(f"File {source_path} is growing - using chunked copy")
            return await self._copy_growing_file(source_path, dest_path, tracked_file)
        else:
            logging.info(f"File {source_path} is stable - using standard copy")
            return await self._copy_stable_file(source_path, dest_path, tracked_file)
    
    async def _is_file_currently_growing(self, tracked_file: TrackedFile) -> bool:
        """Dynamic check if file is growing (replaces is_growing_file field)"""
        # Use existing growing file detector logic
        if hasattr(self, 'growing_file_detector'):
            status, _ = await self.growing_file_detector.check_file_growth_status(tracked_file)
            return status in [FileStatus.GROWING, FileStatus.READY_TO_START_GROWING]
        return False
    
    async def _copy_stable_file(self, source_path: str, dest_path: str, tracked_file: TrackedFile) -> bool:
        """Standard copy for stable files (former NormalFileCopyStrategy logic)"""
        # Use existing file_copy_executor - same as normal strategy
        copy_result = await self.file_copy_executor.copy_file(
            source=Path(source_path), 
            dest=Path(dest_path), 
            progress_callback=self._progress_callback
        )
        return copy_result.success
    
    async def _copy_growing_file(self, source_path: str, dest_path: str, tracked_file: TrackedFile) -> bool:
        """Chunked copy for growing files (existing growing strategy logic)"""
        # Existing growing file copy implementation
        pass
```

---

## 🎯 **Fordele ved Simplifikation FØRST**

### **1. Reducer Refactoring Surface Area**
- **Before:** Refactor 2 copy strategies + factory + feature toggles
- **After:** Refactor 1 unified strategy (50% mindre kode)

### **2. Reducer Test Complexity**  
- **Before:** Test strategy selection logic + 2 different strategies
- **After:** Test 1 strategy med 2 code paths

### **3. Ingen Functionality Loss**
- Growing strategy kan alt hvad normal strategy kan
- Bedre: Dynamisk detection i stedet for static flags

### **4. Simplere Event Bus Integration**
```python
# Efter simplifikation er event integration nemmere:
class UnifiedCopyStrategy:
    async def copy_file(self, source_path: str, dest_path: str, tracked_file: TrackedFile) -> bool:
        # Publish copy start event
        await self._event_bus.publish(FileCopyStartedEvent(tracked_file.id))
        
        # Single copy logic (no strategy selection complexity)
        result = await self._unified_copy_logic(source_path, dest_path, tracked_file)
        
        # Publish copy result event  
        if result:
            await self._event_bus.publish(FileCopyCompletedEvent(tracked_file.id))
        else:
            await self._event_bus.publish(FileCopyFailedEvent(tracked_file.id))
```

---

## 📅 **Updated Migration Timeline**

### **Week 0: Feature Simplification (NEW)**
```
Day 1-2: Remove NormalFileCopyStrategy class
Day 3-4: Update GrowingFileCopyStrategy to handle all files  
Day 5: Remove enable_growing_file_support toggle
Weekend: Test unified copy strategy works for all file types
```

### **Week 1-4: Event Bus Implementation** 
```
# Original plan unchanged, but now working with simplified copy system
```

### **Week 5-9: Service Decoupling**
```
# Easier because copy strategy complexity is already removed
```

---

## 💡 **Konkret Implementering**

### **Start med denne ændring:**

```python
# 1. Update CopyStrategyFactory til at kun returnere growing strategy:
class CopyStrategyFactory:
    def __init__(self, settings: Settings, state_manager: StateManager):
        self.unified_strategy = GrowingFileCopyStrategy(
            settings, state_manager, FileCopyExecutor(settings)
        )

    def get_strategy(self, tracked_file: TrackedFile) -> FileCopyStrategy:
        return self.unified_strategy  # Always return same strategy

# 2. Test at alle filer stadig kopieres korrekt
# 3. Når det virker, fjern NormalFileCopyStrategy class helt
```

---

## 🚨 **Risk Mitigation**

### **Feature Flag for Rollback:**
```python
# Temporary feature flag during transition:
USE_UNIFIED_COPY_STRATEGY = True

class CopyStrategyFactory:
    def get_strategy(self, tracked_file: TrackedFile) -> FileCopyStrategy:
        if USE_UNIFIED_COPY_STRATEGY:
            return self.unified_strategy
        else:
            # Old logic as fallback
            return self.normal_strategy if not tracked_file.is_growing_file else self.growing_strategy
```

---

## 🎯 **Konklusion**

**DU HAR HELT RET!** 

**Simplify først:**
1. ✅ **Remove copy strategy complexity** (Week 0)
2. ✅ **Unified growing strategy handles all files**  
3. ✅ **Remove feature toggles og unødvendige flags**
4. ✅ **Test everything still works**

**Derefter refactor:**
1. ✅ **Event bus implementation** (Week 1-4)
2. ✅ **Service decoupling** (Week 5-9) - nu nemmere!
3. ✅ **StateManager split** (Week 10-15)

**Result:** 50% mindre copy-related kode at refactore + simplere arkitektur! 

**Start med Week 0: Remove NormalFileCopyStrategy! 🚀**