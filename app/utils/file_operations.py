from pathlib import Path
import aiofiles.os


def calculate_relative_path(source_path: Path, source_base: Path) -> Path:
    try:
        return source_path.relative_to(source_base)
    except ValueError:
        # Source is not under source directory - use just filename
        return Path(source_path.name)


async def generate_conflict_free_path(dest_path: Path) -> Path:
    if not await aiofiles.os.path.exists(dest_path):
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

        if not await aiofiles.os.path.exists(new_path):
            return new_path

        counter += 1

        # Safety check - avoid infinite loop
        if counter > 9999:
            raise RuntimeError(
                f"Could not resolve name conflict after 9999 attempts: {dest_path}"
            )


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

