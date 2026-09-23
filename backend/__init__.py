# VoiceGuard Backend 3 package.
from backend.service import SyntheticVoiceDetectionService, detect_synthetic_voice
from backend.schemas import DetectionResult
from backend.config import get_settings

__all__ = [
    "SyntheticVoiceDetectionService",
    "detect_synthetic_voice",
    "DetectionResult",
    "get_settings",
]
