from pathlib import Path
from typing import Tuple


def list_structure_and_count_lines(
    path: Path, prefix: str = "", exclude_dirs: list[str] = []
) -> Tuple[list[str], int]:
    output = []

    total_lines = 0

    # List all files first

    for file in sorted(path.iterdir()):
        if file.is_file() and file.suffix in (".py", ".js", ".ts", ".vue", ".json"):
            with open(file, "r", encoding="utf-8") as f:
                lines = sum(1 for _ in f)

                total_lines += lines

            output.append(f"{prefix}├── {file.name} ({lines} lines)")

    # Then list directories

    for directory in sorted(path.iterdir()):
        if directory.is_dir() and directory.name not in exclude_dirs:
            output.append(f"{prefix}├── {directory.name}/")

            subdir_structure, subdir_lines = list_structure_and_count_lines(
                directory, prefix + "│   ", exclude_dirs
            )

            output.extend(subdir_structure)

            total_lines += subdir_lines

    return output, total_lines


# Test
if __name__ == "__main__":
    exclude = [".idea", "__pycache__", ".pytest_cache", ".git", "node_modules", "lib", ".vscode", "site-packages", ".venv", ".github", ".ruff_cache", "docs", "logs"]

    root = Path(__file__).parent.parent
    print("running from ", root)
    structure, lines = list_structure_and_count_lines(root, exclude_dirs=exclude)
    print(root.resolve().name)
    print("\n".join(structure))
    print(f"Total; {lines} lines")

