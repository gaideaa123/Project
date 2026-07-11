# Zero-view publication fix

TikTok does not publish a guaranteed technical recipe for obtaining views. Its official troubleshooting points creators to post visibility, Account Status, For You feed eligibility, review/violation notices, and recommendation eligibility.

The concrete bug fixed here was local: the uploader detected TikTok's **incomplete copyright check** warning and automatically clicked **Hemen paylaş** for every profile. That can submit a post while checks are still pending, yet the application immediately records it as published.

The new behavior is fail-closed:

1. Keep TikTok content checks enabled.
2. If the incomplete-check modal appears, click exact **İptal** only inside that verified modal.
3. Stop the profile's publishing run with a clear error.
4. Retry after TikTok finishes its check. Never record that attempt as published.

This removes a known false-success path. It cannot guarantee distribution because account restrictions, privacy, content eligibility, moderation, audience response, and platform-side processing remain controlled by TikTok. Check **TikTok Studio → Account check** and each post's **Analytics → For You feed eligibility** when a verified post still remains at zero.
