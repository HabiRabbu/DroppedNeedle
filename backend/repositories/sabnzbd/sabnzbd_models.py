"""msgspec models for the SABnzbd API.

Modelled on the owner's real SABnzbd 5.0.4 responses (curl-captured this session) +
Lidarr's ``Sabnzbd*`` models. SABnzbd's JSON is **stringly-typed** for queue numbers
(``mb``/``mbleft``/``percentage`` arrive as strings) but history ``bytes`` is a real
number; the structs keep the raw types and the client/repository coerces. ``nzo_id``
is an opaque string (a plain UUID on 5.0.4, e.g. ``bc648058-…``).
"""

import msgspec

from infrastructure.msgspec_fastapi import AppStruct


class SabnzbdAddResponse(AppStruct):
    """``mode=addfile`` / ``addurl`` response: ``{"status": true, "nzo_ids": [...]}``.
    Empty ``nzo_ids`` ⇒ SABnzbd rejected the NZB."""

    status: bool = False
    nzo_ids: list[str] = []


class SabnzbdQueueSlot(AppStruct):
    """In-progress job. ``filename`` is the job name (``droppedneedle-{task_id}``).
    ``mb``/``mbleft`` are decimal **megabytes** as strings; ``percentage`` int-as-string;
    ``priority`` a NAME string on read (``Normal``/``High``/…)."""

    nzo_id: str = ""
    status: str = ""
    filename: str = ""
    cat: str = ""
    # SABnzbd usually serialises these as strings, but some builds/fields emit JSON numbers
    # (the doc warns "arrive as numbers/strings - coerce"). Accept both so one number-typed
    # field can't crash the whole queue parse; _to_float/_to_int normalise either form.
    mb: str | float = "0"
    mbleft: str | float = "0"
    percentage: str | float = "0"
    timeleft: str = ""
    priority: str = ""


class SabnzbdQueue(AppStruct):
    status: str = ""
    paused: bool = False
    slots: list[SabnzbdQueueSlot] = []


class SabnzbdHistorySlot(AppStruct):
    """Finished / post-processing / failed job. ``name`` is the job name;
    ``storage`` is the final folder (SABnzbd namespace); ``bytes`` is already bytes;
    ``fail_message`` is set on ``Failed``."""

    nzo_id: str = ""
    name: str = ""
    nzb_name: str = ""
    status: str = ""
    category: str = ""
    storage: str = ""
    bytes: int = 0
    fail_message: str = ""
    password: str | None = None
    download_time: int = 0
    completed: int = 0


class SabnzbdHistory(AppStruct):
    slots: list[SabnzbdHistorySlot] = []


class SabnzbdCategory(AppStruct):
    name: str = ""
    dir: str = ""
    pp: str = ""


class SabnzbdMisc(AppStruct):
    complete_dir: str = ""


class SabnzbdConfig(AppStruct):
    """``mode=get_config`` → ``config.misc.complete_dir`` (the mount-remap prefix) +
    ``config.categories[].name`` (the category picker)."""

    misc: SabnzbdMisc = msgspec.field(default_factory=SabnzbdMisc)
    categories: list[SabnzbdCategory] = []
