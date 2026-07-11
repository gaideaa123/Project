from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import preflight_hook
import web_uploader


def check(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)
    print("OK:", message)


def test_locator_contract() -> None:
    class Locator:
        def __init__(self, count: int):
            self._count = count

        def count(self) -> int:
            return self._count

    check(web_uploader.locator_attached(Locator(1)), "public Locator.count API detects attachment")
    check(not web_uploader.locator_attached(Locator(0)), "missing locator stays detached")
    check("is_attached" not in inspect.getsource(web_uploader.wait_for_login), "removed Playwright API is absent")


def test_preflight_compatibility() -> None:
    calls: list[object] = []
    records: list[tuple[object, ...]] = []

    def legacy_prepare(request: object) -> str:
        calls.append(request)
        return "ok"

    uploader = SimpleNamespace(prepare_upload=legacy_prepare)
    original_validate = preflight_hook.content_preflight.validate
    original_record = preflight_hook.content_preflight.record
    preflight_hook.content_preflight.validate = lambda profile, video, caption: {"valid": True}
    preflight_hook.content_preflight.record = lambda *args: records.append(args)
    try:
        preflight_hook.install(uploader)
        request = SimpleNamespace(profile="profile-1", video=Path("video.mp4"), caption="caption")
        result = uploader.prepare_upload(request, publish=True, approval=object(), status=lambda _: None)
    finally:
        preflight_hook.content_preflight.validate = original_validate
        preflight_hook.content_preflight.record = original_record

    check(result == "ok", "preflight preserves legacy uploader return value")
    check(calls == [request], "unsupported wrapper kwargs are not leaked")
    check(len(records) == 1, "successful publish records one preflight receipt")


def main() -> None:
    test_locator_contract()
    test_preflight_compatibility()
    print("\nARCHITECTURE CONTRACTS PASSED")


if __name__ == "__main__":
    main()
