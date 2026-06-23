from typing import Protocol

from models.library import LibraryAlbum


class LibraryRepositoryProtocol(Protocol):
    """Forward-looking contract for the native library.

    Phase 3's ``LibraryManager`` implements this against ``library_files``.
    During the brownout it is satisfied by ``services.native.stubs.LibraryStub``.
    """

    def is_configured(self) -> bool:
        ...

    def is_library_empty(self) -> bool:
        ...

    async def has_album(self, mbid: str) -> bool:
        ...

    async def get_library_albums(self) -> list[LibraryAlbum]:
        ...

    async def get_library_album_mbids(self) -> set[str]:
        ...

    async def get_library_artist_mbids(self) -> set[str]:
        ...
