"""Bounded RIFF INFO parsing and staged-file rewriting for WAV metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import struct
import tempfile

from core.exceptions import AudioWriteError, UnsupportedAudioFormatError

_MAX_INFO_BYTES = 16 * 1024 * 1024
_COPY_CHUNK = 1024 * 1024


def _chunks(handle, file_size: int):
    position = 12
    while position + 8 <= file_size:
        handle.seek(position)
        header = handle.read(8)
        if len(header) != 8:
            raise UnsupportedAudioFormatError("The WAV chunk table is truncated.")
        chunk_id, chunk_size = struct.unpack("<4sI", header)
        data_offset = position + 8
        padded_size = chunk_size + (chunk_size & 1)
        if data_offset + padded_size > file_size:
            raise UnsupportedAudioFormatError("The WAV chunk table is invalid.")
        yield chunk_id, chunk_size, position, data_offset, padded_size
        position = data_offset + padded_size


def read_riff_info(path: Path) -> dict[str, tuple[str, ...]]:
    file_size = path.stat().st_size
    result: dict[str, list[str]] = {}
    total_info = 0
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE":
            raise UnsupportedAudioFormatError("The file is not a valid RIFF/WAVE file.")
        for chunk_id, chunk_size, _position, data_offset, _padded in _chunks(
            handle, file_size
        ):
            if chunk_id != b"LIST" or chunk_size < 4:
                continue
            handle.seek(data_offset)
            if handle.read(4) != b"INFO":
                continue
            remaining = chunk_size - 4
            total_info += remaining
            if total_info > _MAX_INFO_BYTES:
                raise UnsupportedAudioFormatError("The WAV INFO metadata is too large.")
            while remaining >= 8:
                sub_header = handle.read(8)
                key_bytes, value_size = struct.unpack("<4sI", sub_header)
                padded = value_size + (value_size & 1)
                if padded > remaining - 8:
                    raise UnsupportedAudioFormatError(
                        "The WAV INFO metadata is truncated."
                    )
                raw = handle.read(value_size)
                if value_size & 1:
                    handle.read(1)
                remaining -= 8 + padded
                try:
                    key = key_bytes.decode("ascii")
                except UnicodeDecodeError:
                    continue
                value = raw.rstrip(b"\x00").decode("utf-8", "replace").strip()
                if value:
                    result.setdefault(key, []).append(value)
    return {key: tuple(values) for key, values in result.items()}


def _encoded_info(values: Mapping[str, Sequence[str]]) -> bytes:
    payload = bytearray(b"INFO")
    for key in sorted(values):
        if len(key) != 4 or not key.isascii():
            raise AudioWriteError("A RIFF INFO key is invalid.")
        for value in values[key]:
            encoded = value.encode("utf-8") + b"\x00"
            if len(encoded) > _MAX_INFO_BYTES:
                raise AudioWriteError("A RIFF INFO value is too large.")
            payload.extend(key.encode("ascii"))
            payload.extend(struct.pack("<I", len(encoded)))
            payload.extend(encoded)
            if len(encoded) & 1:
                payload.extend(b"\x00")
    if len(payload) > _MAX_INFO_BYTES:
        raise AudioWriteError("The WAV INFO metadata is too large.")
    return bytes(payload)


def _copy_bytes(source, destination, count: int) -> None:
    remaining = count
    while remaining:
        chunk = source.read(min(remaining, _COPY_CHUNK))
        if not chunk:
            raise AudioWriteError("The WAV file changed during metadata writing.")
        destination.write(chunk)
        remaining -= len(chunk)


def write_riff_info(path: Path, values: Mapping[str, Sequence[str]]) -> None:
    info = _encoded_info(values)
    file_size = path.stat().st_size
    temporary_path: Path | None = None
    try:
        with path.open("rb") as source:
            header = source.read(12)
            if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE":
                raise AudioWriteError("The staged file is not RIFF/WAVE audio.")
            with tempfile.NamedTemporaryFile(
                prefix=f".{path.name}.",
                suffix=".riff.tmp",
                dir=path.parent,
                delete=False,
            ) as destination:
                temporary_path = Path(destination.name)
                destination.write(b"RIFF\x00\x00\x00\x00WAVE")
                copied_until = 12
                for chunk_id, chunk_size, position, data_offset, padded_size in _chunks(
                    source, file_size
                ):
                    copied_until = data_offset + padded_size
                    source.seek(data_offset)
                    is_info = (
                        chunk_id == b"LIST"
                        and chunk_size >= 4
                        and source.read(4) == b"INFO"
                    )
                    if is_info:
                        continue
                    source.seek(position)
                    _copy_bytes(source, destination, 8 + padded_size)
                if copied_until < file_size:
                    source.seek(copied_until)
                    _copy_bytes(source, destination, file_size - copied_until)
                if len(info) > 4:
                    destination.write(b"LIST")
                    destination.write(struct.pack("<I", len(info)))
                    destination.write(info)
                    if len(info) & 1:
                        destination.write(b"\x00")
                final_size = destination.tell()
                if final_size - 8 > 0xFFFFFFFF:
                    raise AudioWriteError("The WAV file exceeds the RIFF size limit.")
                destination.seek(4)
                destination.write(struct.pack("<I", final_size - 8))
                destination.flush()
                os.fsync(destination.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
