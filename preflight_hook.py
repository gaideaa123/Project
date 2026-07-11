from __future__ import annotations

"""Install content preflight around an uploader without changing its public API."""

import inspect
from typing import Any, Callable

import content_preflight


def _supported_kwargs(function: Callable[..., Any], values: dict[str, Any]) -> dict[str, Any]:
    """Forward only arguments supported by the wrapped uploader version."""
    parameters = inspect.signature(function).parameters.values()
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        return values
    names = {parameter.name for parameter in parameters}
    return {name: value for name, value in values.items() if name in names}


def install(web_uploader: Any) -> None:
    if getattr(web_uploader, "_signaldesk_preflight_installed", False):
        return
    original_prepare = web_uploader.prepare_upload

    def prepare(
        request: Any,
        *args: Any,
        publish: bool = False,
        approval: Any = None,
        status: Any = None,
        **kwargs: Any,
    ) -> Any:
        if status:
            status(f"{request.profile}: medya kalite ve tekrar kontrolü yapılıyor")
        report = content_preflight.validate(request.profile, request.video, request.caption)
        optional = {"publish": publish, "approval": approval, "status": status, **kwargs}
        result = original_prepare(
            request,
            *args,
            **_supported_kwargs(original_prepare, optional),
        )
        if publish:
            content_preflight.record(request.profile, report, "published")
        return result

    web_uploader.prepare_upload = prepare
    web_uploader._signaldesk_preflight_installed = True
