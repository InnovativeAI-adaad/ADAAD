from abc import ABC, abstractmethod
from typing import Any, Optional

class ILogger(ABC):
    """He65 canonical logger contract. All logging must pass through this interface."""

    @abstractmethod
    def info(self, msg: str, **kwargs: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    def error(self, msg: str, error: Optional[Exception] = None, **kwargs: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    def debug(self, msg: str, **kwargs: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    def audit(self, action: str, actor: str, outcome: str, **details: Any) -> None:
        """High-value security/transaction logging."""
        raise NotImplementedError
