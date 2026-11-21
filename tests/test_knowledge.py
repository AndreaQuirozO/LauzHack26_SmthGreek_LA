from app.knowledge import get_migration_notes, get_sources


def test_migration_notes_reference_known_https_sources() -> None:
    sources = get_sources()
    source_ids = {source["id"] for source in sources}

    assert len(source_ids) == len(sources)
    assert all(source["url"].startswith("https://") for source in sources)
    assert all(source["version"] for source in sources)
    assert get_migration_notes()
    assert all(
        note["source_ids"] and set(note["source_ids"]).issubset(source_ids)
        for note in get_migration_notes()
    )