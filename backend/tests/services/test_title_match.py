"""Different-album discriminator shared by the Usenet + Soulseek scorers.

``names_different_album`` keeps a request for one album from matching every OTHER album by
the same artist (the Led Zeppelin debut vs II/III/IV, Houses of the Holy, In Through the
Out Door...) - the failure that made the picker burn a download per wrong album and exhaust
before reaching the one requested. Cases below are drawn from real Newznab/Soulseek titles.
"""

from services.native.title_match import fold, names_different_album, strip_featuring


def test_fold_accents_and_case_but_keeps_cjk():
    assert fold("Mötley Crüe") == "motley crue"
    assert fold("Sigur Rós") == "sigur ros"
    assert fold("Beyoncé") == "beyonce"
    assert fold("林宥嘉 神秘嘉宾") == "林宥嘉 神秘嘉宾"  # CJK left intact, not romanised


def test_strip_featuring():
    assert strip_featuring("Crazy in Love (feat. Jay-Z)") == "Crazy in Love"
    assert strip_featuring("Song ft. Someone") == "Song"
    assert strip_featuring("Soft Machine") == "Soft Machine"  # 'ft' inside a word is untouched


def test_accented_artist_is_recognised_so_the_guard_still_discriminates():
    # Before accent-folding the guard failed OPEN on accented artists (artist "not present"),
    # so it stopped rejecting wrong albums for them. Now it discriminates correctly.
    assert names_different_album("Dr. Feelgood", "Mötley Crüe", "Motley Crue - Theatre of Pain (1985) [FLAC]")
    assert not names_different_album("Dr. Feelgood", "Mötley Crüe", "Motley_Crue-Dr_Feelgood-LP-FLAC-1989-GRP")


def test_featured_artist_is_not_read_as_a_foreign_album_word():
    # The featured artist must not count as an extra album word that wrongly rejects the match.
    assert not names_different_album(
        "Crazy in Love", "Beyoncé", "Beyonce - Crazy in Love (feat. Jay-Z) [FLAC]"
    )

_LZ = "Led Zeppelin"  # self-titled: album == artist, the hard case (album adds no discriminator)


def test_self_titled_debut_rejects_other_studio_albums():
    # The exact failing titles: every one is a DIFFERENT album, not the requested debut.
    for cand in (
        "led_zeppelin-led_zeppelin_ii-lp-32bit-wavpack-1969-reetkever",
        "Led_Zeppelin-In_Through_The_Out_Door-LP-24BIT-FLAC-1979-REETKEVER",
        "Led_Zeppelin-Houses_Of_The_Holy-LP-32BIT-WAVPACK-1973-REETKEVER",
        "Led_Zeppelin-Physical_Graffiti-2LP-24BIT-FLAC-1975-REETKEVER",
        "Led_Zeppelin-Presence-LP-US-Edition-24BIT-FLAC-1976-BITOCUL",
        "Led_Zeppelin-Coda-LP-32BIT-WAVPACK-1982-REETKEVER",
    ):
        assert names_different_album(_LZ, _LZ, cand), cand


def test_self_titled_debut_accepts_the_debut_including_editions():
    # Clean release, a year-suffixed name, and a deluxe/remaster are all the requested album.
    for cand in (
        "Led_Zeppelin-Led_Zeppelin-LP-24BIT-FLAC-1968-REETKEVER",
        "Led_Zeppelin-Led_Zeppelin_1969-CD-FLAC-1994-GP-FLAC",
        "Led_Zeppelin-Led_Zeppelin-24-96-WEB-FLAC-REMASTERED_DELUXE_EDITION-2014-GP-FLAC",
        "Led_Zeppelin-Led_Zeppelin-Remastered_Deluxe_Edition-2CD-FLAC-2014-GP-FLAC",
    ):
        assert not names_different_album(_LZ, _LZ, cand), cand


def test_usenet_part_counter_prefix_is_stripped():
    # The ``[002/113] "..."`` part counter's digits must not trip the format boundary at
    # position 0 (which would blank the album and wrongly accept every release).
    assert names_different_album(
        _LZ, _LZ, '[002/113] "Led_Zeppelin-Led_Zeppelin_II-LP-32BIT-WAVPACK-1969-REETKEVER.part001.rar"'
    )
    assert not names_different_album(
        _LZ, _LZ, '[002/112] "Led_Zeppelin-Led_Zeppelin-LP-24BIT-FLAC-1968-REETKEVER.part001.rar"'
    )


def test_requested_numbered_album_keeps_its_own_and_rejects_another():
    assert not names_different_album("Led Zeppelin IV", _LZ, "Led_Zeppelin-Led_Zeppelin_IV-LP-FLAC-1971-REETKEVER")
    assert names_different_album("Led Zeppelin IV", _LZ, "Led_Zeppelin-Led_Zeppelin_II-LP-FLAC-1969-REETKEVER")


def test_obfuscated_release_passes_artist_absent():
    # Q4: a fully obfuscated title (no readable artist) is left alone - the indexer-match base
    # score + import tag-match settle it, so it must NOT be rejected here.
    assert not names_different_album("Led Zeppelin IV", _LZ, "aHR0cHM6 scrambled xQ.part01.rar")


def test_missing_marker_is_not_rejected_so_obfuscated_numbered_album_passes():
    # Requesting a numbered album must not reject an artist-named release that omits the numeral.
    assert not names_different_album("Led Zeppelin IV", _LZ, "Led Zeppelin (1971) [FLAC]")


def test_artist_numbered_in_its_name_does_not_reject_its_own_album():
    # The roman in the ARTIST name is part of the artist, so it can't read as a foreign word.
    assert not names_different_album("Some Album", "Apollo IV", "Apollo IV - Some Album [FLAC]")


def test_different_named_album_rejected_for_named_request():
    # A normal (non-self-titled) request still rejects a different album by the same artist.
    assert names_different_album("Houses of the Holy", _LZ, "Led_Zeppelin-Physical_Graffiti-2LP-FLAC-1975")
    assert not names_different_album(
        "Houses of the Holy", _LZ, "Led_Zeppelin-Houses_Of_The_Holy-Remastered_Deluxe_Edition-2CD-FLAC-2014"
    )


def test_numeric_album_title_matches_only_its_own():
    # A digit-only title ("1989") has no album WORDS; only a same-named release (no foreign
    # words) matches, a differently-named one is rejected.
    assert not names_different_album("1989", "Taylor Swift", "Taylor_Swift-1989-CD-FLAC-2014-GROUP")
    assert names_different_album("1989", "Taylor Swift", "Taylor_Swift-Red-CD-FLAC-2012-GROUP")


def test_soulseek_folder_style_directory():
    # Soulseek parents are "Artist Album Year" / "Artist - Album" folders, not scene names.
    assert not names_different_album("OK Computer", "Radiohead", "Radiohead OK Computer 1997")
    assert names_different_album("OK Computer", "Radiohead", "Radiohead - In Rainbows")


def test_edition_version_descriptors_are_not_a_different_album():
    # Regression (step 3 verify): rip album tags routinely carry these; they're the SAME album,
    # not a different one. None may read as a foreign album word.
    for suffix in [
        "Deluxe Version", "Remastered Version", "Explicit", "Clean", "Extended Edition",
        "Standard Edition", "Promo", "Disc 2", "Deluxe", "Special Edition",
    ]:
        assert not names_different_album(
            "Born This Way", "Lady Gaga", f"Lady Gaga Born This Way ({suffix})"
        ), suffix


def test_numbered_sequel_still_rejected_after_edition_additions():
    # The discrimination that matters must still hold.
    assert names_different_album("Led Zeppelin", "Led Zeppelin", "Led Zeppelin Led Zeppelin II")
    assert names_different_album("OK Computer", "Radiohead", "Radiohead Kid A")
