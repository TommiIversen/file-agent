"""
Ingest Monitor Domain Models

Pydantic models that match the Just In Engine API responses.
These models ensure type safety and data validation when working
with the Just In Engine API.
"""
from pydantic import BaseModel, Field
from typing import List, Optional


class JustInOptions(BaseModel):
    """Options object from Just In Engine recording status response."""
    TOAJustInEngineVideoSignalAvailable: bool = True
    TOAJustInEngineRecordingError: bool = False
    TOAJustInEngineTimecodeSource: Optional[int] = None
    TOAJustInEngineLicenseStatus: Optional[bool] = None
    TOAJustInEngineRecordingMode: Optional[int] = None
    TOAJustInEngineAlternativeStartTimecodeFrames: Optional[int] = None
    TOAJustInEngineTimecodeOffset: Optional[int] = None
    TOAJustInEngineAlternativeStopTimecodeFrames: Optional[int] = None
    TOAJustInEngineLiveCutEnabled: Optional[bool] = None
    TOAJustInEngineMetadataWritingOption: Optional[int] = None
    TOAJustInEngineStartTimecodeFrames: Optional[int] = None
    TOAJustInEngineAlternativeStartTimecodeActive: Optional[bool] = None
    TOAJustInEngineFramerate: Optional[int] = None
    TOAJustInEngineAlternativeStopTimecodeActive: Optional[bool] = None


class JustInRecordingStatus(BaseModel):
    """Recording status response from Just In Engine."""
    rec: bool
    frames: Optional[int] = None
    channel: str
    hours: Optional[int] = None
    seconds: Optional[int] = None
    minutes: Optional[int] = None
    name: str
    options: JustInOptions


class JustInActiveChannels(BaseModel):
    """Active channels response from Just In Engine."""
    channel_names: List[str] = Field(..., alias="channel-names")

    model_config = {"populate_by_name": True}


class JustInErrorInfo(BaseModel):
    """Error user info object."""
    NSLocalizedDescription: Optional[str] = None


class JustInError(BaseModel):
    """Individual error object from Just In Engine."""
    date: float
    errorCode: int
    errorDomain: Optional[str] = None
    errorUIDescription: str
    errorUserInfo: Optional[JustInErrorInfo] = None
    errorType: Optional[int] = None


class JustInErrors(BaseModel):
    """Error response from Just In Engine."""
    channel: str
    name: str
    errors: List[JustInError]


# ── Recording Configuration & Destination Preset models ─────────────────────

class JustInConfigurationEntry(BaseModel):
    """A single recording configuration entry."""
    destinationPreset: str = ""
    capturePreset: str = ""


class JustInRecordingConfiguration(BaseModel):
    """Response from /ingest/recordingConfiguration."""
    channel: str
    name: str
    configurations: List[JustInConfigurationEntry] = []


class JustInDestinationPresets(BaseModel):
    """Response from /ingest/requestDestinationPresets."""
    channel: str
    name: str
    preset: List[str] = []


class JustInDestinationPath(BaseModel):
    """A single destination path entry within a preset."""
    path: str = ""
    redundancy_type: int = Field(0, alias="redundancy-type")
    container_type: int = Field(0, alias="container-type")
    file_buffer_size: int = Field(0, alias="file-buffer-size")
    path_type: int = Field(0, alias="path-type")

    model_config = {"populate_by_name": True}


class JustInDestinationPresetDetail(BaseModel):
    """The inner preset detail from /ingest/requestLoadDestinationPreset."""
    name: str = ""
    destination_path: List[JustInDestinationPath] = Field(default_factory=list, alias="destination-path")

    model_config = {"populate_by_name": True}


class JustInLoadDestinationPresetResponse(BaseModel):
    """Response from /ingest/requestLoadDestinationPreset."""
    destination_preset_id: int = Field(0, alias="destination-preset-id")
    channel: str
    name: str
    justin_destination_preset: JustInDestinationPresetDetail = Field(
        default_factory=JustInDestinationPresetDetail,
        alias="justin-destination-preset"
    )

    model_config = {"populate_by_name": True}


class ChannelState(BaseModel):
    """
    Internal 'Single Source of Truth' for a channel.
    
    This represents the current state of a Just In Engine channel
    as tracked by our application.
    """
    name: str
    is_recording: bool = False
    has_signal: bool = True
    has_errors: bool = False
    last_errors: List[JustInError] = []
    
    # Additional metadata (current timecode)
    frames: Optional[int] = None
    hours: Optional[int] = None
    minutes: Optional[int] = None
    seconds: Optional[int] = None

    # Timecode origin (needed for duration calculation)
    start_timecode_frames: Optional[int] = None
    framerate: Optional[int] = None  # Justin reports e.g. 2500 = 25.00 fps