CREATE TABLE auth_users (id TEXT PRIMARY KEY, display_name TEXT);
CREATE TABLE library_files (
    id TEXT PRIMARY KEY, download_task_id TEXT, release_group_mbid TEXT,
    release_mbid TEXT, recording_mbid TEXT, disc_number INTEGER,
    track_number INTEGER, track_title TEXT, artist_name TEXT, artist_mbid TEXT,
    album_artist_name TEXT, album_artist_mbid TEXT, album_title TEXT, year INTEGER,
    file_path TEXT, source_path TEXT, file_size_bytes INTEGER, file_mtime REAL,
    duration_seconds REAL, file_format TEXT, bit_rate INTEGER, sample_rate INTEGER,
    bit_depth INTEGER, channels INTEGER, source TEXT, is_compilation INTEGER,
    deleted_at REAL, tagged_at REAL, imported_at REAL, genre TEXT,
    track_sort_name TEXT, artist_sort_name TEXT, album_sort_name TEXT,
    album_artist_sort_name TEXT, disc_subtitle TEXT, original_release_date TEXT,
    replaygain_track_gain REAL, replaygain_album_gain REAL,
    replaygain_track_peak REAL, replaygain_album_peak REAL
);
CREATE TABLE manual_review_queue (
    id INTEGER PRIMARY KEY, file_path TEXT, extracted_title TEXT,
    extracted_artist TEXT, extracted_album TEXT, extracted_year INTEGER,
    track_number INTEGER, disc_number INTEGER, file_format TEXT, duration REAL,
    file_size INTEGER, fingerprint TEXT, fingerprint_score REAL,
    candidate_mbids_encoded TEXT, source TEXT, created_at REAL,
    resolved_at REAL, resolution TEXT
);
CREATE TABLE library_albums (
    mbid_lower TEXT PRIMARY KEY, mbid TEXT, artist_mbid TEXT,
    artist_mbid_lower TEXT, artist_name TEXT, title TEXT, year INTEGER,
    cover_url TEXT, date_added INTEGER, raw_json TEXT
);
CREATE TABLE library_artists (
    mbid_lower TEXT PRIMARY KEY, mbid TEXT, name TEXT, album_count INTEGER,
    date_added INTEGER, raw_json TEXT
);
CREATE TABLE library_album_meta (
    release_group_mbid TEXT PRIMARY KEY, cover_url TEXT, last_cover_refresh_at REAL
);
CREATE TABLE user_favorites (
    user_id TEXT, item_kind TEXT, item_id TEXT, created_at REAL,
    PRIMARY KEY(user_id, item_kind, item_id)
);
CREATE TABLE play_history (
    id TEXT PRIMARY KEY, user_id TEXT, track_name TEXT, artist_name TEXT,
    album_name TEXT, recording_mbid TEXT, release_group_mbid TEXT,
    duration_ms INTEGER, source TEXT, played_at TEXT
);
CREATE TABLE playlists (
    id TEXT PRIMARY KEY, name TEXT, cover_image_path TEXT, created_at TEXT,
    updated_at TEXT, source_ref TEXT
);
CREATE TABLE playlist_tracks (
    id TEXT PRIMARY KEY, playlist_id TEXT, position INTEGER, track_name TEXT,
    artist_name TEXT, album_name TEXT, album_id TEXT, artist_id TEXT,
    track_source_id TEXT, cover_url TEXT, source_type TEXT,
    available_sources TEXT, format TEXT, track_number INTEGER, disc_number INTEGER,
    duration INTEGER, created_at TEXT, plex_rating_key TEXT, library_file_id TEXT
);
CREATE TABLE album_release_pins (
    release_group_mbid TEXT PRIMARY KEY, release_mbid TEXT,
    set_by_user_id TEXT, set_at TEXT
);
CREATE TABLE compat_bookmarks (
    user_id TEXT, file_id TEXT, position_ms INTEGER, comment TEXT,
    created_at REAL, changed_at REAL, PRIMARY KEY(user_id, file_id)
);
CREATE TABLE compat_play_queues (
    user_id TEXT PRIMARY KEY, current_index INTEGER, position_ms INTEGER,
    updated_at REAL, changed_by_client TEXT
);
CREATE TABLE compat_play_queue_items (
    user_id TEXT, item_index INTEGER, file_id TEXT,
    PRIMARY KEY(user_id, item_index)
);
CREATE TABLE compat_id_map (
    jf_id TEXT PRIMARY KEY, kind TEXT, internal_id TEXT,
    UNIQUE(kind, internal_id)
);
