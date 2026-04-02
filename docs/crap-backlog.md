# CRAP Factor Backlog — Funktioner over threshold 30

> **CRAP(m) = comp² × (1 − cov/100)³ + comp**
>
> Fix enten ved at reducere complexity (CC), øge test coverage, eller begge dele.

| # | CRAP | CC | Cov% | Fil | Funktion | Strategi |
|---|-----:|---:|-----:|-----|----------|----------|
| 1 | 210.0 | 14 | 0% | `app/main.py` | `lifespan` | Split i helper-funktioner + test |
| 2 | ~~83.8~~ ✅ | 9 | 3→~40% | `app/domains/network_mount/macos_mounter.py` | `MacOSMounter.attempt_mount` | Tests tilføjet + bug fixet |
| 3 | ~~64.6~~ ✅ | 8→6 | 4→100% | `app/domains/network_mount/macos_mount_utils.py` | `MacOSNetworkChecker.is_network_available` | Extracted `_extract_hostname` + 11 tests |
| 4 | ~~50.1~~ ✅ | 7→5 | 4→100% | `app/domains/network_mount/windows_mounter.py` | `WindowsMounter.verify_mount_accessible` | Replaced shell injection with `os.listdir` + `asyncio.to_thread` + 6 tests |
| 5 | ~~47.9~~ ✅ | 7→2 | 6→100% | `app/domains/network_mount/macos_mount_utils.py` | `MacOSMountValidator.find_ghost_mounts` | Extracted `_find_ghost_dirs` sync helper + 8 tests |
| 6 | ~~46.2~~ ✅ | 7 | 7→100% | `app/domains/network_mount/mount_service.py` | `NetworkMountService.ensure_mount_available` | 9 tests dækker alle branches |
| 7 | ~~37.1~~ ✅ | 6 | 5→100% | `app/domains/network_mount/windows_mounter.py` | `WindowsMounter.attempt_mount` | 5 tests dækker alle branches |
