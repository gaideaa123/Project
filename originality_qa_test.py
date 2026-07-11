from __future__ import annotations

import originality_qa
import video_variants


def main() -> None:
 assert len({video_variants.plan_for(index).scene_fractions for index in range(1, 13)}) == 12
 assert all(len(video_variants.plan_for(index).scene_fractions) >= 3 for index in range(1, 13))
 assert originality_qa.hamming(0b1010, 0b0011) == 2
 assert originality_qa.signature_distance((0, 15), (15, 0)) == 4.0
 try:
  originality_qa.assert_output_eligible
 except AttributeError as exc:
  raise AssertionError("Output QA eksik") from exc
 assert auto_publish_advisory_is_blocking()
 print("OK: 12 farklı sahne planı, görsel mesafe ve advisory fail-closed doğrulandı")


def auto_publish_advisory_is_blocking() -> bool:
 import auto_publish_flow
 return bool(auto_publish_flow.ADVISORY.search("Özgün olmayan, düşük kaliteli ve QR kodlu içerik")) and not hasattr(auto_publish_flow, "handle_advisory_dialog")


if __name__ == "__main__": main()
