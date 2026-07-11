from __future__ import annotations

"""Capability-safe TikTok login integration helpers."""

import inspect
from collections.abc import Callable
from typing import Any


def accepts_parameter(function: Callable[..., Any] | None, name: str) -> bool:
    if not callable(function):
        return False
    try:
        parameters = inspect.signature(function).parameters
    except (TypeError, ValueError):
        return False
    return name in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


def optional_callable(target: Any, name: str) -> Callable[..., Any] | None:
    value = getattr(target, name, None)
    return value if callable(value) else None
