from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('DATA_DIR', '/data')).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

# v2.7.4: fall back to settings.json.example when settings.json is absent
# (settings.json is gitignored and excluded from deployments)
_SETTINGS_JSON_PATH = BASE_DIR / 'settings.json'
_SETTINGS_EXAMPLE_PATH = BASE_DIR / 'settings.json.example'
DEFAULT_SETTINGS_PATH = _SETTINGS_JSON_PATH if _SETTINGS_JSON_PATH.exists() else _SETTINGS_EXAMPLE_PATH
SETTINGS_FILE = DATA_DIR / 'settings.json'
SECRETS_JSON_PATH = BASE_DIR / 'secrets.json'


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            with path.open('r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as exc:
        logger.warning('Failed to read %s: %s', path, exc)
    return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)


def ensure_persistent_settings() -> Path:
    # Always read the bundled defaults shipped with the code.
    default_settings = _read_json(DEFAULT_SETTINGS_PATH, {})
    if not isinstance(default_settings, dict):
        default_settings = {}

    # v2.7: safety-critical keys are always force-synced from the bundled
    # defaults on every deploy — same mechanism as bot_name.  This corrects
    # stale volume values (e.g. caps set to 999 from an old "caps off" build)
    # without requiring the operator to manually edit the Railway volume file.
    _FORCE_SYNC_KEYS = {
        'max_losing_trades_day',
        'max_losing_trades_session',
        'max_trades_day',
        'loss_streak_cooldown_min',
        'min_reentry_wait_min',
        'breakeven_enabled',
        'signal_threshold',
        'max_trades_london',
        'max_trades_us',
        'rr_ratio',
        'tp_pct',
        'xau_margin_rate_override',
        'position_full_usd',
        'position_partial_usd',
        'session_thresholds',
        'instrument',
        'timeframe',
        'cpr_narrow_pct',
        'cpr_wide_pct',
        'sma_short_period',
        'sma_long_period',
        'atr_period',
        'dead_zone_start_hour',
        'dead_zone_end_hour',
        'london_session_start',
        'london_session_end',
        'us_session_start',
        'us_session_end',
        'bot_version',
        'post_tp_cooldown_min',
        'gap_filter_pct',
        'gap_filter_wait_min',
        'post_sl_direction_block_count',
        'post_sl_direction_block_min',
        'enforce_min_rr',
        'london_session_end',
        'daily_trend_filter_enabled',
        'daily_trend_filter_days',
        'cpr_wide_pct',
        'intraday_bias_pct',
    }

    if SETTINGS_FILE.exists():
        # Merge: inject any keys present in the bundled defaults that are
        # missing from the persistent volume file (e.g. after a deployment
        # that adds new settings keys).
        persistent = _read_json(SETTINGS_FILE, {})
        if not isinstance(persistent, dict):
            persistent = {}
        new_keys = {k: v for k, v in default_settings.items() if k not in persistent}
        changed = dict(new_keys)

        # bot_name is a version indicator — always sync from bundled defaults.
        bundled_bot_name = default_settings.get('bot_name')
        if bundled_bot_name and persistent.get('bot_name') != bundled_bot_name:
            changed['bot_name'] = bundled_bot_name

        # Safety-critical keys — always sync from bundled defaults so a deploy
        # automatically corrects stale or unsafe volume values.
        for key in _FORCE_SYNC_KEYS:
            bundled_val = default_settings.get(key)
            if bundled_val is not None and persistent.get(key) != bundled_val:
                changed[key] = bundled_val

        if changed:
            persistent.update(changed)
            _write_json(SETTINGS_FILE, persistent)
            logger.info(
                'Updated %d key(s) in persistent settings: %s',
                len(changed), list(changed.keys()),
            )
        return SETTINGS_FILE

    # First boot — bootstrap the persistent file from bundled defaults.
    default_settings.setdefault('bot_name', 'CPR Gold Bot')
    default_settings.setdefault('cycle_minutes', 5)
    default_settings.setdefault('db_retention_days', 90)
    default_settings.setdefault('db_cleanup_hour_sgt', 0)
    default_settings.setdefault('db_cleanup_minute_sgt', 15)
    default_settings.setdefault('db_vacuum_weekly', True)
    default_settings.setdefault('calendar_fetch_interval_min', 60)
    default_settings.setdefault('calendar_retry_after_min', 15)
    # Ensure validate_settings() required keys are always present with safe defaults.
    default_settings.setdefault('spread_limits', {'London': 130, 'US': 130})
    default_settings.setdefault('max_trades_day', 20)
    default_settings.setdefault('max_losing_trades_day', 8)
    default_settings.setdefault('max_losing_trades_session', 4)
    default_settings.setdefault('loss_streak_cooldown_min', 30)
    default_settings.setdefault('min_reentry_wait_min', 5)
    default_settings.setdefault('breakeven_enabled', False)
    default_settings.setdefault('signal_threshold', 5)
    default_settings.setdefault('max_trades_london', 10)
    default_settings.setdefault('max_trades_us', 10)
    default_settings.setdefault('rr_ratio', 2.65)
    default_settings.setdefault('tp_pct', 0.006625)
    default_settings.setdefault('xau_margin_rate_override', 0.20)
    default_settings.setdefault('position_full_usd', 15)
    default_settings.setdefault('position_partial_usd', 10)
    default_settings.setdefault('session_thresholds', {'London': 4, 'US': 4})
    default_settings.setdefault('instrument',            'XAU_USD')
    default_settings.setdefault('timeframe',             'M15')
    default_settings.setdefault('cpr_narrow_pct',        0.5)
    default_settings.setdefault('cpr_wide_pct',          1.0)
    default_settings.setdefault('sma_short_period',      20)
    default_settings.setdefault('sma_long_period',       50)
    default_settings.setdefault('atr_period',            14)
    default_settings.setdefault('dead_zone_start_hour',  1)
    default_settings.setdefault('dead_zone_end_hour',    15)
    default_settings.setdefault('london_session_start',  16)
    default_settings.setdefault('london_session_end',    20)
    default_settings.setdefault('us_session_start',      21)
    default_settings.setdefault('us_session_end',        23)
    default_settings.setdefault('us_cont_session_start', 0)
    default_settings.setdefault('bot_version',           '3.9')
    default_settings.setdefault('intraday_bias_pct',     0.5)
    default_settings.setdefault('daily_trend_filter_enabled', True)
    default_settings.setdefault('daily_trend_filter_days',    3)
    default_settings.setdefault('post_tp_cooldown_min',  20)
    default_settings.setdefault('gap_filter_pct',        2.0)
    default_settings.setdefault('gap_filter_wait_min',   30)
    default_settings.setdefault('post_sl_direction_block_count', 2)
    default_settings.setdefault('post_sl_direction_block_min',   60)
    default_settings.setdefault('enforce_min_rr',        True)
    default_settings.setdefault('london_session_end',    20)
    default_settings.setdefault('sl_mode', 'pct_based')
    default_settings.setdefault('tp_mode', 'rr_multiple')
    _write_json(SETTINGS_FILE, default_settings)
    logger.info('Bootstrapped persistent settings -> %s', SETTINGS_FILE)
    return SETTINGS_FILE


# ── load_settings cache (M-06 fix) ────────────────────────────────────────────
# Avoids re-reading disk on every call. Cache is invalidated when the file's
# modification time changes — so manual edits to settings.json take effect
# on the very next cycle without restarting the bot.
_settings_cache: dict = {}
_settings_mtime: float = 0.0


def load_settings() -> dict:
    global _settings_cache, _settings_mtime
    ensure_persistent_settings()

    try:
        mtime = SETTINGS_FILE.stat().st_mtime
    except OSError:
        mtime = 0.0

    if _settings_cache and mtime == _settings_mtime:
        return _settings_cache  # file unchanged — skip disk read

    settings = _read_json(SETTINGS_FILE, {})
    if not isinstance(settings, dict):
        settings = {}

    original_keys = set(settings.keys())

    settings.setdefault('bot_name', 'CPR Gold Bot')
    settings.setdefault('enabled', True)
    settings.setdefault('cycle_minutes', 5)
    settings.setdefault('db_retention_days', 90)
    settings.setdefault('db_cleanup_hour_sgt', 0)
    settings.setdefault('db_cleanup_minute_sgt', 15)
    settings.setdefault('db_vacuum_weekly', True)
    settings.setdefault('calendar_fetch_interval_min', 60)
    settings.setdefault('calendar_retry_after_min', 15)

    # ── Keys required by validate_settings() in bot.py ──────────────────────
    # Guard against old persistent settings.json files that pre-date these
    # fields being made mandatory. Uses safe production defaults — never 999.
    settings.setdefault('spread_limits', {'London': 130, 'US': 130})
    settings.setdefault('max_trades_day', 20)
    settings.setdefault('max_losing_trades_day', 8)
    settings.setdefault('max_losing_trades_session', 4)
    settings.setdefault('loss_streak_cooldown_min', 30)
    settings.setdefault('min_reentry_wait_min', 5)
    settings.setdefault('breakeven_enabled', False)
    settings.setdefault('signal_threshold', 5)
    settings.setdefault('max_trades_london', 10)
    settings.setdefault('max_trades_us', 10)
    settings.setdefault('rr_ratio', 2.65)
    settings.setdefault('tp_pct', 0.006625)
    settings.setdefault('xau_margin_rate_override', 0.20)
    settings.setdefault('position_full_usd', 15)
    settings.setdefault('position_partial_usd', 10)
    settings.setdefault('session_thresholds', {'London': 4, 'US': 4})
    settings.setdefault('instrument',            'XAU_USD')
    settings.setdefault('timeframe',             'M15')
    settings.setdefault('cpr_narrow_pct',        0.5)
    settings.setdefault('cpr_wide_pct',          1.0)
    settings.setdefault('sma_short_period',      20)
    settings.setdefault('sma_long_period',       50)
    settings.setdefault('atr_period',            14)
    settings.setdefault('dead_zone_start_hour',  1)
    settings.setdefault('dead_zone_end_hour',    15)
    settings.setdefault('london_session_start',  16)
    settings.setdefault('london_session_end',    20)
    settings.setdefault('us_session_start',      21)
    settings.setdefault('us_session_end',        23)
    settings.setdefault('us_cont_session_start', 0)
    settings.setdefault('bot_version',           '3.9')
    settings.setdefault('intraday_bias_pct',     0.5)
    settings.setdefault('daily_trend_filter_enabled', True)
    settings.setdefault('daily_trend_filter_days',    3)
    settings.setdefault('post_tp_cooldown_min',  20)
    settings.setdefault('gap_filter_pct',        2.0)
    settings.setdefault('gap_filter_wait_min',   30)
    settings.setdefault('post_sl_direction_block_count', 2)
    settings.setdefault('post_sl_direction_block_min',   60)
    settings.setdefault('enforce_min_rr',        True)
    settings.setdefault('london_session_end',    20)
    settings.setdefault('sl_mode', 'pct_based')
    settings.setdefault('tp_mode', 'rr_multiple')

    if set(settings.keys()) != original_keys:
        _write_json(SETTINGS_FILE, settings)

    _settings_cache = settings
    _settings_mtime = mtime
    return settings


def save_settings(settings: dict) -> None:
    _write_json(SETTINGS_FILE, settings)
    logger.info('Saved settings -> %s', SETTINGS_FILE)


def load_secrets() -> dict:
    """Load secrets with environment variables taking priority over secrets.json."""
    file_secrets: dict = {}
    if SECRETS_JSON_PATH.exists():
        loaded = _read_json(SECRETS_JSON_PATH, {})
        if isinstance(loaded, dict):
            file_secrets = loaded

    return {
        'OANDA_API_KEY':    os.environ.get('OANDA_API_KEY')    or file_secrets.get('OANDA_API_KEY',    ''),
        'OANDA_ACCOUNT_ID': os.environ.get('OANDA_ACCOUNT_ID') or file_secrets.get('OANDA_ACCOUNT_ID', ''),
        'TELEGRAM_TOKEN':   os.environ.get('TELEGRAM_TOKEN')   or file_secrets.get('TELEGRAM_TOKEN',   ''),
        'TELEGRAM_CHAT_ID': os.environ.get('TELEGRAM_CHAT_ID') or file_secrets.get('TELEGRAM_CHAT_ID', ''),
        'DATA_DIR':         str(DATA_DIR),
    }


def get_bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}
