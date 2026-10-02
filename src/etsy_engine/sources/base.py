"""Base interface every trend source implements."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Trend


class BaseSource(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(self, limit: int) -> list[Trend]:
        """Return up to `limit` trends. Should never raise for transient/network
        issues — log and return what it has, so one bad source doesn't kill the run."""
        raise NotImplementedError
