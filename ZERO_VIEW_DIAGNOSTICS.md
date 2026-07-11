# Zero-view publication diagnostics

TikTok does not guarantee views. The application can, however, eliminate local false-success states that look like a published post while no post was actually accepted.

## Concrete bug fixed in PR 43

The old web uploader accepted the words **upload complete / yüklendi** as publication success. Those words already exist after the media transfer finishes and before the Post request is accepted. The application could therefore close the browser and move to the next account while TikTok was still submitting the post, or while the Post request had silently failed.

The corrected flow distinguishes two states:

1. **Upload complete:** media transfer finished. This is not publication.
2. **Publication verified:** TikTok displays a new explicit post-success notice, or leaves the upload editor for a known content-management page with the editor gone.

The browser stays open for up to three minutes after clicking Post. Generic URL changes and pre-existing upload-complete text are ignored. "Something went wrong", "Try again", and equivalent Turkish post errors fail the current account instead of advancing to the next one.

## Visibility guard

Before Post is clicked, the uploader inspects the visible audience control. If it explicitly shows **Only you / Private / Yalnızca sen / Sadece ben**, the run stops with a clear message. A private post cannot receive outside views. The application does not change this setting automatically.

## Receipts

Every verified web publication writes a timestamped JSON receipt under the platform user-data directory:

`signaldesk-web-uploader/publish-receipts/`

A receipt is local evidence that the UI reached a strict publication-success state. It is not a promise of recommendation or views.

## If a verified post still has zero views

Check TikTok Studio Account Status and the individual post's For You feed eligibility. TikTok states that account standing and recommendation eligibility affect post performance, and repeatedly unsuitable content can make accounts and posts harder to discover. Also confirm the post is visible from a different account.
