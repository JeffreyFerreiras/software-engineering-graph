"""Canonical serialization and stable identifier helpers."""

import hashlib
import json
from typing import Any, Optional



STABLE_ID_DOMAIN_VERSION = 5


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def repository_digest(repository_id: str) -> str:
    return sha256_bytes(b"graph-repository-v1\0" + repository_id.encode("utf-8"))


def stable_id(
    run_id: str,
    policy_digest: str,
    entity_type: str,
    template_key: str,
    generation: int,
    specialist_tag: Optional[str] = None,
) -> str:
    identity = [
        STABLE_ID_DOMAIN_VERSION,
        run_id,
        policy_digest,
        entity_type,
        template_key,
        generation,
        specialist_tag or "",
    ]
    return "g2-" + sha256_bytes(canonical_bytes(identity))[:24]
