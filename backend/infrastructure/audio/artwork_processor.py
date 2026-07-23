"""Bounded inspection and deterministic processing for management artwork."""

from __future__ import annotations

import asyncio
from io import BytesIO
import hashlib
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from core.exceptions import ArtworkProcessingError
from models.library_management_artwork import (
    ArtworkCandidate,
    ArtworkFormat,
    ArtworkImageType,
    ArtworkOutput,
    ArtworkOutputKind,
    ArtworkProcessingFormat,
    InspectedArtwork,
)

MAX_ARTWORK_INPUT_BYTES = 50 * 1024 * 1024
MAX_ARTWORK_PIXELS = 100_000_000

_FORMAT_BY_PIL: dict[str, ArtworkFormat] = {
    "JPEG": "jpeg",
    "PNG": "png",
    "WEBP": "webp",
    "GIF": "gif",
}
_MIME_BY_FORMAT: dict[ArtworkFormat, str] = {
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "pdf": "application/pdf",
}
_PIL_BY_FORMAT: dict[ArtworkFormat, str] = {
    "jpeg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "gif": "GIF",
}


class ArtworkProcessor:
    def __init__(
        self,
        *,
        maximum_input_bytes: int = MAX_ARTWORK_INPUT_BYTES,
        maximum_pixels: int = MAX_ARTWORK_PIXELS,
    ) -> None:
        if maximum_input_bytes <= 0 or maximum_pixels <= 0:
            raise ValueError("Artwork safety limits must be positive.")
        self.maximum_input_bytes = maximum_input_bytes
        self.maximum_pixels = maximum_pixels

    async def inspect(
        self,
        candidate: ArtworkCandidate,
        content: bytes,
        *,
        declared_mime_type: str | None = None,
    ) -> InspectedArtwork:
        return await asyncio.to_thread(
            self._inspect_sync,
            candidate,
            content,
            declared_mime_type,
        )

    async def process(
        self,
        artwork: InspectedArtwork,
        *,
        output_kind: ArtworkOutputKind,
        image_type: ArtworkImageType,
        maximum_size: int,
        output_format: ArtworkProcessingFormat,
    ) -> ArtworkOutput:
        return await asyncio.to_thread(
            self._process_sync,
            artwork,
            output_kind,
            image_type,
            maximum_size,
            output_format,
        )

    def _inspect_sync(
        self,
        candidate: ArtworkCandidate,
        content: bytes,
        declared_mime_type: str | None,
    ) -> InspectedArtwork:
        if not content or len(content) > self.maximum_input_bytes:
            raise ArtworkProcessingError("Artwork exceeds the byte safety limit.")
        declared = (
            declared_mime_type.partition(";")[0].strip().casefold()
            if declared_mime_type
            else None
        )
        if content.startswith(b"%PDF-"):
            if b"%%EOF" not in content[-1024:]:
                raise ArtworkProcessingError("Artwork PDF is incomplete.")
            if declared not in (None, "application/pdf", "application/octet-stream"):
                raise ArtworkProcessingError("Artwork MIME does not match its bytes.")
            return InspectedArtwork(
                candidate=candidate,
                content=content,
                mime_type="application/pdf",
                format="pdf",
                width=None,
                height=None,
                byte_size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                external_only=True,
            )

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as image:
                    pil_format = image.format
                    width, height = image.size
                    if width <= 0 or height <= 0:
                        raise ArtworkProcessingError(
                            "Artwork dimensions must be positive."
                        )
                    if width * height > self.maximum_pixels:
                        raise ArtworkProcessingError(
                            "Artwork exceeds the decompression safety limit."
                        )
                    image.verify()
                with Image.open(BytesIO(content)) as image:
                    image.load()
                    oriented = ImageOps.exif_transpose(image)
                    width, height = oriented.size
        except ArtworkProcessingError:
            raise
        except (
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            ValueError,
        ) as error:
            raise ArtworkProcessingError(
                "Artwork is not a safe raster image."
            ) from error

        if pil_format not in _FORMAT_BY_PIL:
            raise ArtworkProcessingError("Artwork format is not supported.")
        image_format = _FORMAT_BY_PIL[pil_format]
        actual_mime = _MIME_BY_FORMAT[image_format]
        if declared not in (None, actual_mime, "application/octet-stream"):
            raise ArtworkProcessingError("Artwork MIME does not match its bytes.")
        return InspectedArtwork(
            candidate=candidate,
            content=content,
            mime_type=actual_mime,
            format=image_format,
            width=width,
            height=height,
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )

    def _process_sync(
        self,
        artwork: InspectedArtwork,
        output_kind: ArtworkOutputKind,
        image_type: ArtworkImageType,
        maximum_size: int,
        output_format: ArtworkProcessingFormat,
    ) -> ArtworkOutput:
        if output_kind == "embedded" and artwork.external_only:
            raise ArtworkProcessingError("PDF artwork cannot be embedded.")
        if maximum_size < 0:
            raise ArtworkProcessingError("Artwork output size cannot be negative.")
        if output_format not in {"original", "jpeg", "png", "webp"}:
            raise ArtworkProcessingError("Artwork output format is unsupported.")

        if artwork.format == "pdf":
            if output_format != "original" or maximum_size:
                raise ArtworkProcessingError(
                    "PDF artwork cannot be resized or converted."
                )
            return self._output(artwork, output_kind, image_type, artwork)

        output_formats: dict[ArtworkProcessingFormat, ArtworkFormat] = {
            "original": artwork.format,
            "jpeg": "jpeg",
            "png": "png",
            "webp": "webp",
        }
        target_format = output_formats[output_format]
        resize_needed = bool(
            maximum_size
            and artwork.width is not None
            and artwork.height is not None
            and max(artwork.width, artwork.height) > maximum_size
        )
        if not resize_needed and target_format == artwork.format:
            return self._output(artwork, output_kind, image_type, artwork)

        try:
            with Image.open(BytesIO(artwork.content)) as source:
                source.load()
                image = ImageOps.exif_transpose(source)
                if resize_needed:
                    image.thumbnail(
                        (maximum_size, maximum_size), Image.Resampling.LANCZOS
                    )
                if target_format == "jpeg" and image.mode not in ("RGB", "L"):
                    flattened = Image.new("RGB", image.size, "white")
                    if image.mode in ("RGBA", "LA"):
                        flattened.paste(image, mask=image.getchannel("A"))
                    else:
                        flattened.paste(image.convert("RGB"))
                    image = flattened
                output = BytesIO()
                save_options: dict[str, object] = {}
                if target_format == "jpeg":
                    save_options = {"quality": 90, "optimize": True}
                elif target_format == "png":
                    save_options = {"optimize": True}
                elif target_format == "webp":
                    save_options = {"quality": 90, "method": 4}
                image.save(output, format=_PIL_BY_FORMAT[target_format], **save_options)
                processed_content = output.getvalue()
        except (KeyError, OSError, ValueError) as error:
            raise ArtworkProcessingError("Artwork processing failed.") from error

        processed = self._inspect_sync(
            artwork.candidate,
            processed_content,
            _MIME_BY_FORMAT[target_format],
        )
        return self._output(artwork, output_kind, image_type, processed)

    @staticmethod
    def _output(
        source: InspectedArtwork,
        output_kind: ArtworkOutputKind,
        image_type: ArtworkImageType,
        processed: InspectedArtwork,
    ) -> ArtworkOutput:
        return ArtworkOutput(
            output_kind=output_kind,
            image_type=image_type,
            content=processed.content,
            mime_type=processed.mime_type,
            format=processed.format,
            width=processed.width,
            height=processed.height,
            byte_size=processed.byte_size,
            sha256=processed.sha256,
            source=source.candidate.source,
            source_candidate_id=source.candidate.candidate_id,
            source_is_exact_release=source.candidate.source_is_exact_release,
            description=source.candidate.description,
        )
