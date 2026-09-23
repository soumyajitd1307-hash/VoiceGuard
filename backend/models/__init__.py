"""Backend 3 model adapters."""
from backend.models.base import SyntheticVoiceModel
from backend.models.mock_model import MockHeuristicModel

__all__ = ["SyntheticVoiceModel", "MockHeuristicModel"]
