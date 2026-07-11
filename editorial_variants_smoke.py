from __future__ import annotations

import inspect

import video_variants as variants


def check(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)
    print("OK:", message)


def main() -> None:
    plans = [variants.plan_for(index) for index in range(1, 19)]
    check(len(variants.BASE_PLANS) >= 6, "en az altı farklı editoryal gramer")
    check(len({plan.name for plan in plans}) == len(plans), "hesap plan adları benzersiz")
    check(len({plan.hook_fractions for plan in plans}) >= 12, "hook sahneleri hesaplara göre değişiyor")
    check(any(len(plan.hook_fractions) == 1 for plan in plans), "tek güçlü hook kurgusu")
    check(any(len(plan.hook_fractions) == 2 for plan in plans), "çift reveal kurgusu")
    check(any(len(plan.hook_fractions) == 3 for plan in plans), "hızlı montage kurgusu")
    check(len({round(plan.speed, 4) for plan in plans}) >= 10, "ana anlatı temposu değişiyor")
    check(all(.975 <= plan.speed <= 1.045 for plan in plans), "tempo oynatılabilir sınırda")
    check(all(.08 <= value <= .90 for plan in plans for value in plan.hook_fractions), "hook noktaları güvenli aralıkta")
    source = inspect.getsource(variants.create_variants)
    check('f"{index}.mp4"' in source, "1.mp4, 2.mp4 sırası korunuyor")
    check("temporary.replace(target)" in source, "çıktılar atomik tamamlanıyor")
    signature = inspect.signature(variants.create_variants)
    check("cold_open" in signature.parameters and "output_dir" in signature.parameters, "app_tr API uyumluluğu")
    print("\nTEK TIK EDİTORYAL VARYASYON TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
