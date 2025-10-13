"""
Secure Resume Configuration

Konfiguration for ultra-sikker resume funktionalitet med byte-level verification.
Dette system prioriterer data integritet over performance og giver maksimal
kontrol over hvordan resume operationer udføres.
"""

from typing import Optional
from pydantic import BaseModel, Field, field_validator
import logging

logger = logging.getLogger("app.utils.secure_resume_config")


class SecureResumeConfig(BaseModel):
    """
    Konfiguration for sikker resume funktionalitet.

    Denne klasse definerer alle parametre for hvordan resume operationer
    skal udføres med maksimal sikkerhed og data integritet.
    """

    # Verification sizes
    min_verify_bytes: int = Field(
        default=1024,  # 1KB minimum
        description="Minimum antal bytes der skal verificeres før resume",
        ge=512,  # Mindst 512 bytes
    )

    max_verify_mb: int = Field(
        default=100,  # 100MB maximum
        description="Maximum MB der verificeres i ét styk",
        ge=1,
        le=1000,  # Mellem 1MB og 1GB
    )

    # Progressive search parameters
    binary_search_chunk_mb: int = Field(
        default=1,  # 1MB chunks for binary search
        description="Chunk størrelse for binary search af corruption points",
        ge=1,
        le=100,
    )

    verification_buffer_kb: int = Field(
        default=64,  # 64KB buffer
        description="Buffer størrelse for byte-level verification",
        ge=4,
        le=1024,  # Mellem 4KB og 1MB
    )

    # Adaptive verification for large files
    large_file_threshold_mb: int = Field(
        default=1000,  # 1GB threshold
        description="Størrelse hvor adaptive verification starter",
        ge=100,
    )

    large_file_verification_mb: int = Field(
        default=50,  # Verificer kun 50MB for store filer
        description="Verification størrelse for store filer",
        ge=10,
        le=500,
    )

    # Corruption handling
    max_corruption_search_attempts: int = Field(
        default=10,
        description="Max antal forsøg på at finde corruption point",
        ge=3,
        le=50,
    )

    corruption_expansion_factor: float = Field(
        default=2.0,
        description="Faktor for udvidelse af verification ved corruption",
        ge=1.5,
        le=5.0,
    )

    # Safety margins
    safety_margin_kb: int = Field(
        default=1024,  # 1MB safety margin
        description="Ekstra bytes der droppes ved corruption for sikkerhed",
        ge=0,
        le=10240,  # Max 10MB
    )

    # Performance tuning
    enable_parallel_verification: bool = Field(
        default=False,
        description="Aktiver parallel verification (eksperimentel)",
    )

    max_verification_time_seconds: int = Field(
        default=300,  # 5 minutter max
        description="Maximum tid til verification før timeout",
        ge=30,
        le=3600,
    )

    # Logging og debugging
    detailed_corruption_logging: bool = Field(
        default=True, description="Aktiver detaljeret logging af corruption detection"
    )

    log_verification_progress: bool = Field(
        default=False, description="Log verification progress (kan være meget verbose)"
    )

    @field_validator("max_verify_mb")
    @classmethod
    def max_verify_reasonable(cls, v, info):
        """Sørg for at max verification størrelse er rimelig"""
        if info.data and "large_file_verification_mb" in info.data:
            large_file_value = info.data["large_file_verification_mb"]
            if v < large_file_value:
                raise ValueError(
                    f"max_verify_mb ({v}) skal være >= large_file_verification_mb "
                    f"({large_file_value})"
                )
        return v

    @field_validator("binary_search_chunk_mb")
    @classmethod
    def binary_search_chunk_reasonable(cls, v, info):
        """Sørg for at binary search chunk er mindre end max verification"""
        if info.data and "max_verify_mb" in info.data:
            max_verify_value = info.data["max_verify_mb"]
            if v > max_verify_value:
                raise ValueError(
                    f"binary_search_chunk_mb ({v}) skal være <= max_verify_mb "
                    f"({max_verify_value})"
                )
        return v

    def get_verification_size_for_file(self, file_size_bytes: int) -> int:
        """
        Beregn optimal verification størrelse baseret på fil størrelse.

        Args:
            file_size_bytes: Størrelse af filen der skal verificeres

        Returns:
            Antal bytes der skal verificeres
        """
        file_size_mb = file_size_bytes / (1024 * 1024)

        if file_size_mb > self.large_file_threshold_mb:
            # Store filer: brug reduceret verification
            verify_bytes = self.large_file_verification_mb * 1024 * 1024
        else:
            # Små/medium filer: brug op til max_verify_mb
            max_verify_bytes = self.max_verify_mb * 1024 * 1024
            verify_bytes = min(max_verify_bytes, file_size_bytes)

        # Sørg for minimum verification
        return max(self.min_verify_bytes, verify_bytes)

    def get_binary_search_chunk_size(self) -> int:
        """Get binary search chunk størrelse i bytes"""
        return self.binary_search_chunk_mb * 1024 * 1024

    def get_verification_buffer_size(self) -> int:
        """Get verification buffer størrelse i bytes"""
        return self.verification_buffer_kb * 1024

    def get_safety_margin_bytes(self) -> int:
        """Get safety margin i bytes"""
        return self.safety_margin_kb * 1024

    def log_config(self):
        """Log den aktuelle konfiguration"""
        logger.info("SecureResumeConfig indlæst:")
        logger.info(
            f"  Verification: {self.min_verify_bytes} bytes - {self.max_verify_mb} MB"
        )
        logger.info(f"  Binary search: {self.binary_search_chunk_mb} MB chunks")
        logger.info(f"  Buffer: {self.verification_buffer_kb} KB")
        logger.info(
            f"  Store filer: >{self.large_file_threshold_mb} MB → {self.large_file_verification_mb} MB verification"
        )
        logger.info(f"  Safety margin: {self.safety_margin_kb} KB")
        logger.info(f"  Max verification tid: {self.max_verification_time_seconds}s")


class ResumeOperationMetrics(BaseModel):
    """
    Metrics for resume operationer til monitoring og optimering.
    """

    file_size_bytes: int
    dest_size_bytes: int
    verification_bytes: int
    verification_time_seconds: float
    corruption_detected: bool
    corruption_offset: Optional[int] = None
    bytes_preserved: int
    resume_position: int
    binary_search_iterations: int = 0

    @property
    def preservation_percentage(self) -> float:
        """Beregn hvor meget af filen der blev bevaret"""
        if self.dest_size_bytes == 0:
            return 0.0
        return (self.bytes_preserved / self.dest_size_bytes) * 100.0

    @property
    def verification_percentage(self) -> float:
        """Beregn hvor meget af filen der blev verificeret"""
        if self.dest_size_bytes == 0:
            return 0.0
        return (self.verification_bytes / self.dest_size_bytes) * 100.0

    def log_metrics(self):
        """Log resumé operation metrics"""
        logger.info("Resume Operation Metrics:")
        logger.info(f"  Fil størrelse: {self.file_size_bytes:,} bytes")
        logger.info(f"  Dest størrelse: {self.dest_size_bytes:,} bytes")
        logger.info(
            f"  Verificeret: {self.verification_bytes:,} bytes ({self.verification_percentage:.1f}%)"
        )
        logger.info(f"  Verification tid: {self.verification_time_seconds:.2f}s")
        logger.info(f"  Corruption: {'Ja' if self.corruption_detected else 'Nej'}")
        if self.corruption_detected and self.corruption_offset is not None:
            logger.info(f"  Corruption offset: {self.corruption_offset:,} bytes")
        logger.info(
            f"  Bytes bevaret: {self.bytes_preserved:,} ({self.preservation_percentage:.1f}%)"
        )
        logger.info(f"  Resume position: {self.resume_position:,} bytes")
        if self.binary_search_iterations > 0:
            logger.info(f"  Binary search iterationer: {self.binary_search_iterations}")


# Standard konfigurationer for forskellige use cases
CONSERVATIVE_CONFIG = SecureResumeConfig(
    min_verify_bytes=2048,  # 2KB minimum
    max_verify_mb=200,  # 200MB max verification
    binary_search_chunk_mb=2,  # 2MB chunks
    large_file_verification_mb=100,  # 100MB for store filer
    safety_margin_kb=2048,  # 2MB safety margin
    detailed_corruption_logging=True,
)

PERFORMANCE_CONFIG = SecureResumeConfig(
    min_verify_bytes=1024,  # 1KB minimum
    max_verify_mb=50,  # 50MB max verification
    binary_search_chunk_mb=1,  # 1MB chunks
    large_file_verification_mb=25,  # 25MB for store filer
    safety_margin_kb=1024,  # 1MB safety margin
    detailed_corruption_logging=False,
)

PARANOID_CONFIG = SecureResumeConfig(
    min_verify_bytes=4096,  # 4KB minimum
    max_verify_mb=500,  # 500MB max verification
    binary_search_chunk_mb=5,  # 5MB chunks
    large_file_verification_mb=200,  # 200MB for store filer
    safety_margin_kb=5120,  # 5MB safety margin
    corruption_expansion_factor=3.0,  # Aggressiv expansion
    max_corruption_search_attempts=20,
    detailed_corruption_logging=True,
    log_verification_progress=True,
)
