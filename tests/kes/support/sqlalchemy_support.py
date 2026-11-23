"""SQLAlchemy registration helpers for the KES integration suite."""


def register_kes_dialects() -> None:
    """Register the unified local asynckb KES dialect entry point."""
    from sqlalchemy.dialects import registry

    registry.register(
        "kingbase.asynckb",
        "asynckb.sa_dialect",
        "KESDialect_asynckb",
    )
