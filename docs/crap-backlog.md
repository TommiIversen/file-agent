# CRAP Factor Backlog — Funktioner over threshold 30

> **CRAP(m) = comp² × (1 − cov/100)³ + comp**
>
> Fix enten ved at reducere complexity (CC), øge test coverage, eller begge dele.

| # | CRAP | CC | Cov% | Fil | Funktion | Strategi |
|---|-----:|---:|-----:|-----|----------|----------|
| 1 | 210.0 | 14 | 0% | `app/main.py` | `lifespan` | Split i helper-funktioner + test |
| 2 | 100.0 | 10 | 3% | `app/domains/ingest_monitor/worker.py` | `IngestMonitorWorker._slow_polling_loop` | Reducer CC + øg coverage |
| 3 | 83.8 | 9 | 3% | `app/domains/network_mount/macos_mounter.py` | `MacOSMounter.attempt_mount` | Split + test |
| 4 | 64.6 | 8 | 4% | `app/domains/network_mount/macos_mount_utils.py` | `MacOSNetworkChecker.is_network_available` | Split + test |
| 5 | 50.1 | 7 | 4% | `app/domains/network_mount/windows_mounter.py` | `WindowsMounter.verify_mount_accessible` | Split + test |
| 6 | 47.9 | 7 | 6% | `app/domains/network_mount/macos_mount_utils.py` | `MacOSMountValidator.find_ghost_mounts` | Split + test |
| 7 | 46.2 | 7 | 7% | `app/domains/network_mount/mount_service.py` | `NetworkMountService.ensure_mount_available` | Split + test |
| 8 | 37.1 | 6 | 5% | `app/domains/network_mount/windows_mounter.py` | `WindowsMounter.attempt_mount` | Split + test |
