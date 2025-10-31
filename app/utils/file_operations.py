from pathlib import Path


def calculate_relative_path(source_path: Path, source_base: Path) -> Path:
    try:
        return source_path.relative_to(source_base)
    except ValueError:
        # Source is not under source directory - use just filename
        return Path(source_path.name)


def generate_conflict_free_path(dest_path: Path) -> Path:
    if not dest_path.exists():
        return dest_path

    # Handle complex extensions like .tar.gz properly
    name = dest_path.name
    parent = dest_path.parent

    # Find the first dot to separate base name from all extensions
    if "." in name:
        base_name, extensions = name.split(".", 1)
        extensions = "." + extensions
    else:
        base_name = name
        extensions = ""

    counter = 1
    while True:
        new_name = f"{base_name}_{counter}{extensions}"
        new_path = parent / new_name

        if not new_path.exists():
            return new_path

        counter += 1

        # Safety check - avoid infinite loop
        if counter > 9999:
            raise RuntimeError(
                f"Could not resolve name conflict after 9999 attempts: {dest_path}"
            )


def validate_file_sizes(source_size: int, dest_size: int) -> bool:
    return source_size == dest_size


def create_temp_file_path(dest_path: Path) -> Path:
    return dest_path.with_suffix(dest_path.suffix + ".tmp")


def build_destination_path(
    source_path: Path, source_base: Path, dest_base: Path
) -> Path:
    relative_path = calculate_relative_path(source_path, source_base)
    return dest_base / relative_path


def build_destination_path_with_template(
    source_path: Path, source_base: Path, dest_base: Path, template_engine=None
) -> Path:
    filename = source_path.name

    # Use template engine if available and enabled
    if template_engine and template_engine.is_enabled():
        return Path(template_engine.generate_output_path(filename))

    # Fall back to standard path preservation
    return build_destination_path(source_path, source_base, dest_base)


def resolve_destination_with_conflicts(
    source_path: Path, source_base: Path, dest_base: Path
) -> Path:
    initial_dest = build_destination_path(source_path, source_base, dest_base)
    return generate_conflict_free_path(initial_dest)


def validate_source_file(source_path: Path) -> None:
    if not source_path.exists():
        raise FileNotFoundError(f"Source file does not exist: {source_path}")

    if not source_path.is_file():
        raise ValueError(f"Source path is not a regular file: {source_path}")


def validate_file_copy_integrity(source_path: Path, dest_path: Path) -> None:
    source_size = source_path.stat().st_size
    dest_size = dest_path.stat().st_size

    if not validate_file_sizes(source_size, dest_size):
        raise ValueError(f"File size mismatch: source={source_size}, dest={dest_size}")
