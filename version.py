"""Version — single source of truth. Bot identity also in settings.json (v3.1+)."""
__version__ = "3.7"
BOT_NAME    = "CPR Gold Bot"

def get_version(settings: dict | None = None) -> str:
    if settings and settings.get("bot_version"):
        return str(settings["bot_version"])
    return __version__

def get_bot_name(settings: dict | None = None) -> str:
    if settings and settings.get("bot_name"):
        return str(settings["bot_name"])
    return BOT_NAME
