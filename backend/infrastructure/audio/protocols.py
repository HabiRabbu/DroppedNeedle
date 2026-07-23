from pathlib import Path
from typing import Protocol

from models.audio_metadata import (
    FileAttributeSnapshot,
    FormatCapabilities,
    FormatProbe,
    ReadAudioDocument,
)


class AudioReadAdapterProtocol(Protocol):
    capabilities: FormatCapabilities

    def read(
        self,
        path: Path,
        audio: object,
        probe: FormatProbe,
        file_attributes: FileAttributeSnapshot,
    ) -> ReadAudioDocument: ...
