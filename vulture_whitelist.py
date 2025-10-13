# Vulture whitelist for legitimate unused code
# This file contains code that vulture flags as unused but is actually needed

# Pydantic validators require 'cls' parameter even when not used
cls  # Used in @classmethod validators

# API endpoints - called by external systems (frontend, other services)
get_queue_status  # API endpoint in app.api.state
get_source_storage  # API endpoint in app.api.storage  
get_destination_storage  # API endpoint in app.api.storage
websocket_endpoint  # WebSocket endpoint in app.api.websockets
get_websocket_status  # API endpoint in app.api.websockets
read_settings  # API endpoint in app.routers.api
dashboard_page  # Web page endpoint in app.routers.views
health  # Health check endpoint in app.main
log_requests  # Middleware function in app.main

# Pydantic model_config - required by Pydantic but not explicitly referenced
model_config  # Used by Pydantic models

# Dependency injection functions - called by FastAPI framework
get_job_queue  # Dependency in app.dependencies
reset_singletons  # Test utility in app.dependencies

# Dataclass fields used in ProcessResult - created via constructor
retry_scheduled  # Used in job_space_manager.py
should_retry  # Used in job_processor.py and error_handler.py

# macOS specific config - platform dependent  
macos_mount_point  # macOS mount configuration

# Diagnostic and monitoring methods - kept for debugging/admin use
log_classification_decision  # Logging method in job_error_classifier.py
get_executor_config  # Config diagnostic in copy_strategy_factory.py
should_use_temp_file  # Strategy diagnostic method
get_progress_callback  # Progress monitoring method
get_factory_info  # Factory diagnostic method
get_growth_info  # File growth monitoring
requeue_job  # Job management method
wait_for_queue_empty  # Queue monitoring
peek_next_job  # Queue inspection
get_producer_status  # Producer monitoring
get_expected_mount_point  # Mount diagnostic
get_platform_info  # Platform diagnostic
is_space_check_enabled  # Space monitoring config
get_space_settings_info  # Space diagnostic
cancel_all_retries  # Retry management
get_retry_status  # Retry monitoring
get_file_count_by_status  # State statistics
get_failed_files  # Error reporting
get_failed_growing_files  # Growth error reporting
get_interrupted_copy_files  # Interruption reporting
send_system_statistics  # System monitoring
get_connection_count  # WebSocket monitoring
get_template_info  # Template diagnostic
create_strategy_for_file  # Strategy creation
create_adapted_strategy  # Strategy adaptation
get_resume_config_for_mode  # Resume config
record_operation  # Operation logging
log_summary  # Summary logging
max_verify_reasonable  # Verification config
binary_search_chunk_reasonable  # Verification config
log_config  # Config logging

# Test utilities and fixtures
event_loop  # Pytest fixture
clean_singletons  # Test cleanup
pytestmark  # Pytest marker
full_system  # Test method

# Test mock attributes - used by unittest.mock framework
side_effect  # Mock attribute
__aexit__  # Mock async context manager
SOURCE_PATH  # Test configuration constants
DESTINATION_PATH  # Test configuration constants
ENABLE_AUTO_MOUNT  # Test configuration constants
NETWORK_SHARE_URL  # Test configuration constants
NETWORK_USERNAME  # Test configuration constants
NETWORK_PASSWORD  # Test configuration constants
MOUNT_POINT_PATH  # Test configuration constants
broadcast_storage_status  # Mock WebSocket method
broadcast  # Mock WebSocket method

# Resume functionality - kept for future resume feature implementation
ResumableStrategyAdapter  # Resume integration adapter
