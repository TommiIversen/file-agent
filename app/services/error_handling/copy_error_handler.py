"""
Copy Error Handler Strategy for File Transfer Agent.

Ekstrakteret fra FileCopyService som en del af SOLID principper implementering.
Håndterer classification af fejl, retry beslutninger, og global vs. lokal fejlhåndtering.

Strategy pattern tillader forskellige error handling approaches og gør det nemmere at teste.
"""

import asyncio
import logging
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

from app.config import Settings


class ErrorType(str, Enum):
    """
    Classification af forskellige error typer for retry logic.
    
    - LOCAL: Lokale fejl der kan retries med kort delay (fil låst, permissions osv.)
    - GLOBAL: Globale fejl der kræver lang delay (destination utilgængelig, netværk)
    - PERMANENT: Fejl der ikke skal retries (fil ikke fundet, korrupt osv.)
    """
    LOCAL = "local"           # Fil låst, permissions, temp issues - retry with short delay
    GLOBAL = "global"         # Destination unavailable, network issues - retry with long delay
    PERMANENT = "permanent"   # File not found, corrupt file, fatal errors - don't retry


class RetryDecision(str, Enum):
    """
    Beslutning om hvordan en fejl skal håndteres.
    """
    RETRY_IMMEDIATELY = "retry_immediately"  # Retry uden delay
    RETRY_SHORT_DELAY = "retry_short_delay"  # Retry med kort delay (lokal fejl)
    RETRY_LONG_DELAY = "retry_long_delay"    # Retry med lang delay (global fejl)
    NO_RETRY = "no_retry"                    # Giv op, marker som failed


@dataclass
class ErrorHandlingResult:
    """
    Resultat af error handling analysis.
    
    Indeholder information om hvordan en fejl skal håndteres,
    inklusive retry decision og delay specifictions.
    """
    error_type: ErrorType
    retry_decision: RetryDecision
    delay_seconds: float
    should_retry: bool
    error_message: str
    classification_reason: str
    timestamp: datetime
    
    @property
    def is_retriable(self) -> bool:
        """Check if this error should be retried"""
        return self.retry_decision != RetryDecision.NO_RETRY


class CopyErrorHandler:
    """
    Strategy class for handling copy errors med retry logic.
    
    Ansvar:
    1. Error Classification: Classifieer fejl som LOCAL, GLOBAL eller PERMANENT
    2. Retry Decisions: Bestem om retry skal ske og med hvilket delay
    3. Global Error Handling: Håndter globale fejl med infinite retry
    4. Local Error Handling: Håndter lokale fejl med limited retry
    5. Statistics: Track error counts og patterns
    
    Følger Strategy pattern for at gøre error handling modulært og testbart.
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize CopyErrorHandler med konfiguration.
        
        Args:
            settings: Application settings med retry configuration
        """
        self.settings = settings
        
        
        # Error statistics
        self._local_errors_count = 0
        self._global_errors_count = 0
        self._permanent_errors_count = 0
        self._total_retries_performed = 0
        
        # Global error state
        self._in_global_error_state = False
        self._last_global_error_time: Optional[datetime] = None
        
        logging.info("CopyErrorHandler initialiseret")
        logging.info(f"Max retry attempts: {self.settings.max_retry_attempts}")
        logging.info(f"Local retry delay: {self.settings.retry_delay_seconds}s")
        logging.info(f"Global retry delay: {self.settings.global_retry_delay_seconds}s")
    
    async def handle_local_error(self, error: Exception, file_path: str, 
                                attempt: int, max_attempts: int) -> ErrorHandlingResult:
        """
        Håndter lokal fejl med retry decision logic.
        
        Lokal fejl = fil låst, permissions, korrupt fil osv.
        Har limited retry attempts med kort delay.
        
        Args:
            error: Exception der opstod
            file_path: Fil path der fejlede
            attempt: Nuværende forsøg nummer
            max_attempts: Total antal forsøg tilladt
            
        Returns:
            ErrorHandlingResult med retry decision
        """
        error_type = self.classify_error(error)
        
        # Log error details
        logging.warning(
            f"Local error handling: {error.__class__.__name__}: {error}",
            extra={
                "operation": "local_error_handling",
                "file_path": file_path,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "error_type": error_type.value,
                "error_class": error.__class__.__name__
            }
        )
        
        # Determine retry decision based on error type and attempt count
        if error_type == ErrorType.PERMANENT:
            # Permanent errors should not be retried
            self._permanent_errors_count += 1
            return ErrorHandlingResult(
                error_type=error_type,
                retry_decision=RetryDecision.NO_RETRY,
                delay_seconds=0.0,
                should_retry=False,
                error_message=f"Permanent error: {str(error)}",
                classification_reason=f"Error classified as permanent: {error.__class__.__name__}",
                timestamp=datetime.now()
            )
        
        elif error_type == ErrorType.GLOBAL:
            # Global errors should be escalated to global error handling
            self._global_errors_count += 1
            return ErrorHandlingResult(
                error_type=error_type,
                retry_decision=RetryDecision.RETRY_LONG_DELAY,
                delay_seconds=float(self.settings.global_retry_delay_seconds),
                should_retry=True,
                error_message=f"Global error (escalated): {str(error)}",
                classification_reason=f"Error classified as global: {error.__class__.__name__}",
                timestamp=datetime.now()
            )
        
        else:  # LOCAL error
            self._local_errors_count += 1
            
            if attempt >= max_attempts:
                # Max attempts reached
                return ErrorHandlingResult(
                    error_type=error_type,
                    retry_decision=RetryDecision.NO_RETRY,
                    delay_seconds=0.0,
                    should_retry=False,
                    error_message=f"Max retry attempts ({max_attempts}) reached: {str(error)}",
                    classification_reason="Retry limit exceeded for local error",
                    timestamp=datetime.now()
                )
            else:
                # Retry with short delay
                self._total_retries_performed += 1
                return ErrorHandlingResult(
                    error_type=error_type,
                    retry_decision=RetryDecision.RETRY_SHORT_DELAY,
                    delay_seconds=float(self.settings.retry_delay_seconds),
                    should_retry=True,
                    error_message=f"Local error (attempt {attempt}/{max_attempts}): {str(error)}",
                    classification_reason=f"Retriable local error, attempt {attempt} of {max_attempts}",
                    timestamp=datetime.now()
                )
    
    async def handle_global_error(self, error_message: str) -> None:
        """
        Håndter global fejl med infinite retry og lang delay.
        
        Global fejl = destination utilgængelig, netværksproblemer osv.
        Denne metode håndterer det globale retry pattern med lange delays.
        
        Args:
            error_message: Beskrivelse af global fejl
        """
        if not self._in_global_error_state:
            logging.warning(f"Global fejl detekteret: {error_message}")
            logging.warning(f"Pauser alle operationer i {self.settings.global_retry_delay_seconds} sekunder")
            
            self._in_global_error_state = True
            self._last_global_error_time = datetime.now()
            self._global_errors_count += 1
        
        # Infinite retry med lang delay
        await asyncio.sleep(self.settings.global_retry_delay_seconds)
    
    def classify_error(self, error: Exception) -> ErrorType:
        """
        Klassificer en exception som LOCAL, GLOBAL eller PERMANENT.
        
        Classification logic baseret på exception type og patterns:
        - FileNotFoundError, CorruptionError: PERMANENT
        - PermissionError, BlockingIOError: LOCAL (kan løses ved retry)
        - ConnectionError, TimeoutError: GLOBAL (netværksproblemer)
        - OSError med specific errno: Kan være LOCAL eller GLOBAL
        
        Args:
            error: Exception at klassificere
            
        Returns:
            ErrorType classification
        """
        error_str = str(error).lower()
        
        # Permanent errors (don't retry)
        if isinstance(error, FileNotFoundError):
            return ErrorType.PERMANENT
        
        if isinstance(error, ValueError) and "size mismatch" in error_str:
            return ErrorType.PERMANENT
        
        if "corrupt" in error_str or "invalid" in error_str or "malformed" in error_str:
            return ErrorType.PERMANENT
        
        # Global errors (network, destination availability)
        if isinstance(error, (ConnectionError, TimeoutError)):
            return ErrorType.GLOBAL
        
        if isinstance(error, OSError):
            # Check specific OSError patterns
            errno = getattr(error, 'errno', None)
            
            # Network-related errors
            if errno in [28, 30, 32]:  # No space left, Read-only filesystem, Broken pipe
                return ErrorType.GLOBAL
            
            # Windows network errors
            if "network" in error_str or "destination" in error_str:
                return ErrorType.GLOBAL
        
        if "destination" in error_str and ("unavailable" in error_str or "not accessible" in error_str):
            return ErrorType.GLOBAL
        
        # Local errors (file locks, permissions, temporary issues)
        if isinstance(error, PermissionError):
            return ErrorType.LOCAL
        
        if isinstance(error, (BlockingIOError, InterruptedError)):
            return ErrorType.LOCAL
        
        if "permission denied" in error_str or "access denied" in error_str:
            return ErrorType.LOCAL
        
        if "file is being used" in error_str or "locked" in error_str:
            return ErrorType.LOCAL
        
        # Default to LOCAL for retryable unknown errors
        return ErrorType.LOCAL
    
    def should_retry(self, error: Exception, attempt: int, max_attempts: int) -> bool:
        """
        Bestem om en fejl skal retries baseret på error type og attempt count.
        
        Args:
            error: Exception der opstod
            attempt: Nuværende forsøg nummer
            max_attempts: Maximum antal forsøg
            
        Returns:
            True hvis retry skal ske
        """
        error_type = self.classify_error(error)
        
        if error_type == ErrorType.PERMANENT:
            return False
        
        if error_type == ErrorType.GLOBAL:
            return True  # Global errors are retried with long delays
        
        # LOCAL errors
        return attempt < max_attempts
    
    def clear_global_error_state(self) -> None:
        """
        Clear global error state når destination bliver tilgængelig igen.
        
        Bruges når destination checker rapporterer at destination er available igen.
        """
        if self._in_global_error_state:
            logging.info("Clearing global error state - destination available again")
            self._in_global_error_state = False
            self._last_global_error_time = None
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """
        Hent detaljerede error handling statistikker.
        
        Returns:
            Dictionary med error statistics
        """
        return {
            "local_errors_count": self._local_errors_count,
            "global_errors_count": self._global_errors_count,
            "permanent_errors_count": self._permanent_errors_count,
            "total_retries_performed": self._total_retries_performed,
            "in_global_error_state": self._in_global_error_state,
            "last_global_error_time": self._last_global_error_time.isoformat() if self._last_global_error_time else None,
            "error_handling_config": {
                "max_retry_attempts": self.settings.max_retry_attempts,
                "retry_delay_seconds": self.settings.retry_delay_seconds,
                "global_retry_delay_seconds": self.settings.global_retry_delay_seconds
            }
        }
    
    def get_classification_info(self) -> Dict[str, Any]:
        """
        Hent information om error classification logic for debugging.
        
        Returns:
            Dictionary med classification patterns
        """
        return {
            "permanent_patterns": [
                "FileNotFoundError",
                "ValueError with 'size mismatch'",
                "Corruption patterns (corrupt, invalid, malformed)"
            ],
            "global_patterns": [
                "ConnectionError, TimeoutError",
                "OSError errno 28,30,32 (No space, Read-only, Broken pipe)",
                "Network/destination unavailable patterns"
            ],
            "local_patterns": [
                "PermissionError, BlockingIOError",
                "Permission/access denied patterns",
                "File lock patterns"
            ],
            "default_classification": "LOCAL (for unknown retriable errors)"
        }
    
    def reset_statistics(self) -> None:
        """Reset error statistics for testing purposes."""
        self._local_errors_count = 0
        self._global_errors_count = 0
        self._permanent_errors_count = 0
        self._total_retries_performed = 0
        self._in_global_error_state = False
        self._last_global_error_time = None
        
        logging.info("Error statistics reset")
