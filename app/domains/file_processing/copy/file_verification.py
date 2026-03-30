import asyncio
import logging
import os
import aiofiles
import aiofiles.os


class FileVerificationService:
    """
    Håndterer post-kopi verificering og oprydning af kildefil.
    """
    def __init__(self, retry_delay: float = 2.0):
        self._retry_delay = retry_delay
        logging.info("FileVerificationService initialiseret")

    async def verify_integrity(self, source_path: str, dest_path: str) -> tuple[bool, int, int]:
        """
        Verificer at kilde- og destinationsfil har rimelig størrelse.
        
        Args:
            source_path: Sti til kildefil
            dest_path: Sti til destinationsfil
            
        Returns:
            Tuple af (success, source_bytes, dest_bytes).
            For growing files returneres den faktiske destination størrelse som bytes_copied.
        """
        try:
            source_size = await aiofiles.os.path.getsize(source_path)
            dest_size = await aiofiles.os.path.getsize(dest_path)

            # Critical: destination must have actual data
            if dest_size == 0:
                logging.error(f"Verification FAILED: destination file is empty (0 bytes): {dest_path}")
                return False, source_size, dest_size

            # For growing files, dest < source is normal (source kept growing during copy).
            # But dest should never be larger than source.
            if dest_size > source_size:
                logging.error(
                    f"Verification FAILED: destination ({dest_size}) larger than source ({source_size}): {dest_path}"
                )
                return False, source_size, dest_size

            if source_size != dest_size:
                logging.warning(
                    f"Size difference: source={source_size}, dest={dest_size} "
                    f"(normal for growing files, {dest_size/source_size*100:.1f}% copied)"
                )
            else:
                logging.debug(f"File integrity verified: {dest_size} bytes")
            
            return True, source_size, dest_size
            
        except Exception as e:
            logging.error(f"Error verifying file integrity: {e}", exc_info=True)
            return False, 0, 0

    async def delete_source_file(self, source_path: str) -> tuple[bool, str | None]:
        """
        Forsøg at slette kildefilen med retry-logik.
        
        Args:
            source_path: Sti til kildefil der skal slettes
            
        Returns:
            Tuple af (success, error_message). error_message er None hvis succesfuld.
        """
        last_error = None
        for i in range(3): # 3 retry forsøg
            try:
                await aiofiles.os.remove(source_path)
                logging.debug(f"Source file deleted: {os.path.basename(source_path)}")
                return True, None
            except Exception as e:
                last_error = str(e)
                logging.warning(
                    f"Delete attempt {i + 1}/3 failed for {os.path.basename(source_path)}: {e}"
                )
                if i < 2:
                    await asyncio.sleep(self._retry_delay)
        return False, last_error
