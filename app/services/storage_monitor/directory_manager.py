from pathlib import Path
import logging


class DirectoryManager:

    def __init__(self):
        pass

    async def ensure_directory_exists(self, path: str, storage_type: str) -> bool:
        try:
            path_obj = Path(path)

            if path_obj.exists() and path_obj.is_dir():
                return True

            logging.info(f"Creating missing {storage_type} directory: {path}")
            path_obj.mkdir(parents=True, exist_ok=True)

            if path_obj.exists() and path_obj.is_dir():
                logging.info(f"Successfully created {storage_type} directory: {path}")
                return True
            else:
                logging.error(
                    f"Directory creation appeared successful but verification failed: {path}"
                )
                return False

        except Exception as e:
            logging.error(f"Failed to create {storage_type} directory {path}: {e}")
            return False
