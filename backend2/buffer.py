"""In-memory per-session audio buffer for Backend 2 (Milestone 1).

Maintains isolated, FIFO byte buffers for each active session_id.
Preserves frame arrival order, ensures thread-safe and async-safe access,
and prevents unbounded memory growth via configurable size limits.
"""
from __future__ import annotations

import logging
import threading
from typing import Literal

logger = logging.getLogger("backend2.buffer")

OverflowPolicy = Literal["drop_oldest", "reject"]

# 16 kHz mono 16-bit PCM = 32,000 bytes/sec.
# Default limit: ~32 seconds of audio per session (~1 MB).
DEFAULT_MAX_BYTES_PER_SESSION = 1_024_000
DEFAULT_MAX_SESSIONS = 1000
MAX_SESSION_ID_LENGTH = 128


class AudioBufferError(Exception):
    """Base exception for audio buffer operations."""


class InvalidSessionError(AudioBufferError):
    """Raised when a session_id is empty, invalid, or malformed."""


class BufferOverflowError(AudioBufferError):
    """Raised when appending exceeds buffer capacity and policy is 'reject'."""


class SessionNotFoundError(AudioBufferError):
    """Raised when attempting an operation on a non-existent session."""


def _validate_session_id(session_id: object) -> str:
    """Validate and clean session ID."""
    if not isinstance(session_id, str):
        raise InvalidSessionError(
            f"session_id must be a string, got {type(session_id).__name__}."
        )
    cleaned = session_id.strip()
    if not cleaned:
        raise InvalidSessionError("session_id must be a non-empty string.")
    if len(cleaned) > MAX_SESSION_ID_LENGTH:
        raise InvalidSessionError(
            f"session_id exceeds max length of {MAX_SESSION_ID_LENGTH} characters."
        )
    return cleaned


class SessionAudioBuffer:
    """Thread-safe FIFO byte buffer for a single session.

    Stores unmodified raw PCM16 bytes in strict arrival sequence.
    """

    def __init__(
        self,
        session_id: str,
        max_bytes: int = DEFAULT_MAX_BYTES_PER_SESSION,
        overflow_policy: OverflowPolicy = "drop_oldest",
    ) -> None:
        self.session_id = _validate_session_id(session_id)
        if max_bytes <= 0:
            raise ValueError(f"max_bytes must be positive, got {max_bytes}.")
        self.max_bytes = max_bytes
        self.overflow_policy: OverflowPolicy = overflow_policy
        self._data = bytearray()
        self._lock = threading.RLock()
        self._total_bytes_appended = 0
        self._total_bytes_extracted = 0
        self._dropped_bytes = 0

    @property
    def size(self) -> int:
        """Current number of buffered bytes."""
        with self._lock:
            return len(self._data)

    @property
    def total_bytes_appended(self) -> int:
        """Cumulative bytes appended over this session's lifetime."""
        with self._lock:
            return self._total_bytes_appended

    @property
    def total_bytes_extracted(self) -> int:
        """Cumulative bytes extracted over this session's lifetime."""
        with self._lock:
            return self._total_bytes_extracted

    @property
    def dropped_bytes(self) -> int:
        """Cumulative bytes dropped due to buffer capacity overruns."""
        with self._lock:
            return self._dropped_bytes

    def append(self, chunk: bytes | bytearray) -> int:
        """Append raw PCM16 bytes to the buffer in FIFO order.

        Args:
            chunk: bytes or bytearray to append.

        Returns:
            The number of bytes successfully accepted into the buffer.

        Raises:
            TypeError: if chunk is not bytes or bytearray.
            BufferOverflowError: if buffer capacity is exceeded and
                overflow_policy is 'reject'.
        """
        if not isinstance(chunk, (bytes, bytearray)):
            raise TypeError(
                f"Audio chunk must be bytes or bytearray, got {type(chunk).__name__}."
            )
        if len(chunk) == 0:
            return 0

        incoming_len = len(chunk)

        with self._lock:
            projected_size = len(self._data) + incoming_len

            if projected_size > self.max_bytes:
                if self.overflow_policy == "reject":
                    raise BufferOverflowError(
                        f"Session {self.session_id} buffer overflow: "
                        f"size {len(self._data)} + incoming {incoming_len} > max {self.max_bytes}."
                    )
                # Drop oldest bytes to accommodate the incoming chunk
                overflow = projected_size - self.max_bytes
                del self._data[:overflow]
                self._dropped_bytes += overflow
                logger.warning(
                    "Session %s buffer dropped %d oldest bytes (capacity: %d).",
                    self.session_id,
                    overflow,
                    self.max_bytes,
                )

            # Append unmodified bytes at the end
            self._data.extend(chunk)
            self._total_bytes_appended += incoming_len
            return incoming_len

    def extract(self, num_bytes: int, exact: bool = False) -> bytes:
        """Extract and remove the oldest `num_bytes` from the buffer.

        Args:
            num_bytes: Number of bytes to extract.
            exact: If True, raises ValueError if fewer than `num_bytes`
                   are available. If False, returns min(num_bytes, available).

        Returns:
            bytes object containing the extracted PCM16 audio.
        """
        if num_bytes < 0:
            raise ValueError(f"num_bytes must be non-negative, got {num_bytes}.")
        if num_bytes == 0:
            return b""

        with self._lock:
            current_len = len(self._data)
            if exact and current_len < num_bytes:
                raise ValueError(
                    f"Requested {num_bytes} bytes but only {current_len} available in session {self.session_id}."
                )

            to_extract = min(num_bytes, current_len)
            extracted = bytes(self._data[:to_extract])
            del self._data[:to_extract]
            self._total_bytes_extracted += to_extract
            return extracted

    def peek(self, num_bytes: int | None = None) -> bytes:
        """Inspect buffered bytes without removing them.

        Args:
            num_bytes: Number of bytes to inspect. If None, peeks entire buffer.
        """
        with self._lock:
            if num_bytes is None:
                return bytes(self._data)
            if num_bytes < 0:
                raise ValueError(f"num_bytes must be non-negative, got {num_bytes}.")
            return bytes(self._data[:num_bytes])

    def clear(self) -> None:
        """Clear all buffered audio for this session."""
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return self.size


class SessionBufferManager:
    """Manages independent SessionAudioBuffer instances across multiple sessions.

    Thread-safe and safe for concurrent async access.
    """

    def __init__(
        self,
        max_bytes_per_session: int = DEFAULT_MAX_BYTES_PER_SESSION,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        overflow_policy: OverflowPolicy = "drop_oldest",
    ) -> None:
        self.max_bytes_per_session = max_bytes_per_session
        self.max_sessions = max_sessions
        self.overflow_policy = overflow_policy
        self._buffers: dict[str, SessionAudioBuffer] = {}
        self._lock = threading.RLock()

    def get_or_create_buffer(self, session_id: str) -> SessionAudioBuffer:
        """Retrieve existing buffer or create a new one for session_id."""
        clean_id = _validate_session_id(session_id)
        with self._lock:
            if clean_id not in self._buffers:
                if len(self._buffers) >= self.max_sessions:
                    raise AudioBufferError(
                        f"Maximum session limit ({self.max_sessions}) reached. "
                        "Remove inactive sessions to free capacity."
                    )
                self._buffers[clean_id] = SessionAudioBuffer(
                    session_id=clean_id,
                    max_bytes=self.max_bytes_per_session,
                    overflow_policy=self.overflow_policy,
                )
            return self._buffers[clean_id]

    def append(self, session_id: str, chunk: bytes | bytearray) -> int:
        """Append raw audio chunk to the specified session buffer."""
        buf = self.get_or_create_buffer(session_id)
        return buf.append(chunk)

    def extract(self, session_id: str, num_bytes: int, exact: bool = False) -> bytes:
        """Extract up to or exactly `num_bytes` from the session buffer."""
        clean_id = _validate_session_id(session_id)
        with self._lock:
            buf = self._buffers.get(clean_id)
            if buf is None:
                if exact and num_bytes > 0:
                    raise SessionNotFoundError(f"Session {clean_id} not found.")
                return b""
            return buf.extract(num_bytes, exact=exact)

    def peek(self, session_id: str, num_bytes: int | None = None) -> bytes:
        """Inspect bytes from the session buffer without removing them."""
        clean_id = _validate_session_id(session_id)
        with self._lock:
            buf = self._buffers.get(clean_id)
            if buf is None:
                return b""
            return buf.peek(num_bytes)

    def get_size(self, session_id: str) -> int:
        """Get the current buffered byte count for a session."""
        clean_id = _validate_session_id(session_id)
        with self._lock:
            buf = self._buffers.get(clean_id)
            return buf.size if buf is not None else 0

    def clear_session(self, session_id: str) -> None:
        """Clear buffered bytes for a session while retaining the session record."""
        clean_id = _validate_session_id(session_id)
        with self._lock:
            buf = self._buffers.get(clean_id)
            if buf is not None:
                buf.clear()

    def remove_session(self, session_id: str) -> bool:
        """Completely remove a session and its buffer.

        Returns:
            True if the session existed and was removed, False otherwise.
        """
        clean_id = _validate_session_id(session_id)
        with self._lock:
            if clean_id in self._buffers:
                buf = self._buffers.pop(clean_id)
                buf.clear()
                return True
            return False

    def has_session(self, session_id: str) -> bool:
        """Check if a session buffer currently exists."""
        clean_id = _validate_session_id(session_id)
        with self._lock:
            return clean_id in self._buffers

    def list_sessions(self) -> list[str]:
        """Return a list of all active session IDs."""
        with self._lock:
            return list(self._buffers.keys())

    def get_total_buffered_bytes(self) -> int:
        """Return the sum of all buffered bytes across all active sessions."""
        with self._lock:
            return sum(b.size for b in self._buffers.values())

    def clear_all(self) -> None:
        """Remove all sessions and clear all buffers."""
        with self._lock:
            for buf in self._buffers.values():
                buf.clear()
            self._buffers.clear()


# Global singleton instance and accessors
_buffer_manager_lock = threading.Lock()
_global_buffer_manager: SessionBufferManager | None = None


def get_buffer_manager() -> SessionBufferManager:
    """Return the process-wide SessionBufferManager singleton."""
    global _global_buffer_manager
    if _global_buffer_manager is not None:
        return _global_buffer_manager
    with _buffer_manager_lock:
        if _global_buffer_manager is not None:
            return _global_buffer_manager
        _global_buffer_manager = SessionBufferManager()
        return _global_buffer_manager


def reset_buffer_manager() -> None:
    """Reset the global SessionBufferManager (for test isolation)."""
    global _global_buffer_manager
    with _buffer_manager_lock:
        if _global_buffer_manager is not None:
            _global_buffer_manager.clear_all()
        _global_buffer_manager = None
