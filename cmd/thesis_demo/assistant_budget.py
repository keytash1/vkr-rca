"""Local input estimate with explicit uncertainty, never a provider cost cap."""

import json
import hashlib
import math
import os
from pathlib import Path
import tempfile

# Pin the encoding policy separately from the model. Unknown models retain the
# conservative byte reservation. Codec updates require new development proofs.
ENCODING_POLICY = {"gpt-6.1-sol": "o200k_base"}
ENCODING_CACHE_KEY = "fb374d419588a4632f3f557e76b4b70aebbca790"
# tiktoken 0.12.0, tiktoken_ext/openai_public.py::o200k_base expected_hash.
ENCODING_SHA256 = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"


def reserve_input(payload, model):
    wire = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    fallback = (len(wire.encode()) + 512, "UTF8_BYTES_PLUS_512_CONSERVATIVE")
    if model not in ENCODING_POLICY:
        return fallback
    # Warm-up is separate. Verify BEFORE calling tiktoken: its ordinary cache
    # loader would download again after discovering corrupt data. Trusted-local
    # cache, not protection against the owner racing filesystem modifications.
    try:
        # Match tiktoken's exact precedence. An empty override disables its
        # cache and would cause a network download, so use the byte fallback.
        configured = next((os.environ[k] for k in ("TIKTOKEN_CACHE_DIR", "DATA_GYM_CACHE_DIR")
                           if k in os.environ), None)
        if configured == "":
            return fallback
        cache = Path(configured) if configured is not None else Path(tempfile.gettempdir()) / "data-gym-cache"
        path = cache / ENCODING_CACHE_KEY
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8*1024*1024:
            return fallback
        if hashlib.sha256(path.read_bytes()).hexdigest() != ENCODING_SHA256:
            return fallback
        import tiktoken

        count = len(
            tiktoken.get_encoding(ENCODING_POLICY[model]).encode(
                wire, disallowed_special=()
            )
        )
    except (ImportError, OSError, ValueError):
        return fallback
    return (
        math.ceil(count * 1.5) + 512,
        "O200K_VERIFIED_LOCAL_ESTIMATE_X1_5_PLUS_512_NOT_PROVIDER_INVOICE",
    )
