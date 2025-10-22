# Network Recovery Refactoring Roadmap

## Overview
Transition from complex bitwise resume strategy to simple "fail-and-rediscover" approach for network interruption handling.

## Current Problems
- [ ] Bitwise resume complexity with UUID mismatches
- [ ] Copy strategies pause/resume logic is error-prone
- [ ] App cannot start offline without space/network errors
- [ ] Growing copy creates duplicate _1 files incorrectly
- [ ] Users cannot see pending files during network outage

## Target Architecture: "Fail-and-Rediscover"

### Core Strategy
1. **Network Failure:** GROWING_COPY → FAILED (immediate clean failure)
2. **Re-Discovery:** Scanner finds file again → New TrackedFile (fresh UUID)
3. **Conflict Resolution:** _1 naming indicates recovery file
4. **Queue Awareness:** READY files wait for network before entering queue
5. **Recovery Trigger:** Storage monitor activates READY files when network returns

## Implementation Phases

### Phase 1: Foundation & Offline Startup Fix ⭐ PRIORITY
- [x] **Task:** Ensure app can start offline without errors
- [x] **Issue:** Files in input folder cause space/network errors on startup
- [x] **Solution:** 
  - [x] Added WAITING_FOR_NETWORK status to models
  - [x] Made directory creation async with 5s timeout 
  - [x] Modified job space manager to use WAITING_FOR_NETWORK for "not accessible" 
  - [x] Added network awareness to JobQueue (files stay as WAITING_FOR_NETWORK if offline)
  - [x] Added process_waiting_network_files() method for recovery
  - [x] Integrated with storage monitor recovery flow
- [ ] **Test:** Start app with files in input folder while network is down

### Phase 2: Remove Complex Resume Logic ✅ COMPLETED
- [x] **Remove from job_queue.py:**
  - [x] `_resume_paused_file()` method
  - [x] PAUSED_GROWING_COPY special handling
  - [x] Intelligent resume process logic
- [x] **Remove from copy_strategies.py:**
  - [x] Pause detection during copy loops
  - [x] Resume from existing progress logic
  - [x] Status checking with wait states
  - [x] Append mode ("ab") file opening logic
  - [x] Seek operations for resume functionality
- [x] **Remove from job_file_preparation_service.py:**
  - [x] `_is_resume_scenario()` method
  - [x] Conflict resolution skipping for resume
- [x] **Remove from resumable_copy_strategies.py:**
  - [x] Network recovery resume forcing
  - [x] Append mode file opening logic
  - [x] **DELETED ENTIRE FILE** + related files (secure_resume_*.py, resume_integration.py)
- [x] **Remove from space_retry_manager.py:**
  - [x] `_is_file_paused()` method
  - [x] `_schedule_paused_file_retry()` method

### Phase 3: Implement Fail-on-Network-Error
- [ ] **Modify copy strategies:**
  - [ ] Detect network errors (destination unreachable)
  - [ ] Immediately set status to FAILED
  - [ ] Add error_message = "network_interruption"
  - [ ] Clean exit from copy process
- [ ] **No pause logic:** Just clean failure

### Phase 4: Network-Aware JobQueue
- [ ] **Add network status checking to JobQueue**
- [ ] **Modify _handle_state_change():**
  ```python
  if new_status == FileStatus.READY:
      if network_is_available():
          await self._add_job_to_queue(tracked_file)
      else:
          # Keep as READY, don't queue
  ```
- [ ] **READY files visible in UI but not processed**

### Phase 5: Storage Monitor Recovery Trigger
- [ ] **Add to storage monitor:**
  - [ ] Detect when network comes back online
  - [ ] Trigger processing of all READY files
  - [ ] `await self.job_queue.process_ready_files()`
- [ ] **Automatic recovery without user intervention**

### Phase 6: UI Enhancement for Recovery Files
- [ ] **Show both original and recovery files:**
  ```
  video1.mxf [FAILED] ❌ Network error at 45%
  video1_1.mxf [READY] ⏳ Waiting for network
  ```
- [ ] **Clear indication of recovery status**
- [ ] **Optional: Hide FAILED files when recovery file exists**

### Phase 7: Test Updates
- [ ] **Update existing tests:**
  - [ ] test_growing_copy_recovery.py
  - [ ] test_network_interruption_recovery.py
  - [ ] test_paused_file_*.py tests
- [ ] **Remove pause/resume test scenarios**
- [ ] **Add fail-and-rediscover test scenarios**
- [ ] **Test offline startup scenarios**

### Phase 8: Full Testing & Validation
- [ ] **Run pytest - all tests must pass**
- [ ] **End-to-end network interruption testing**
- [ ] **Offline startup testing**
- [ ] **Performance validation**

## Key Benefits After Implementation
✅ **Simplicity:** No complex pause/resume state management  
✅ **Reliability:** Fresh copies eliminate UUID/state conflicts  
✅ **User Clarity:** _1 files clearly indicate recovery  
✅ **Offline Support:** App starts cleanly without network  
✅ **Immediate Visibility:** Users see pending files instantly  

## Implementation Notes

### File Naming Strategy
- Original: `video.mxf` → FAILED
- Recovery: `video_1.mxf` → Fresh copy with conflict resolution
- User understands _1 = recovered file

### Network Detection
- Use existing storage checker logic
- Destination unreachable = network down
- Destination accessible = network up

### State Transitions
```
Network Error Flow:
GROWING_COPY → FAILED (network_interruption)
Scanner → DISCOVERED → READY (waiting for network)
Network Recovery → READY → IN_QUEUE → COPYING
```

## Testing Strategy
1. **Unit Tests:** Individual component behavior
2. **Integration Tests:** Full flow testing
3. **Scenario Tests:** Real network interruption simulation
4. **Offline Tests:** App startup without network

## Success Criteria
- [ ] App starts cleanly offline with files in input folder
- [ ] Network interruptions cause clean failures (no crashes)
- [ ] Recovery files appear immediately with _1 naming
- [ ] Network recovery automatically processes pending files
- [ ] All existing pytest tests pass
- [ ] No UUID mismatch errors
- [ ] No infinite loops or stuck processes

---

**Status:** 🚧 In Progress  
**Priority:** ⭐ High - Critical for production reliability  
**Estimated Effort:** 2-3 days for complete implementation  