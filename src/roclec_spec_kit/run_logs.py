"""Bounded, local capture of two process streams."""
from __future__ import annotations

import hashlib
import os
import re
import selectors
import signal
import subprocess
import time


def allowed_environment(configured):
    allowed = {"PATH", "HOME", "TMPDIR", "LANG", "LANGUAGE", *configured}
    return {key: value for key, value in os.environ.items() if key in allowed or key.startswith("LC_")}


class Capture:
    def __init__(self, path, prefix_limit):
        self.path = path
        self.prefix_limit = prefix_limit
        self.size = 0
        self.hash = hashlib.sha256()
        self.prefix = bytearray()
        self.file = None

    def open(self, store):
        path = store.path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.file = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)

    def append(self, content):
        data = memoryview(content)
        while data:
            written = os.write(self.file, data)
            if written <= 0:
                raise OSError("Log write made no progress")
            chunk = data[:written]
            self.size += written
            self.hash.update(chunk)
            self.prefix.extend(chunk[:self.prefix_limit - len(self.prefix)])
            data = data[written:]

    def record(self, complete, limit, secrets, patterns):
        record = {"path": self.path, "sha256": self.hash.hexdigest(), "size": self.size, "complete": complete}
        if limit:
            excerpt = self.prefix.decode("utf-8", "replace")
            for secret in secrets:
                excerpt = excerpt.replace(secret, "[REDACTED]")
            for pattern in patterns:
                excerpt = re.sub(pattern, "[REDACTED]", excerpt)
            record["excerpt"] = excerpt.encode("utf-8")[:limit].decode("utf-8", "ignore")
        return record


def collect(process, captures, timeout, budget):
    deadline = time.monotonic() + timeout
    with selectors.DefaultSelector() as selector:
        for label in ("stdout", "stderr"):
            selector.register(getattr(process, label), selectors.EVENT_READ, captures[label])
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, timeout)
            for key, _ in selector.select(remaining):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                try:
                    key.data.append(chunk[:budget])
                except OSError:
                    return "log write failed"
                if len(chunk) > budget:
                    return "log quota exceeded"
                budget -= len(chunk)
        process.wait(timeout=max(0, deadline - time.monotonic()))
    return None


def execute(store, check, cwd, log_root, index, profile, quota):
    env = allowed_environment(check.get("env", []))
    secrets = sorted({os.environ[key] for key in profile.get("secret_env", []) if os.environ.get(key)}, key=len, reverse=True)
    limit = profile.get("max_log_bytes", 0)
    prefix_limit = limit + max((len(secret.encode("utf-8", "replace")) for secret in secrets), default=0) if limit else 0
    captures = {label: Capture(f"{log_root}/{index:03}.{label}", prefix_limit) for label in ("stdout", "stderr")}
    result = {"id": check["id"], "argv": check["argv"], "cwd": check["cwd"],
              "acceptance_ids": check.get("acceptance_ids", []), "executed_by_roclec": False, "environment": sorted(env)}
    start = time.monotonic()
    process = None
    status, code, limitation = "incomplete", None, None
    io_limitation = "log write failed"
    try:
        for capture in captures.values():
            capture.open(store)
        io_limitation = "environment: executable or working directory unavailable"
        process = subprocess.Popen(check["argv"], cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        result["executed_by_roclec"] = True
        io_limitation = "log read failed"
        limitation = collect(process, captures, check["timeout_seconds"], quota)
        if limitation is None:
            code = process.returncode
            status = "pass" if code == 0 else "fail"
    except subprocess.TimeoutExpired:
        limitation = "timeout"
    except KeyboardInterrupt:
        status, limitation = "interrupted", "interrupted"
    except OSError:
        limitation = io_limitation
    finally:
        if process is not None:
            if limitation is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.stdout.close()
            process.stderr.close()
            process.wait()
        for capture in captures.values():
            if capture.file is not None:
                try:
                    os.fsync(capture.file)
                except OSError:
                    status, code, limitation = "incomplete", None, "log write failed"
                finally:
                    os.close(capture.file)
    result.update(status=status, returncode=code, duration_seconds=round(time.monotonic() - start, 6))
    if limitation:
        result["limitation"] = limitation
    for label, capture in captures.items():
        result[label] = capture.record(limitation is None, limit, secrets, profile.get("redact_patterns", []))
    return result, sum(capture.size for capture in captures.values())
