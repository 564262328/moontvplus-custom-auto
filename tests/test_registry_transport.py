#!/usr/bin/env python3
"""Offline regression tests for registry transport precedence.

Run: python3 -m unittest discover -s tests -p 'test_registry_transport.py'
No Docker daemon, network, or production MoonTV service required.
"""
import pathlib
import re
import subprocess
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "nas" / "update-moontv.sh"


def function(name):
    text = SCRIPT.read_text()
    match = re.search(r"(?ms)^" + re.escape(name) + r"\(\) \{\n.*?^\}", text)
    if not match:
        raise AssertionError("missing function: " + name)
    return match.group(0)


def exercise(name, mode, direct_ok, proxy_ok, proxy_available=True):
    fn = function(name)
    with tempfile.TemporaryDirectory() as directory:
        setup = f"""
REGISTRY_PROXY_MODE={mode}
REMOTE_CHECK_RETRIES=1
REMOTE_CHECK_DELAY_SECONDS=0
LAST_REMOTE_DIGEST={directory}/digest
LAST_REMOTE_CHECK={directory}/checked
STATE_DIR={directory}
REMOTE_DIGEST=sha256:mock
ensure_skopeo() {{ return 0; }}
proxy_available() {{ {'return 0' if proxy_available and mode != 'off' else 'return 1'}; }}
inspect_remote_once() {{
  echo "inspect:$1" >> {directory}/calls
  if [ "$1" = direct ]; then {'return 0' if direct_ok else 'return 1'}; fi
  {'return 0' if proxy_ok else 'return 1'}
}}
pull_with_skopeo_mode() {{
  echo "pull:$1" >> {directory}/calls
  if [ "$1" = direct ]; then {'return 0' if direct_ok else 'return 1'}; fi
  {'return 0' if proxy_ok else 'return 1'}
}}
"""
        cmd = setup + "\n" + fn + "\n" + name + "\n"
        p = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True)
        calls = pathlib.Path(directory, "calls")
        return p.returncode, calls.read_text().splitlines() if calls.exists() else []


class RegistryPrecedence(unittest.TestCase):
    def test_direct_first_when_preferred(self):
        for fn in ("fetch_remote_metadata", "pull_with_skopeo"):
            with self.subTest(fn=fn):
                code, calls = exercise(fn, "prefer", True, True)
                self.assertEqual(code, 0)
                self.assertEqual(calls, ["inspect:direct" if fn.startswith("fetch") else "pull:direct"])

    def test_proxy_fallback(self):
        for fn in ("fetch_remote_metadata", "pull_with_skopeo"):
            with self.subTest(fn=fn):
                code, calls = exercise(fn, "prefer", False, True)
                self.assertEqual(code, 0)
                self.assertEqual(calls, [("inspect:" if fn.startswith("fetch") else "pull:") + mode for mode in ("direct", "proxy")])

    def test_force_proxy_only(self):
        for fn in ("fetch_remote_metadata", "pull_with_skopeo"):
            with self.subTest(fn=fn):
                code, calls = exercise(fn, "force", True, True)
                self.assertEqual(code, 0)
                self.assertEqual(calls, ["inspect:proxy" if fn.startswith("fetch") else "pull:proxy"])

    def test_off_direct_only(self):
        for fn in ("fetch_remote_metadata", "pull_with_skopeo"):
            with self.subTest(fn=fn):
                code, calls = exercise(fn, "off", False, True)
                self.assertNotEqual(code, 0)
                self.assertEqual(calls, ["inspect:direct" if fn.startswith("fetch") else "pull:direct"])

    def test_fails_closed_when_both_paths_fail(self):
        for fn in ("fetch_remote_metadata", "pull_with_skopeo"):
            with self.subTest(fn=fn):
                code, calls = exercise(fn, "prefer", False, False)
                self.assertNotEqual(code, 0)
                self.assertEqual(len(calls), 2)

    def test_direct_container_transport_clears_proxy_and_uses_host_network(self):
        for fn in ("run_skopeo_inspect", "pull_with_skopeo_mode"):
            with self.subTest(fn=fn):
                body = function(fn)
                direct = body.split('if [ "$mode" = "proxy" ]; then')[-1]
                self.assertIn("--network host", direct)
                for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                    self.assertIn("-e " + variable + "=", direct)


    def test_force_never_uses_docker_fallback(self):
        """Exercise real routing functions with stubbed network operations."""
        shell_functions = "\n".join(function(name) for name in (
            "pull_with_skopeo", "pull_with_docker", "pull_target_image"
        ))
        for strategy in ("skopeo", "skopeo-first", "docker-first"):
            for proxy_ok in (False, True):
                with self.subTest(strategy=strategy, proxy_ok=proxy_ok):
                    with tempfile.TemporaryDirectory() as directory:
                        setup = f"""
REGISTRY_PROXY_MODE=force
PULL_STRATEGY={strategy}
IMAGE=ghcr.io/example/test:stable
STATE_DIR={directory}
ensure_skopeo() {{ return 0; }}
proxy_available() {{ return 0; }}
pull_with_skopeo_mode() {{
  echo "skopeo:$1" >> {directory}/calls
  {'return 0' if proxy_ok else 'return 1'}
}}
run_with_timeout() {{ echo docker-invoked >> {directory}/calls; return 0; }}
"""
                        result = subprocess.run(
                            ["sh", "-c", setup + shell_functions + "\npull_target_image\n"],
                            capture_output=True, text=True
                        )
                        calls_path = pathlib.Path(directory) / "calls"
                        calls = calls_path.read_text().splitlines() if calls_path.exists() else []
                        self.assertEqual(calls, ["skopeo:proxy"])
                        self.assertEqual(result.returncode == 0, proxy_ok)

    def test_docker_pull_guard_rejects_force(self):
        with tempfile.TemporaryDirectory() as directory:
            setup = f"""
REGISTRY_PROXY_MODE=force
STATE_DIR={directory}
run_with_timeout() {{ echo docker-invoked > {directory}/calls; return 0; }}
"""
            result = subprocess.run(
                ["sh", "-c", setup + function("pull_with_docker") + "\npull_with_docker\n"],
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((pathlib.Path(directory) / "calls").exists())


if __name__ == "__main__":
    unittest.main()
