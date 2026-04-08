"""
Pure logic for disk space calculation — no I/O, no mocks needed.
Extracted from SpaceChecker to enable zero-mock testing.
"""


class SpaceCalculator:
    """Disk space calculation with safety margins — pure logic, no dependencies."""

    def __init__(
        self,
        safety_margin_gb: float,
        min_free_after_copy_gb: float,
    ):
        self.safety_margin_bytes = int(safety_margin_gb * 1024**3)
        self.min_free_after_bytes = int(min_free_after_copy_gb * 1024**3)

    def required_space(self, file_size_bytes: int) -> int:
        """Return minimum required free space in bytes."""
        return max(0, file_size_bytes) + self.safety_margin_bytes + self.min_free_after_bytes

    def has_sufficient_space(
        self, available_bytes: int, file_size_bytes: int
    ) -> bool:
        return available_bytes >= self.required_space(file_size_bytes)

    def shortage_bytes(
        self, available_bytes: int, file_size_bytes: int
    ) -> int:
        """Return number of bytes short (0 if enough space)."""
        required = self.required_space(file_size_bytes)
        return max(0, required - available_bytes)

    def format_reason(
        self,
        available_bytes: int,
        file_size_bytes: int,
    ) -> str:
        has_space = self.has_sufficient_space(available_bytes, file_size_bytes)
        available_gb = available_bytes / (1024**3)
        required_gb = self.required_space(file_size_bytes) / (1024**3)
        file_gb = file_size_bytes / (1024**3)
        if has_space:
            return (
                f"Sufficient space: {available_gb:.1f}GB available, "
                f"{required_gb:.1f}GB required for {file_gb:.1f}GB file"
            )
        shortage_gb = self.shortage_bytes(available_bytes, file_size_bytes) / (1024**3)
        return (
            f"Insufficient space: {available_gb:.1f}GB available, "
            f"{required_gb:.1f}GB required (shortage: {shortage_gb:.1f}GB). "
            f"File: {file_gb:.1f}GB + safety margins"
        )
