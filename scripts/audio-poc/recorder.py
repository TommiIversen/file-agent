import os
os.environ["SD_ENABLE_ASIO"] = "1"

import asyncio
import concurrent.futures
import logging
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

# Konfiguration
DEVICE_NAME = "ASIO MADIface USB"
NUM_CHANNELS = 14
SAMPLERATE = 48000
OUTPUT_DIR = Path("recordings")

# Maks antal blokke i køen før vi dropper data.
# Ved 48 kHz / 128 frames per blok ≈ 375 blokke/sek.
# 4096 blokke ≈ ~11 sekunders buffer.
MAX_QUEUE_SIZE = 4096


class AsioThread:
    """Dedikeret tråd der ejer hele PortAudio/ASIO-livscyklussen.

    ASIO bruger COM (STA) på Windows. Alle PortAudio-kald SKAL ske
    på samme tråd. Denne klasse kører en kommando-kø på en fast tråd
    der initialiserer PortAudio ved opstart.
    """

    def __init__(self):
        self._cmd_q: queue.Queue[tuple] = queue.Queue()
        self._thread = threading.Thread(
            target=self._run, name="asio-thread"
        )
        self._ready = threading.Event()
        self._sd = None  # sounddevice importeres på ASIO-tråden
        self._thread.start()
        self._ready.wait()

    def _run(self):
        """Kører på den dedikerede ASIO-tråd."""
        import sounddevice as sd
        sd._terminate()
        sd._initialize()
        self._sd = sd
        self._ready.set()

        while True:
            future, fn, args, kwargs = self._cmd_q.get()
            if fn is None:  # shutdown signal
                sd._terminate()
                logger.info("PortAudio/ASIO termineret")
                future.set_result(None)
                break
            try:
                result = fn(*args, **kwargs)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)

    def submit(self, fn, *args, **kwargs) -> concurrent.futures.Future:
        """Submit en funktion til ASIO-tråden. Returnerer Future."""
        future = concurrent.futures.Future()
        self._cmd_q.put((future, fn, args, kwargs))
        return future

    async def asubmit(self, fn, *args, **kwargs):
        """Async variant — awaiter resultatet uden at blokere event loop."""
        future = self.submit(fn, *args, **kwargs)
        loop = asyncio.get_running_loop()
        return await asyncio.wrap_future(future, loop=loop)

    def shutdown(self):
        """Luk PortAudio og stop ASIO-tråden. Frigiver ASIO-driveren."""
        future = self.submit(None)
        self._thread.join(timeout=5)

    @property
    def sd(self):
        return self._sd


# Singleton — opret ved første brug
_asio_thread: AsioThread | None = None


def get_asio_thread() -> AsioThread:
    global _asio_thread
    if _asio_thread is None:
        _asio_thread = AsioThread()
    return _asio_thread


def shutdown_asio():
    """Luk ASIO-tråden og frigiv driveren."""
    global _asio_thread
    if _asio_thread is not None:
        _asio_thread.shutdown()
        _asio_thread = None


def find_asio_device(name: str) -> int:
    """Find ASIO device index by name substring. Stabil på tværs af reboots."""
    at = get_asio_thread()
    sd = at.sd
    host_apis = sd.query_hostapis()
    for i, dev in enumerate(sd.query_devices()):
        api = host_apis[dev["hostapi"]]["name"]
        if "ASIO" in api and name.lower() in dev["name"].lower():
            return i
    raise RuntimeError(f"No ASIO device matching '{name}' found")


def query_asio_devices() -> list[dict]:
    """Returnér liste over ASIO-enheder. Thread-safe."""
    at = get_asio_thread()
    sd = at.sd
    host_apis = sd.query_hostapis()
    devices = []
    for i, dev in enumerate(sd.query_devices()):
        api_name = host_apis[dev["hostapi"]]["name"]
        if "ASIO" in api_name:
            devices.append({
                "index": i,
                "name": dev["name"],
                "max_input_channels": dev["max_input_channels"],
                "max_output_channels": dev["max_output_channels"],
                "default_samplerate": int(dev["default_samplerate"]),
            })
    return devices


class Recorder:
    def __init__(
        self,
        device: str = DEVICE_NAME,
        channels: int | list[int] = NUM_CHANNELS,
        samplerate: int = SAMPLERATE,
        output_dir: Path = OUTPUT_DIR,
        subtype: str = "PCM_24",
    ):
        self._at = get_asio_thread()
        self.device = (
            self._at.submit(find_asio_device, device).result()
            if isinstance(device, str) else device
        )
        self.device_name = device if isinstance(device, str) else str(device)
        self.output_dir = output_dir
        self.subtype = subtype
        self.samplerate = samplerate

        if isinstance(channels, list):
            self._channel_selectors = channels
            self.channels = len(channels)
        else:
            self._channel_selectors = list(range(channels))
            self.channels = channels

        self._audio_q: queue.Queue[np.ndarray | None] = queue.Queue(
            maxsize=MAX_QUEUE_SIZE
        )
        self._stream = None
        self._writers: list[sf.SoundFile] = []
        self._writer_thread: threading.Thread | None = None
        self._writer_error: BaseException | None = None
        self._recording = False
        self._overflow_count = 0
        self.is_broken = threading.Event()

    # -- ASIO callback: kun kø-push, ingen I/O --
    def _callback(self, indata: np.ndarray, frames: int, time, status):
        if self.is_broken.is_set():
            return
        if status:
            logger.warning("ASIO callback status: %s", status)
        try:
            self._audio_q.put_nowait(indata.copy())
        except queue.Full:
            self._overflow_count += 1
            if self._overflow_count % 100 == 1:
                logger.error(
                    "Queue overflow #%d — disk writer kan ikke følge med",
                    self._overflow_count,
                )

    # -- Disk-skriver i egen tråd --
    def _writer_loop(self):
        try:
            while True:
                block = self._audio_q.get()
                if block is None:
                    break
                for ch, w in enumerate(self._writers):
                    w.write(block[:, ch])
        except Exception as exc:
            self._writer_error = exc
            self.is_broken.set()
            logger.exception("Writer-tråd fejlede fatalt")

    def _open_stream(self) -> float:
        """Åbn ASIO stream. SKAL køres på ASIO-tråden."""
        sd = self._at.sd
        asio_settings = sd.AsioSettings(channel_selectors=self._channel_selectors)
        self._stream = sd.InputStream(
            device=self.device,
            channels=self.channels,
            samplerate=self.samplerate,
            callback=self._callback,
            extra_settings=asio_settings,
        )
        self._stream.start()
        return self._stream.samplerate

    def _close_stream(self):
        """Luk ASIO stream. SKAL køres på ASIO-tråden."""
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def start(self) -> list[Path]:
        """Start optagelse. Returnerer liste over filstier."""
        if self._recording:
            raise RuntimeError("Allerede i gang med at optage")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._overflow_count = 0
        self._writer_error = None

        # Tøm køen
        while not self._audio_q.empty():
            try:
                self._audio_q.get_nowait()
            except queue.Empty:
                break

        # Dansk datoformat: DD-MM-YYYY_HH_MM_SS
        stamp = datetime.now().strftime("%d-%m-%Y_%H_%M_%S")

        files: list[Path] = []
        self._writers = []
        for ch in range(self.channels):
            path = self.output_dir / f"channel_{ch + 1}_{stamp}.wav"
            writer = sf.SoundFile(
                str(path), mode="w",
                samplerate=self.samplerate,
                channels=1,
                format="WAV",
                subtype=self.subtype,
            )
            self._writers.append(writer)
            files.append(path)

        # Start disk-skriver tråd (IKKE daemon — skal flushe ved shutdown)
        self._writer_thread = threading.Thread(
            target=self._writer_loop, name="wav-writer"
        )
        self._writer_thread.start()

        # Start ASIO stream via den dedikerede tråd
        actual_sr = self._at.submit(self._open_stream).result()

        # Verificer at streamen kører med den forventede samplerate
        if actual_sr != self.samplerate:
            self._at.submit(self._close_stream).result()
            self._audio_q.put(None)
            self._writer_thread.join()
            self._close_writers()
            raise RuntimeError(
                f"Samplerate mismatch: requested {self.samplerate}, "
                f"got {actual_sr}. Check your ASIO driver settings."
            )

        self._recording = True
        return files

    def stop(self) -> dict:
        """Stop optagelse og luk filer. Returnerer status-dict."""
        if not self._recording:
            return {"status": "not_recording"}
        self._recording = False

        self._at.submit(self._close_stream).result()

        # Signal skriver-tråden at stoppe og vent til køen er tømt
        self._audio_q.put(None)
        self._writer_thread.join()
        self._writer_thread = None

        # Luk WAV-filer (skriver header med korrekt længde)
        self._close_writers()

        result = {
            "status": "stopped",
            "overflow_count": self._overflow_count,
        }
        if self._writer_error:
            result["writer_error"] = str(self._writer_error)
        return result

    def _close_writers(self):
        for w in self._writers:
            try:
                w.close()
            except Exception:
                logger.exception("Fejl ved lukning af WAV-fil")
        self._writers = []

    @property
    def is_recording(self) -> bool:
        return self._recording

    # -- Async helpers til brug i FastAPI --

    async def astart(self) -> list[Path]:
        # start() kører på en normal tråd. Internt submitter den kun
        # _open_stream/_close_stream til ASIO-tråden.
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.start)

    async def astop(self) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.stop)

    async def arecord(self, duration: float) -> list[Path]:
        files = await self.astart()
        await asyncio.sleep(duration)
        await self.astop()
        return files

