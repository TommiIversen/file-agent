# Vulture whitelist for legitimate unused code
# This file contains code that vulture flags as unused but is actually needed

# Pydantic validators require 'cls' parameter even when not used
cls  # Used in @classmethod validators