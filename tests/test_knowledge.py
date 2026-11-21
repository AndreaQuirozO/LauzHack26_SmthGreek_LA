from app.knowledge import (
    get_migration_notes,
    get_roles,
    get_software_history,
    get_sources,
)


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


def test_each_role_has_a_software_history_with_expected_fields() -> None:
    required_fields = {"name", "vendor", "category", "years_used", "proficiency"}
    for role in get_roles():
        history = get_software_history(role["id"])
        assert history, f"role {role['id']} has no software history"
        for software in history:
            assert required_fields.issubset(software)
            assert isinstance(software["years_used"], int)


def test_unknown_role_has_empty_software_history() -> None:
    assert get_software_history("does_not_exist") == []