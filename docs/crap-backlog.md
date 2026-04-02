# CRAP Factor Backlog — Funktioner over threshold 30

> **CRAP(m) = comp² × (1 − cov/100)³ + comp**
>
> Fix enten ved at reducere complexity (CC), øge test coverage, eller begge dele.

| # | CRAP | CC | Cov% | Fil | Funktion | Strategi |
|---|-----:|---:|-----:|-----|----------|----------|
| 1 | 210.0 | 14 | 0% | `app/main.py` | `lifespan` | Split i helper-funktioner + test |
| 2 | 100.0 | 10 | 3% | `app/domains/ingest_monitor/worker.py` | `IngestMonitorWorker._slow_polling_loop` | Reducer CC + øg coverage |
| 3 | 83.8 | 9 | 3% | `app/domains/network_mount/macos_mounter.py` | `MacOSMounter.attempt_mount` | Split + test |
| 4 | 72.0 | 8 | 0% | `app/domains/presentation/api_endpoints.py` | `get_initial_state` | Tilføj test |
| 5 | 64.6 | 8 | 4% | `app/domains/network_mount/macos_mount_utils.py` | `MacOSNetworkChecker.is_network_available` | Split + test |
| 6 | 54.6 | 21 | 58% | `app/domains/file_processing/copy/copy_io_loop.py` | `CopyIoLoop.copy_chunk_range` | Split (CC=21!) + øg coverage |
| 7 | 50.1 | 7 | 4% | `app/domains/network_mount/windows_mounter.py` | `WindowsMounter.verify_mount_accessible` | Split + test |
| 8 | 49.9 | 7 | 4% | `app/domains/ingest_monitor/worker.py` | `IngestMonitorWorker._fast_polling_loop` | Reducer CC + test |
| 9 | 47.9 | 7 | 6% | `app/domains/network_mount/macos_mount_utils.py` | `MacOSMountValidator.find_ghost_mounts` | Split + test |
| 10 | 46.2 | 7 | 7% | `app/domains/network_mount/mount_service.py` | `NetworkMountService.ensure_mount_available` | Split + test |
| 11 | 40.8 | 8 | 20% | `app/domains/ingest_monitor/worker.py` | `IngestMonitorWorker.stop_monitoring` | Reducer CC + test |
| 12 | 37.1 | 6 | 5% | `app/domains/network_mount/windows_mounter.py` | `WindowsMounter.attempt_mount` | Split + test |
| 13 | 34.1 | 24 | 74% | `app/domains/directory_browsing/service.py` | `DirectoryScannerService._perform_directory_scan` | Split (CC=24!) |
