from io import BytesIO

from PIL import Image
import pytest

from core.exceptions import ArtworkProcessingError
from infrastructure.audio.artwork_processor import ArtworkProcessor
from models.library_management_artwork import ArtworkCandidate


def _candidate() -> ArtworkCandidate:
    return ArtworkCandidate(
        candidate_id="test-image",
        source="local_files",
        locator="cover.png",
        image_types=("front",),
        approved=True,
        primary=True,
    )


def _image_bytes(
    width: int = 20,
    height: int = 10,
    *,
    image_format: str = "PNG",
    mode: str = "RGB",
) -> bytes:
    output = BytesIO()
    Image.new(mode, (width, height), (20, 80, 140)).save(output, format=image_format)
    return output.getvalue()


@pytest.mark.asyncio
async def test_inspection_sniffs_actual_mime_and_rejects_mismatch() -> None:
    processor = ArtworkProcessor()
    content = _image_bytes()

    inspected = await processor.inspect(
        _candidate(), content, declared_mime_type="image/png; charset=binary"
    )

    assert inspected.mime_type == "image/png"
    assert (inspected.width, inspected.height) == (20, 10)
    assert inspected.byte_size == len(content)
    with pytest.raises(ArtworkProcessingError, match="MIME"):
        await processor.inspect(_candidate(), content, declared_mime_type="image/jpeg")


@pytest.mark.asyncio
async def test_invalid_bytes_and_byte_or_decompression_limits_are_rejected() -> None:
    with pytest.raises(ArtworkProcessingError, match="safe raster"):
        await ArtworkProcessor().inspect(_candidate(), b"not an image")
    with pytest.raises(ArtworkProcessingError, match="byte safety"):
        await ArtworkProcessor(maximum_input_bytes=10).inspect(
            _candidate(), _image_bytes()
        )
    with pytest.raises(ArtworkProcessingError, match="decompression safety"):
        await ArtworkProcessor(maximum_pixels=100).inspect(
            _candidate(), _image_bytes(11, 10)
        )


@pytest.mark.asyncio
async def test_resize_never_upscales_and_conversion_is_reinspected() -> None:
    processor = ArtworkProcessor()
    original = await processor.inspect(_candidate(), _image_bytes(20, 10))

    unchanged = await processor.process(
        original,
        output_kind="external",
        image_type="front",
        maximum_size=100,
        output_format="original",
    )
    converted = await processor.process(
        original,
        output_kind="embedded",
        image_type="front",
        maximum_size=8,
        output_format="jpeg",
    )

    assert unchanged.content == original.content
    assert (unchanged.width, unchanged.height) == (20, 10)
    assert converted.mime_type == "image/jpeg"
    assert converted.format == "jpeg"
    assert (converted.width, converted.height) == (8, 4)
    assert converted.content.startswith(b"\xff\xd8\xff")


@pytest.mark.asyncio
async def test_pdf_is_validated_for_external_original_only() -> None:
    processor = ArtworkProcessor()
    inspected = await processor.inspect(
        _candidate(),
        b"%PDF-1.4\n1 0 obj\nendobj\n%%EOF\n",
        declared_mime_type="application/pdf",
    )

    external = await processor.process(
        inspected,
        output_kind="external",
        image_type="booklet",
        maximum_size=0,
        output_format="original",
    )

    assert inspected.external_only is True
    assert external.mime_type == "application/pdf"
    with pytest.raises(ArtworkProcessingError, match="cannot be embedded"):
        await processor.process(
            inspected,
            output_kind="embedded",
            image_type="booklet",
            maximum_size=0,
            output_format="original",
        )
    with pytest.raises(ArtworkProcessingError, match="incomplete"):
        await processor.inspect(_candidate(), b"%PDF-1.4\n")
