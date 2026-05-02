"""Optional anchorpy-backed account-data decoder.

When the BagsVault Anchor IDL JSON is available on disk
(``BAGSVAULT_IDL_PATH`` setting), this module loads it once per process
and exposes a high-level :meth:`AnchorDecoder.decode_account` that turns
base64 account data into a Python dict using anchorpy's :class:`Coder`.

When the IDL is *not* available — empty path, missing file, or anchorpy
import failure — the decoder degrades gracefully:
:meth:`decode_account` returns ``None`` and :meth:`decode_available`
returns ``False``. Callers (notably :class:`MerkleIndexer`) can then fall
back to the manual byte-layout decoder without raising at startup.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Process-level cache so we don't re-parse the IDL on every decode call.
_IDL_CACHE: dict[str, Any] = {}
_CODER_CACHE: dict[str, Any] = {}


class AnchorDecoder:
    """Thin wrapper around ``anchorpy.coder.coder.Coder`` for account decode.

    The decoder is intentionally lazy: it only attempts to load the IDL
    on first use and keeps the parsed Idl + Coder cached for the
    lifetime of the process.
    """

    def __init__(self, idl_path: str | None) -> None:
        self._idl_path = (idl_path or "").strip()
        self._available: bool | None = None
        self._coder: Any | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _load_coder(self) -> Any | None:
        """Return the cached :class:`Coder`, or ``None`` if unavailable.

        Failures (missing file, malformed JSON, anchorpy ImportError) are
        logged once and remembered so we don't retry on every decode.
        """

        if self._coder is not None:
            return self._coder
        if self._available is False:
            return None

        if not self._idl_path:
            self._available = False
            logger.info("AnchorDecoder: BAGSVAULT_IDL_PATH not set — decoder disabled.")
            return None

        path = Path(self._idl_path)
        if not path.exists():
            self._available = False
            logger.warning("AnchorDecoder: IDL file not found at %s — decoder disabled.", path)
            return None

        cache_key = str(path.resolve())
        if cache_key in _CODER_CACHE:
            self._coder = _CODER_CACHE[cache_key]
            self._available = True
            return self._coder

        try:
            # anchorpy is in requirements.txt but we still guard the
            # import so a partial install can't take the indexer down.
            from anchorpy import Idl
            from anchorpy.coder.coder import Coder
        except ImportError as exc:
            self._available = False
            logger.warning("AnchorDecoder: anchorpy not importable (%s) — decoder disabled.", exc)
            return None

        try:
            raw = path.read_text(encoding="utf-8")
            # Validate JSON early so a clean error message surfaces.
            json.loads(raw)
            idl = Idl.from_json(raw)
            coder = Coder(idl)
        except (OSError, ValueError) as exc:
            self._available = False
            logger.warning("AnchorDecoder: failed to parse IDL at %s (%s) — disabled.", path, exc)
            return None
        except Exception as exc:  # noqa: BLE001 — anchorpy-side parse errors
            self._available = False
            logger.warning(
                "AnchorDecoder: unexpected error loading IDL at %s (%s) — disabled.",
                path,
                exc,
            )
            return None

        _IDL_CACHE[cache_key] = idl
        _CODER_CACHE[cache_key] = coder
        self._coder = coder
        self._available = True
        logger.info("AnchorDecoder: IDL loaded from %s.", path)
        return coder

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def decode_available(self) -> bool:
        """Return ``True`` once the IDL + Coder have loaded successfully."""

        if self._available is None:
            # Trigger lazy load so the first call to ``decode_available``
            # gives the correct answer.
            self._load_coder()
        return bool(self._available)

    async def decode_account(
        self,
        account_data_base64: str,
        account_name: str,
    ) -> dict[str, Any] | None:
        """Decode a base64-encoded account payload to a Python dict.

        Returns ``None`` if the decoder is disabled, the input cannot be
        decoded as base64, or anchorpy refuses the payload (for example
        because the discriminator does not match ``account_name``).
        """

        coder = self._load_coder()
        if coder is None:
            return None

        try:
            raw = base64.b64decode(account_data_base64)
        except (ValueError, TypeError) as exc:
            logger.warning("AnchorDecoder.decode_account: bad base64 (%s)", exc)
            return None

        try:
            container = coder.accounts.decode(raw)
        except Exception as exc:  # noqa: BLE001 — anchorpy raises generic exceptions
            logger.warning("AnchorDecoder.decode_account(name=%s) failed: %s", account_name, exc)
            return None

        return _container_to_dict(container)


def _container_to_dict(value: Any) -> Any:
    """Recursively convert anchorpy/construct decode output to plain Python.

    Anchorpy's account decoder may return either:

    * a generated dataclass instance (one ``@dataclass`` per IDL account) —
      we walk ``__dataclass_fields__`` (or ``__slots__`` / public attrs);
    * a ``construct.Container`` (dict-subclass with junk ``_io`` keys) —
      we strip the leading-underscore metadata keys.

    Bytes are hex-encoded so the resulting structure is JSON-serialisable.
    """

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and k.startswith("_"):
                continue
            out[str(k)] = _container_to_dict(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_container_to_dict(v) for v in value]
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    # Dataclass / generated anchorpy account class — walk fields.
    fields = getattr(value, "__dataclass_fields__", None)
    if fields is not None:
        return {name: _container_to_dict(getattr(value, name)) for name in fields}

    # Slotted class — walk __slots__.
    slots = getattr(value, "__slots__", None)
    if slots:
        slot_names: list[str]
        if isinstance(slots, str):
            slot_names = [slots]
        else:
            slot_names = list(slots)
        return {name: _container_to_dict(getattr(value, name, None)) for name in slot_names}

    # Generic object — best-effort: collect public attributes that are
    # not callables.
    attrs = {
        name: getattr(value, name)
        for name in dir(value)
        if not name.startswith("_") and not callable(getattr(value, name, None))
    }
    if attrs:
        return {name: _container_to_dict(val) for name, val in attrs.items()}
    return value


# ----------------------------------------------------------------------
# Module-level singleton
# ----------------------------------------------------------------------
_anchor_decoder: AnchorDecoder | None = None


def get_anchor_decoder() -> AnchorDecoder:
    """FastAPI dependency factory for the lazy :class:`AnchorDecoder`."""

    global _anchor_decoder
    if _anchor_decoder is None:
        # Imported here to avoid a hard dependency at import time.
        from app.config import settings

        _anchor_decoder = AnchorDecoder(idl_path=settings.bagsvault_idl_path)
    return _anchor_decoder


def reset_anchor_decoder() -> None:
    """Test helper: clear the cached singleton so a new IDL path is picked up."""

    global _anchor_decoder
    _anchor_decoder = None
