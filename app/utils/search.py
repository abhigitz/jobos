"""Search-related utilities."""


def escape_like(value: str) -> str:
    """Escape special LIKE characters (% and _) for safe SQL LIKE queries."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
