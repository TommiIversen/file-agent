"""
File operations utilities for File Transfer Agent.

Pure functions for path resolution, conflict resolution, and file validation.
These functions have no side effects and are easily testable.

Part of Fase 1.1 refactoring: Extract Pure Functions from FileCopyService.
"""

from pathlib import Path


def calculate_relative_path(source_path: Path, source_base: Path) -> Path:
    """
    Calculate relative path from source base directory.
    
    Pure function that determines the relative path structure
    to preserve directory hierarchy in destination.
    
    Args:
        source_path: The file path to calculate relative path for
        source_base: The base source directory
        
    Returns:
        Relative path from source_base, or just filename if source_path
        is not under source_base
        
    Examples:
        >>> calculate_relative_path(Path("/src/video.mxf"), Path("/src"))
        Path("video.mxf")
        >>> calculate_relative_path(Path("/src/folder/video.mxf"), Path("/src"))
        Path("folder/video.mxf")
        >>> calculate_relative_path(Path("/other/video.mxf"), Path("/src"))
        Path("video.mxf")
    """
    try:
        return source_path.relative_to(source_base)
    except ValueError:
        # Source is not under source directory - use just filename
        return Path(source_path.name)


def generate_conflict_free_path(dest_path: Path) -> Path:
    """
    Generate a conflict-free path by adding _1, _2, etc. suffixes.
    
    Pure function that resolves naming conflicts without filesystem access.
    Tests for existence using Path.exists() which is deterministic.
    Properly handles complex extensions like .tar.gz.
    
    Args:
        dest_path: The destination path that may have conflicts
        
    Returns:
        A path that doesn't exist (with _N suffix if needed)
        
    Raises:
        RuntimeError: If more than 9999 conflicts are encountered
        
    Examples:
        >>> # If /dest/video.mxf exists:
        >>> generate_conflict_free_path(Path("/dest/video.mxf"))
        Path("/dest/video_1.mxf")
        >>> # If both video.mxf and video_1.mxf exist:
        >>> generate_conflict_free_path(Path("/dest/video.mxf"))  
        Path("/dest/video_2.mxf")
        >>> # Handles complex extensions:
        >>> generate_conflict_free_path(Path("/dest/archive.tar.gz"))
        Path("/dest/archive_1.tar.gz")
    """
    if not dest_path.exists():
        return dest_path
    
    # Handle complex extensions like .tar.gz properly
    name = dest_path.name
    parent = dest_path.parent
    
    # Find the first dot to separate base name from all extensions
    if '.' in name:
        base_name, extensions = name.split('.', 1)
        extensions = '.' + extensions
    else:
        base_name = name
        extensions = ''
    
    counter = 1
    while True:
        new_name = f"{base_name}_{counter}{extensions}"
        new_path = parent / new_name
        
        if not new_path.exists():
            return new_path
            
        counter += 1
        
        # Safety check - avoid infinite loop
        if counter > 9999:
            raise RuntimeError(f"Could not resolve name conflict after 9999 attempts: {dest_path}")


def validate_file_sizes(source_size: int, dest_size: int) -> bool:
    """
    Validate that source and destination file sizes match.
    
    Pure function for verifying successful file copy.
    
    Args:
        source_size: Size of source file in bytes
        dest_size: Size of destination file in bytes
        
    Returns:
        True if sizes match, False otherwise
        
    Examples:
        >>> validate_file_sizes(1024, 1024)
        True
        >>> validate_file_sizes(1024, 1023)
        False
    """
    return source_size == dest_size


def create_temp_file_path(dest_path: Path) -> Path:
    """
    Create temporary file path by adding .tmp suffix.
    
    Pure function that generates temporary file paths for safe copying.
    
    Args:
        dest_path: The final destination path
        
    Returns:
        Path with .tmp suffix added
        
    Examples:
        >>> create_temp_file_path(Path("/dest/video.mxf"))
        Path("/dest/video.mxf.tmp")
        >>> create_temp_file_path(Path("/dest/file.tar.gz"))
        Path("/dest/file.tar.gz.tmp")
    """
    return dest_path.with_suffix(dest_path.suffix + ".tmp")


def build_destination_path(source_path: Path, source_base: Path, dest_base: Path) -> Path:
    """
    Build complete destination path preserving directory structure.
    
    Combines relative path calculation and destination base to create
    the full destination path while preserving directory hierarchy.
    
    Args:
        source_path: The source file path
        source_base: The source base directory
        dest_base: The destination base directory
        
    Returns:
        Complete destination path preserving relative structure
        
    Examples:
        >>> build_destination_path(
        ...     Path("/src/folder/video.mxf"), 
        ...     Path("/src"), 
        ...     Path("/dest")
        ... )
        Path("/dest/folder/video.mxf")
    """
    relative_path = calculate_relative_path(source_path, source_base)
    return dest_base / relative_path


def build_destination_path_with_template(
    source_path: Path, 
    source_base: Path, 
    dest_base: Path,
    template_engine=None
) -> Path:
    """
    Build destination path with optional template engine support.
    
    If template engine is provided and enabled, uses template-based folder organization.
    Otherwise falls back to preserving original directory structure.
    
    Args:
        source_path: The source file path
        source_base: The source base directory  
        dest_base: The destination base directory
        template_engine: Optional OutputFolderTemplateEngine instance
        
    Returns:
        Complete destination path with template-based or standard organization
        
    Examples:
        # Without template (preserves structure):
        >>> build_destination_path_with_template(
        ...     Path("/src/folder/video.mxf"), 
        ...     Path("/src"), 
        ...     Path("/dest")
        ... )
        Path("/dest/folder/video.mxf")
        
        # With template (organized by rules):
        >>> build_destination_path_with_template(
        ...     Path("/src/200305_1344_Ingest_Cam1.mxf"), 
        ...     Path("/src"), 
        ...     Path("/dest"),
        ...     template_engine
        ... )
        Path("/dest/KAMERA/200305/200305_1344_Ingest_Cam1.mxf")
    """
    filename = source_path.name
    
    # Use template engine if available and enabled
    if template_engine and template_engine.is_enabled():
        return Path(template_engine.generate_output_path(filename))
    
    # Fall back to standard path preservation
    return build_destination_path(source_path, source_base, dest_base)


def resolve_destination_with_conflicts(source_path: Path, source_base: Path, dest_base: Path) -> Path:
    """
    Resolve complete destination path including conflict resolution.
    
    High-level pure function that combines path building and conflict resolution.
    This is the main function that replaces FileCopyService._resolve_destination_path.
    
    Args:
        source_path: The source file path
        source_base: The source base directory  
        dest_base: The destination base directory
        
    Returns:
        Conflict-free destination path
        
    Examples:
        >>> resolve_destination_with_conflicts(
        ...     Path("/src/video.mxf"),
        ...     Path("/src"),
        ...     Path("/dest")
        ... )
        Path("/dest/video.mxf")  # or "/dest/video_1.mxf" if conflict exists
    """
    initial_dest = build_destination_path(source_path, source_base, dest_base)
    return generate_conflict_free_path(initial_dest)


# Validation functions for error checking

def validate_source_file(source_path: Path) -> None:
    """
    Validate that source file exists and is a regular file.
    
    Args:
        source_path: Path to validate
        
    Raises:
        FileNotFoundError: If source file doesn't exist
        ValueError: If source path is not a regular file
    """
    if not source_path.exists():
        raise FileNotFoundError(f"Source file does not exist: {source_path}")
    
    if not source_path.is_file():
        raise ValueError(f"Source path is not a regular file: {source_path}")


def validate_file_copy_integrity(source_path: Path, dest_path: Path) -> None:
    """
    Validate file copy integrity by comparing file sizes.
    
    Args:
        source_path: Source file path
        dest_path: Destination file path
        
    Raises:
        ValueError: If file sizes don't match
    """
    source_size = source_path.stat().st_size
    dest_size = dest_path.stat().st_size
    
    if not validate_file_sizes(source_size, dest_size):
        raise ValueError(
            f"File size mismatch: source={source_size}, dest={dest_size}"
        )