#!/usr/bin/env python3
import asyncio
import argparse
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

"""
File Growth Simulator
Simulerer videoptager der skriver til 8 streams kontinuerligt,
og "clipper" dem efter en time med _1, _2 osv. bagefter.
Skriver direkte til .mxf filer som en rigtig videoptager.
"""


# Konfiguration variabler
DEFAULT_OUTPUT_FOLDER = r"C:\temp_input"
DEFAULT_STREAM_COUNT = 1
DEFAULT_WRITE_INTERVAL_MS = 500  # Millisekunder mellem hver skrivning
DEFAULT_CHUNK_SIZE_KB = 64 * 2  # KB per skrivning (realistisk for video)
DEFAULT_CLIP_DURATION_MINUTES = 4  # Minutter før ny fil startes
DEFAULT_NEW_FILE_INTERVAL_MINUTES = (
    0  # Forskydning mellem stream starts (0 = alle samtidigt)
)


class VideoStream:
    """Repræsenterer en enkelt video stream der skriver til fil"""

    def __init__(
        self,
        stream_id: int,
        output_folder: Path,
        chunk_size_kb: int,
        write_interval_ms: int,
        clip_duration_minutes: int,
        stream_type: str = "Cam",
    ):
        self.stream_id = stream_id
        self.stream_type = stream_type  # "Cam", "PGM", "CLN"
        self.output_folder = output_folder
        self.chunk_size_bytes = chunk_size_kb * 1024
        self.write_interval_seconds = write_interval_ms / 1000.0
        self.clip_duration = timedelta(minutes=clip_duration_minutes)

        self.current_file = None
        self.current_file_start_time = None
        self.total_bytes_written = 0
        self.is_running = False

        # Sørg for output folder eksisterer
        self.output_folder.mkdir(parents=True, exist_ok=True)

    def _get_filename(self) -> str:
        """Genererer filnavn der matcher template system"""
        # Format: YYMMDD_HHMM_Ingest_TYPE.mxf
        # Eksempel: 200305_1344_Ingest_Cam1.mxf
        now = datetime.now()
        date_str = now.strftime("%y%m%d")  # YYMMDD format
        time_str = now.strftime("%H%M")  # HHMM format

        if self.stream_type == "Cam":
            type_suffix = f"Cam{self.stream_id}"
        elif self.stream_type == "PGM":
            type_suffix = "PGM"
        elif self.stream_type == "CLN":
            type_suffix = "CLN"
        else:
            type_suffix = f"{self.stream_type}{self.stream_id}"

        return f"{date_str}_{time_str}_Ingest_{type_suffix}.mxf"

    def _start_new_file(self):
        """Starter en ny fil for denne stream"""
        if self.current_file:
            self._finalize_current_file()

        file_path = self.output_folder / self._get_filename()
        self.current_file = open(file_path, "wb")
        self.current_file_start_time = datetime.now()

        logging.info(f"Stream {self.stream_id}: Startet ny fil {file_path.name}")

    def _finalize_current_file(self):
        """Afslutter nuværende fil"""
        if not self.current_file:
            return

        file_path = Path(self.current_file.name)
        self.current_file.close()

        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        logging.info(
            f"Stream {self.stream_id}: Afsluttet fil {file_path.name} ({file_size_mb:.1f} MB)"
        )

        self.current_file = None

    async def run(self):
        """Hovedloop for denne stream"""
        self.is_running = True
        logging.info(f"Stream {self.stream_id}: Starter...")

        self._start_new_file()

        try:
            while self.is_running:
                # Tjek om vi skal starte en ny fil (clip efter X minutter)
                if (
                    datetime.now() - self.current_file_start_time
                ) >= self.clip_duration:
                    self._start_new_file()

                # Skriv en chunk af data
                if self.current_file:
                    # Generer tilfældige bytes (simulerer video data)
                    chunk = bytes(
                        random.getrandbits(8) for _ in range(self.chunk_size_bytes)
                    )
                    self.current_file.write(chunk)
                    self.current_file.flush()  # Vigtig for at simulere realtid skrivning

                    self.total_bytes_written += len(chunk)

                    # Log fremgang hver 10. MB
                    if (
                        self.total_bytes_written % (10 * 1024 * 1024)
                        < self.chunk_size_bytes
                    ):
                        mb_written = self.total_bytes_written / (1024 * 1024)
                        logging.info(
                            f"Stream {self.stream_id}: {mb_written:.1f} MB skrevet til {self._get_filename()}"
                        )

                # Vent før næste skrivning
                await asyncio.sleep(self.write_interval_seconds)

        except asyncio.CancelledError:
            logging.info(f"Stream {self.stream_id}: Stopper...")
        finally:
            if self.current_file:
                self._finalize_current_file()

    def stop(self):
        """Stopper denne stream"""
        self.is_running = False


class FileGrowthSimulator:
    """Hovedklasse der administrerer alle video streams"""

    def __init__(
        self,
        output_folder: str,
        stream_count: int,
        write_interval_ms: int,
        chunk_size_kb: int,
        clip_duration_minutes: int,
        new_file_interval_minutes: int,
        stream_mix: str = "mixed",
    ):
        self.output_folder = Path(output_folder)
        self.stream_count = stream_count
        self.write_interval_ms = write_interval_ms
        self.chunk_size_kb = chunk_size_kb
        self.clip_duration_minutes = clip_duration_minutes
        self.new_file_interval_minutes = new_file_interval_minutes
        self.stream_mix = stream_mix  # "mixed", "cameras", "program"

        self.streams: List[VideoStream] = []
        self.stream_tasks: List[asyncio.Task] = []

        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%H:%M:%S",
        )

    def _get_stream_type(self, stream_index: int) -> str:
        """Bestem stream type baseret på stream mix konfiguration"""
        if self.stream_mix == "cameras":
            return "Cam"
        elif self.stream_mix == "program":
            # Alternér mellem PGM og CLN for program streams
            return "PGM" if stream_index % 2 == 0 else "CLN"
        else:  # mixed (default)
            # Fordel streams: 60% kameraer, 20% PGM, 20% CLN
            if stream_index < self.stream_count * 0.6:
                return "Cam"
            elif stream_index < self.stream_count * 0.8:
                return "PGM"
            else:
                return "CLN"

    async def start_streams(self):
        """Starter alle streams parallelt"""
        logging.info(
            f"Starter {self.stream_count} streams parallelt i {self.output_folder}"
        )
        logging.info(f"Stream mix: {self.stream_mix}")
        logging.info(
            f"Skriveinterval: {self.write_interval_ms}ms, Chunk størrelse: {self.chunk_size_kb}KB"
        )
        logging.info(f"Clip længde: {self.clip_duration_minutes} min")

        # Opret alle streams med forskellige typer
        for i in range(self.stream_count):
            stream_type = self._get_stream_type(i)
            stream = VideoStream(
                stream_id=i + 1,
                output_folder=self.output_folder,
                chunk_size_kb=self.chunk_size_kb,
                write_interval_ms=self.write_interval_ms,
                clip_duration_minutes=self.clip_duration_minutes,
                stream_type=stream_type,
            )
            self.streams.append(stream)
            logging.info(f"Stream {i + 1}: Type = {stream_type}")

        # Start alle stream tasks parallelt (med optional forskydning)
        logging.info(f"Starter alle {self.stream_count} streams samtidigt...")
        for i, stream in enumerate(self.streams):
            # Optional forskydning mellem stream starts
            if i > 0 and self.new_file_interval_minutes > 0:
                wait_seconds = self.new_file_interval_minutes * 60
                logging.info(
                    f"Venter {wait_seconds:.1f} sekunder før stream {i + 1}..."
                )
                await asyncio.sleep(wait_seconds)

            task = asyncio.create_task(stream.run())
            self.stream_tasks.append(task)

    async def run(self):
        """Hovedloop - starter streams og venter på afslutning"""
        try:
            await self.start_streams()

            logging.info("Alle streams kører. Tryk Ctrl+C for at stoppe.")

            # Vent på alle tasks
            await asyncio.gather(*self.stream_tasks)

        except KeyboardInterrupt:
            logging.info("Modtaget stop signal...")
            await self.stop()

    async def stop(self):
        """Stopper alle streams pænt"""
        logging.info("Stopper alle streams...")

        # Stop alle streams
        for stream in self.streams:
            stream.stop()

        # Cancel alle tasks
        for task in self.stream_tasks:
            task.cancel()

        # Vent på at de afslutter
        await asyncio.gather(*self.stream_tasks, return_exceptions=True)

        logging.info("Alle streams stoppet.")


def main():
    parser = argparse.ArgumentParser(
        description="Simulerer video optager med voksende filer"
    )

    parser.add_argument(
        "--output-folder",
        default=DEFAULT_OUTPUT_FOLDER,
        help="Output mappe (default: %(default)s)",
    )

    parser.add_argument(
        "--stream-count",
        type=int,
        default=DEFAULT_STREAM_COUNT,
        help="Antal samtidige streams (default: %(default)s)",
    )

    parser.add_argument(
        "--write-interval-ms",
        type=int,
        default=DEFAULT_WRITE_INTERVAL_MS,
        help="Millisekunder mellem skrivninger (default: %(default)s)",
    )

    parser.add_argument(
        "--chunk-size-kb",
        type=int,
        default=DEFAULT_CHUNK_SIZE_KB,
        help="KB per skrivning (default: %(default)s)",
    )

    parser.add_argument(
        "--clip-duration-minutes",
        type=float,
        default=DEFAULT_CLIP_DURATION_MINUTES,
        help="Minutter før ny fil (default: %(default)s)",
    )

    parser.add_argument(
        "--new-file-interval-minutes",
        type=float,
        default=DEFAULT_NEW_FILE_INTERVAL_MINUTES,
        help="Optional forskydning mellem stream starts i minutter (default: %(default)s, 0=alle samtidigt)",
    )

    parser.add_argument(
        "--stream-mix",
        choices=["mixed", "cameras", "program"],
        default="mixed",
        help="Type af streams at generere: mixed=60%% Cam/20%% PGM/20%% CLN, cameras=kun kameraer, program=kun PGM/CLN",
    )

    args = parser.parse_args()

    # Opret simulator
    simulator = FileGrowthSimulator(
        output_folder=args.output_folder,
        stream_count=args.stream_count,
        write_interval_ms=args.write_interval_ms,
        chunk_size_kb=args.chunk_size_kb,
        clip_duration_minutes=args.clip_duration_minutes,
        new_file_interval_minutes=args.new_file_interval_minutes,
        stream_mix=args.stream_mix,
    )

    # Kør simulator
    try:
        asyncio.run(simulator.run())
    except KeyboardInterrupt:
        print("\nAfslutter...")


if __name__ == "__main__":
    main()
