from __future__ import annotations

"""Allow only unassigned profiles to publish through the machine's direct IP."""

from typing import Any

import network_identity
import profile_integrity
import proxy_health


def connection_for(profile: str) -> network_identity.NetworkIdentity:
 identity = network_identity.load(profile)
 if not identity.server:
  return identity
 try:
  proxy_health.require_healthy(identity)
 except Exception as exc:
  raise RuntimeError(f"{profile}: atanmış proxy sağlıklı değil: {exc}") from exc
 return identity


def validate_connections(names: list[str]) -> dict[str, network_identity.NetworkIdentity]:
 if not names:
  raise RuntimeError("Bağlantısı doğrulanacak profil yok")
 return {name: connection_for(name) for name in names}


def install(publishing_flow_gui: Any) -> None:
 if getattr(publishing_flow_gui, "_direct_connection_policy_installed", False):
  return
 publishing_flow_gui.validated_proxy = connection_for
 publishing_flow_gui.validate_proxy_assignments = validate_connections
 publishing_flow_gui._direct_connection_policy_installed = True

 if not getattr(network_identity, "_integrity_aware_delete_installed", False):
  original_delete = network_identity.delete

  def delete_and_reset(profile: str) -> None:
   original_delete(profile)
   profile_integrity.reset(profile)

  network_identity.delete = delete_and_reset
  network_identity._integrity_aware_delete_installed = True
