from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ServiceError(Exception):
    code: int
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
