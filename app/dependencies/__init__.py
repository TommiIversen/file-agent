"""
Dependency injection / Composition Root.

Re-exports all factory functions for backward compatibility.
Actual implementations are split across submodules.
"""

# === Core factories (re-exported) ===
from app.dependencies.core import (  # noqa: F401
    _singletons,
    get_settings,
    get_command_bus,
    get_query_bus,
    get_event_bus,
    get_file_repository,
    get_file_state_machine,
    get_global_event_logger,
    get_event_store,
    reset_singletons,
)

# === Storage & network factories (re-exported) ===
from app.dependencies.storage import (  # noqa: F401
    get_storage_checker,
    get_network_mount_service,
    get_network_coordinator,
    register_network_coordinator,
    get_storage_monitor,
)

# === File processing & discovery factories (re-exported) ===
from app.dependencies.file_processing import (  # noqa: F401
    get_file_discovery_slice,
    get_file_scanner,
    get_job_queue_service,
    get_file_copier,
    get_space_checker,
    get_space_retry_manager,
    get_job_finalization_service,
    get_job_copy_executor,
    get_job_space_manager,
    get_job_error_classifier,
    get_copy_strategy,
    get_file_verification_service,
    get_copy_io_loop,
    get_job_queue,
)

# === Domain service factories (re-exported) ===
from app.dependencies.services import (  # noqa: F401
    get_websocket_manager,
    get_directory_scanner,
    get_presentation_event_handlers,
    get_lifecycle_service,
    get_tally_light_event_handler,
    get_tally_switch_monitor,
    get_ingest_state_service,
    get_ingest_api_client,
    get_ingest_monitor_worker,
)

