# SPDX-License-Identifier: Apache-2.0
from abc import ABC, abstractmethod
from typing import Any, Optional


class ILogger(ABC):
    # He65 canonical logger contract. All logging must pass through this interface.

    @abstractmethod
    def info(self, msg: str, **kwargs: Any) -> None:
        pass

    @abstractmethod
    def error(self, msg: str, error: Optional[Exception] = None, **kwargs: Any) -> None:
        pass

    @abstractmethod
    def debug(self, msg: str, **kwargs: Any) -> None:
        pass

    @abstractmethod
    def audit(self, action: str, actor: str, outcome: str, **details: Any) -> None:
        pass
