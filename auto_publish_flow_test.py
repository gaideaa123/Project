from __future__ import annotations

from unittest.mock import patch

import auto_publish_flow


class Button:
    def __init__(self, label="Paylaş"):
        self.label = label
        self.clicks = 0

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def is_visible(self, timeout=0):
        return True

    def is_enabled(self):
        return True

    def scroll_into_view_if_needed(self, timeout=0):
        pass

    def click(self, **kwargs):
        self.clicks += 1


class Empty:
    @property
    def first(self):
        return self

    def count(self):
        return 0

    def nth(self, index):
        raise IndexError(index)


class Body:
    def __init__(self, page):
        self.page = page

    def inner_text(self, timeout=0):
        return self.page.texts[self.page.index]


class Page:
    def __init__(self, texts):
        self.texts = list(texts)
        self.index = 0
        self.waits = []
        self.button = Button()

    def is_closed(self):
        return False

    def wait_for_timeout(self, value):
        self.waits.append(value)
        self.index = min(self.index + 1, len(self.texts) - 1)

    def locator(self, selector):
        return Body(self) if selector == "body" else Empty()

    def get_by_role(self, role, name=None):
        return self.button if role == "button" else Empty()


class Dialog:
    def __init__(self):
        self.cancel = Button("İptal")
        self.immediate = Button("Hemen paylaş")

    def is_visible(self, timeout=0):
        return True

    def inner_text(self, timeout=0):
        return (
            "Paylaşmaya devam edilsin mi? Telif hakkı kontrolü eksik. "
            "Videonuzu hâlâ potansiyel sorunlar bakımından kontrol ediyoruz. "
            "İptal Hemen paylaş"
        )

    def get_by_role(self, role, name=None):
        return self.cancel

    def locator(self, selector):
        return Empty()


class DialogCollection:
    def __init__(self, dialog):
        self.dialog = dialog

    def count(self):
        return 1

    def nth(self, index):
        return self.dialog


class DialogPage:
    def __init__(self):
        self.dialog = Dialog()
        self.waits = []

    def is_closed(self):
        return False

    def locator(self, selector):
        return DialogCollection(self.dialog)

    def wait_for_timeout(self, value):
        self.waits.append(value)



def main() -> None:
    page = Page([
        "Video yükleniyor 70% İçerik kontrolü sürüyor",
        "İçerik kontrolü sürüyor",
        "Müzik telif hakkı kontrolü Sorun tespit edilmedi. İçerik kontrolü Sorun tespit edilmedi.",
        "Müzik telif hakkı kontrolü Sorun tespit edilmedi. İçerik kontrolü Sorun tespit edilmedi.",
        "Müzik telif hakkı kontrolü Sorun tespit edilmedi. İçerik kontrolü Sorun tespit edilmedi.",
    ])
    with patch.object(auto_publish_flow.time, "monotonic", side_effect=range(100)):
        assert auto_publish_flow.wait_for_checks_complete(
            page,
            timeout_seconds=90,
            require_completion_evidence=True,
        ) is page.button
    assert len(page.waits) >= 4

    warning = DialogPage()
    with patch.object(auto_publish_flow.time, "monotonic", side_effect=range(20)):
        assert auto_publish_flow.dismiss_incomplete_check_dialog(warning, timeout_seconds=8)
    assert warning.dialog.cancel.clicks == 1
    assert warning.dialog.immediate.clicks == 0

    blocked = Page(["Özgün olmayan, düşük kaliteli ve QR kodlu içerik. Yine de paylaşabilirsiniz."])
    with patch.object(auto_publish_flow.time, "monotonic", side_effect=range(20)):
        try:
            auto_publish_flow.wait_for_checks_complete(blocked, timeout_seconds=10)
            raise AssertionError("Advisory varken yayın devam etmemeliydi")
        except RuntimeError as exc:
            assert "Yine de paylaş" in str(exc) and "seçilmedi" in str(exc)

    print("OK: eksik kontrol uyarısı kapatılıyor, Hemen paylaş atlanıyor ve kontrol bitince Paylaş hazır")


if __name__ == "__main__":
    main()
