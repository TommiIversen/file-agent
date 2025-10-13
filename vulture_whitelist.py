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
