"""Multi-provider API-key rotation with persistent usage accounting.

- Cohere: trial keys allow ~1000 calls each (strict). Keys are retired on
  quota/auth errors; 429s are transient (backoff happens in ra_driver).
- GLM (Z.ai): free-tier keys, no fixed call cap -> rotate only when the API
  signals a quota/busy error, so parallel screening+extraction jobs share the
  pool. Paste extra keys into ZAI_API_KEYS in .env.

State lives in state/<provider>_usage.json and is RE-READ on every key request,
making rotation safe across the parallel screening/extraction processes.

Check budget anytime:  python keys.py
"""
import hashlib
import json
import threading
import time

import config

_LOCK = threading.Lock()
PER_KEY_LIMIT = 1000

# Study call budget (with retries/JSON-repair/pilot/rerun overhead)
NEED_SCREEN = 2300    # screening arm: 2000 papers
NEED_FULL = 4700      # + EvidenceInference extraction: 2184 articles


def _fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def is_quota_error(err: Exception) -> bool:
    """True when the error means 'this key is done', not 'slow down'."""
    s = str(err).lower()
    quota = ["invalid api key", "unauthorized", "forbidden", "not_found",
             "exceeded", "quota", "trial limit", "key limit", "401", "403",
             "arrears", "insufficient balance"]
    rate = ["429", "too many requests", "rate limit", "server busy", "overload"]
    return any(k in s for k in quota) and not any(k in s for k in rate)


class RotatingKeys:
    """Least-used-key rotation, re-reading state from disk (process-safe)."""

    def __init__(self, name: str, keys: list[str], per_key_limit: int | None):
        self.name = name
        self.keys = [k for k in keys if k]
        self.per_key_limit = per_key_limit
        self.state_file = config.STATE_DIR / f"{name}_usage.json"
        if not self.keys:
            raise RuntimeError(f"No API keys configured for {name}")
        self._load_merge()

    def _load(self) -> dict:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except Exception:
                pass
        return {}

    def _load_merge(self) -> None:
        with _LOCK:
            state = self._load()
            for k in self.keys:
                state.setdefault(_fingerprint(k), {"calls": 0, "exhausted": False})
            self._save(state)

    def _save(self, state: dict) -> None:
        # Unique tmp name per process/thread: screening and extraction run as
        # parallel processes sharing this state file, and a shared tmp name
        # races (replace() consuming the other writer's tmp file).
        import os
        import threading
        tmp = self.state_file.with_suffix(
            f".{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            tmp.write_text(json.dumps(state, indent=2))
            tmp.replace(self.state_file)
        except OSError as e:
            # Accounting is best-effort; never lose an inference result over it.
            # (Cohere enforces the real quota server-side regardless.)
            print(f"[keys] usage-state write skipped ({e}); continuing.")

    def get_key(self) -> str:
        with _LOCK:
            state = self._load()
            usable = [k for k in self.keys
                      if not state.get(_fingerprint(k), {}).get("exhausted")]
            if not usable:
                raise RuntimeError(
                    f"All {self.name} keys exhausted. Add keys in validation/.env.")
            usable.sort(key=lambda k: state.get(_fingerprint(k), {}).get("calls", 0))
            return usable[0]

    def mark_call(self, key: str) -> None:
        with _LOCK:
            state = self._load()
            fp = _fingerprint(key)
            state.setdefault(fp, {"calls": 0, "exhausted": False})
            state[fp]["calls"] += 1
            if self.per_key_limit and state[fp]["calls"] >= self.per_key_limit:
                state[fp]["exhausted"] = True
            self._save(state)

    def mark_exhausted(self, key: str) -> None:
        with _LOCK:
            state = self._load()
            fp = _fingerprint(key)
            state.setdefault(fp, {"calls": 0, "exhausted": False})
            state[fp]["exhausted"] = True
            self._save(state)
            left = [k for k in self.keys if not state[_fingerprint(k)]["exhausted"]]
        print(f"[keys] {self.name} key ...{key[-4:]} retired. {len(left)} key(s) remain.")

    def usage_report(self) -> str:
        state = self._load()
        lines = []
        for k in self.keys:
            s = state.get(_fingerprint(k), {"calls": 0, "exhausted": False})
            cap = f"/{self.per_key_limit}" if self.per_key_limit else ""
            lines.append(f"  ...{k[-4:]}: {s['calls']}{cap} calls, exhausted={s['exhausted']}")
        return "\n".join(lines)


_MANAGERS: dict[str, RotatingKeys] = {}


def get_manager(provider: str) -> RotatingKeys:
    if provider not in _MANAGERS:
        if provider == "cohere":
            _MANAGERS[provider] = RotatingKeys(
                "cohere", config.MODELS["cohere"]["keys"](), PER_KEY_LIMIT)
        elif provider == "glm":
            _MANAGERS[provider] = RotatingKeys(
                "glm", config.MODELS["glm"]["keys"](), None)
        else:
            raise KeyError(provider)
    return _MANAGERS[provider]


def rotate(provider: str, make_call):
    """Run make_call(key) rotating keys on quota errors (process-safe)."""
    mgr = get_manager(provider)
    max_rotations = max(len(mgr.keys) * 2, 4)
    for attempt in range(max_rotations):
        key = mgr.get_key()
        try:
            result = make_call(key)
            mgr.mark_call(key)
            return result, key
        except Exception as e:
            if is_quota_error(e):
                mgr.mark_exhausted(key)
                continue
            if attempt < max_rotations - 1:
                time.sleep(min(5 * (2 ** attempt), 60))
            else:
                raise
    raise RuntimeError(f"{provider}: all keys exhausted during rotation.")


def call_with_rotation(make_call):
    """Back-compat wrapper for the Cohere pool."""
    return rotate("cohere", make_call)


if __name__ == "__main__":
    print("Cohere:")
    try:
        print(get_manager("cohere").usage_report())
        coh = get_manager("cohere")
        used = sum(coh._load().get(_fingerprint(k), {}).get("calls", 0) for k in coh.keys)
        remaining = sum(PER_KEY_LIMIT - coh._load().get(_fingerprint(k), {}).get("calls", 0)
                        for k in coh.keys
                        if not coh._load().get(_fingerprint(k), {}).get("exhausted"))
        print(f"  Capacity: {used} used, {remaining} remaining "
              f"({len(coh.keys)} keys x {PER_KEY_LIMIT}).")
        if remaining < NEED_SCREEN:
            print(f"  WARNING: below the ~{NEED_SCREEN} calls for the screening arm.")
        elif remaining < NEED_FULL:
            extra = -(-(NEED_FULL - remaining) // PER_KEY_LIMIT)
            print(f"  OK for screening. Full study needs ~{NEED_FULL} -> add {extra} more key(s).")
        else:
            print("  OK for the full study.")
    except RuntimeError as e:
        print(f"  {e}")
    print("GLM (free tier, no fixed cap):")
    try:
        print(get_manager("glm").usage_report())
    except RuntimeError as e:
        print(f"  {e}")
