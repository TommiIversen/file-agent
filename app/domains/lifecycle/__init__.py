"""
Lifecycle Domain - Responsible for managing the lifecycle of tracked files.

This domain handles periodic cleanup operations to prevent the in-memory
FileRepository from growing indefinitely. It manages old, terminal files
that are no longer actively being processed.
"""