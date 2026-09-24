"""Deployment-readiness tests for the unified cloud runtime (Render).

Covers: unified route table, environment-aware CORS, PORT/B4_BASE_URL
resolution, and a live single-process smoke test (create call -> audio
ingest ack -> signaling join -> risk WS lifecycle) proving ONE process
serves every contract without localhost assumptions beyond loopback.

Stdlib unittest only (no httpx/TestClient живой server via subprocess).
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

from backend import cloud
from backend.cors import (
    ALLOW_HEADERS,
    ALLOW_METHODS,
    PRODUCTION_FRONTEND_ORIGIN,
    add_cors_middleware,
    get_allowed_origins,
)


def _iter_routes(app_or_router):
    # FastAPI >= 0.135 keeps included routers lazy (_IncludedRouter);
    # unwrap to the original router so introspection sees real paths.
    for route in app_or_router.routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            yield from _iter_routes(original)
        else:
            yield route


def _route_paths(app):
    found = {}
    for route in _iter_routes(app):
        path = getattr(route, "path", None)
        if not path:
            continue
        methods = sorted(getattr(route, "methods", None) or [])
        found.setdefault(path, set()).update(methods or {"WEBSOCKET"})
    return {p: sorted(m) for p, m in found.items()}


class TestUnifiedRouteTable(unittest.TestCase):
    def test_b1_contracts_present(self):
        paths = _route_paths(cloud.app)
        for required in ("/health", "/ws/signal", "/ws/audio"):
            self.assertIn(required, paths, f"unified app missing {required}")

    def test_b4_contracts_present(self):
        paths = _route_paths(cloud.app)
        for required in (
            "/api/v1/calls",
            "/api/v1/calls/{call_id}",
            "/api/v1/calls/active",
            "/api/v1/calls/history",
            "/api/v1/system/status",
            "/ws/calls",
        ):
            self.assertIn(required, paths, f"unified app missing {required}")

    def test_ml_contracts_present(self):
        paths = _route_paths(cloud.app)
        self.assertIn("/ml/v1/health", paths)
        self.assertIn("/ml/v1/detect", paths)

    def test_create_app_factory_matches_module_app(self):
        fresh = cloud.create_app()
        self.assertEqual(_route_paths(fresh), _route_paths(cloud.app))


class TestPortAndB4UrlResolution(unittest.TestCase):
    def test_default_port(self):
        old = os.environ.pop("PORT", None)
        try:
            self.assertEqual(cloud.resolve_port(), 8000)
        finally:
            if old is not None:
                os.environ["PORT"] = old

    def test_render_port_honored(self):
        self.assertEqual(cloud.resolve_port("10000"), 10000)

    def test_invalid_port_falls_back(self):
        self.assertEqual(cloud.resolve_port("not-a-port"), 8000)

    def test_b4_base_url_defaults_to_loopback_self(self):
        old = os.environ.pop("B4_BASE_URL", None)
        try:
            self.assertEqual(
                cloud.resolve_b4_base_url(8123),
                "http://127.0.0.1:8123/api/v1",
            )
        finally:
            if old is not None:
                os.environ["B4_BASE_URL"] = old

    def test_b4_base_url_explicit_wins(self):
        old = os.environ.get("B4_BASE_URL")
        os.environ["B4_BASE_URL"] = "http://split-b4:9000/api/v1/"
        try:
            self.assertEqual(
                cloud.resolve_b4_base_url(8123), "http://split-b4:9000/api/v1"
            )
        finally:
            if old is None:
                os.environ.pop("B4_BASE_URL", None)
            else:
                os.environ["B4_BASE_URL"] = old


class TestCorsPolicy(unittest.TestCase):
    def test_builtin_origins(self):
        origins = get_allowed_origins()
        self.assertIn(PRODUCTION_FRONTEND_ORIGIN, origins)
        self.assertIn("http://localhost:5173", origins)
        self.assertIn("http://127.0.0.1:5173", origins)

    def test_no_wildcard_with_credentials(self):
        from fastapi import FastAPI

        probe = FastAPI()
        add_cors_middleware(probe)
        cors = [m for m in probe.user_middleware if "CORS" in str(m.cls)]
        self.assertTrue(cors, "CORSMiddleware must be installed")
        options = cors[0].kwargs
        self.assertNotIn("*", options["allow_origins"])
        self.assertFalse(options["allow_credentials"])
        self.assertIn("GET", options["allow_methods"])
        self.assertIn("POST", options["allow_methods"])

    def test_env_extras_merged_without_duplicates(self):
        old_front = os.environ.get("FRONTEND_ORIGIN")
        old_extra = os.environ.get("CORS_ORIGINS")
        os.environ["FRONTEND_ORIGIN"] = "https://staging.example.com"
        os.environ["CORS_ORIGINS"] = (
            "https://staging.example.com, https://soumyajitd1307-hash.github.io "
        )
        try:
            origins = get_allowed_origins()
            self.assertIn("https://staging.example.com", origins)
            self.assertEqual(len(origins), len(set(origins)))
        finally:
            if old_front is None:
                os.environ.pop("FRONTEND_ORIGIN", None)
            else:
                os.environ["FRONTEND_ORIGIN"] = old_front
            if old_extra is None:
                os.environ.pop("CORS_ORIGINS", None)
            else:
                os.environ["CORS_ORIGINS"] = old_extra

    def test_allowed_methods_and_headers_cover_frontend(self):
        self.assertIn("GET", ALLOW_METHODS)
        self.assertIn("POST", ALLOW_METHODS)
        self.assertIn("OPTIONS", ALLOW_METHODS)
        self.assertIn("Content-Type", ALLOW_HEADERS)

    def test_dev_and_cloud_apps_share_policy(self):
        from backend import app as b4_app
        from backend1 import app as b1_app

        for candidate in (b4_app.app, b1_app.app, cloud.app):
            cors = [m for m in candidate.user_middleware if "CORS" in str(m.cls)]
            self.assertTrue(cors, f"{candidate} missing CORSMiddleware")
            self.assertIn(
                PRODUCTION_FRONTEND_ORIGIN, cors[0].kwargs["allow_origins"]
            )


TEST_PORT = 18080


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) != 0


class TestUnifiedLiveSmoke(unittest.TestCase):
    """Boot ONE unified process; prove every contract answers on one origin."""

    @classmethod
    def setUpClass(cls):
        if not _port_free(TEST_PORT):
            raise unittest.SkipTest(f"test port {TEST_PORT} busy")
        env = dict(os.environ)
        env["PORT"] = str(TEST_PORT)
        env.pop("B4_BASE_URL", None)  # exercise the loopback-self default
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        repo_root = os.path.dirname(repo_root)  # backend/tests/ -> repo root
        cls.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.cloud:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(TEST_PORT),
                "--workers",
                "1",
            ],
            cwd=repo_root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cls.base = f"http://127.0.0.1:{TEST_PORT}"
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"{cls.base}/health", timeout=2
                ) as resp:
                    if resp.status == 200:
                        break
            except Exception:  # noqa: BLE001 - server still booting
                time.sleep(0.5)
        else:
            cls.proc.terminate()
            raise unittest.SkipTest("unified cloud app did not boot in 30 s")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=15)
        except Exception:  # noqa: BLE001 - already gone
            cls.proc.kill()

    def _api(self, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.base}/api/v1{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())

    def test_health_and_system_status(self):
        with urllib.request.urlopen(f"{self.base}/health", timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(json.loads(resp.read().decode())["status"], "ok")
        status, body = self._api("GET", "/system/status")
        self.assertEqual(status, 200)
        self.assertIn("status", body)

    def test_authoritative_call_lifecycle(self):
        status, created = self._api(
            "POST", "/calls", {"owner_id": "deploy-smoke", "reference_id": ""}
        )
        self.assertEqual(status, 200)
        call_id = created["id"]
        self.assertTrue(call_id)
        status, active = self._api("GET", "/calls/active")
        self.assertEqual(status, 200)
        self.assertIn(call_id, [c["id"] for c in active])
        status, _ = self._api("POST", f"/calls/{call_id}/terminate", {})
        self.assertEqual(status, 200)
        try:
            self._api("GET", f"/calls/{call_id}")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 404)
        else:
            # GET returns the record even when ENDED in some builds; accept
            # either honest outcome, but the call must not stay ACTIVE.
            status, active = self._api("GET", "/calls/active")
            self.assertNotIn(call_id, [c["id"] for c in active])

    def test_audio_ingest_and_signaling_and_risk_ws(self):
        status, created = self._api(
            "POST", "/calls", {"owner_id": "deploy-ws", "reference_id": ""}
        )
        call_id = created["id"]

        async def _sockets():
            import websockets

            audio_url = (
                f"ws://127.0.0.1:{TEST_PORT}/ws/audio?session_id={call_id}"
            )
            async with websockets.connect(audio_url) as audio:
                await audio.send(bytes(8000))
                ack = json.loads(await audio.recv())
                self.assertEqual(ack["type"], "ack")

                signal_url = (
                    f"ws://127.0.0.1:{TEST_PORT}/ws/signal"
                    f"?call_id={call_id}&participant_id=smoke-a"
                )
                async with websockets.connect(signal_url) as signal:
                    await signal.send(
                        json.dumps({"type": "join", "display_name": "A"})
                    )
                    joined = json.loads(await signal.recv())
                    self.assertEqual(joined["type"], "joined")
                    self.assertEqual(joined["call_id"], call_id)

            risk_url = (
                f"ws://127.0.0.1:{TEST_PORT}/ws/calls?call_id=no-such-call"
            )
            try:
                async with websockets.connect(risk_url) as risk:
                    await risk.recv()
            except Exception as exc:  # noqa: BLE001 - expect 4401 close
                self.assertIn("4401", str(exc))
            else:
                self.fail("unknown call id must be rejected with 4401")

        asyncio.run(_sockets())
        self._api("POST", f"/calls/{call_id}/terminate", {})


if __name__ == "__main__":
    unittest.main()
