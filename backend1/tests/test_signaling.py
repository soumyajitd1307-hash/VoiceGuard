"""Tests for the Backend 1 two-person WebRTC signaling hub (/ws/signal).

Verifies room join/roster, peer-joined/peer-left fan-out, and SDP/ICE
envelope relay between two participants sharing one call_id.
"""
from __future__ import annotations

import threading
import unittest

try:
    from fastapi.testclient import TestClient
    from backend1.app import app

    HAS_TESTCLIENT = True
except Exception:  # noqa: BLE001 - starlette raises RuntimeError w/o httpx
    HAS_TESTCLIENT = False


def _url(call_id: str, participant_id: str) -> str:
    return f"/ws/signal?call_id={call_id}&participant_id={participant_id}"


@unittest.skipUnless(HAS_TESTCLIENT, "fastapi or httpx not available for TestClient")
class TestSignalingHub(unittest.TestCase):
    def test_join_returns_empty_roster_for_first_peer(self):
        client = TestClient(app)
        with client.websocket_connect(_url("room-1", "alice")) as ws:
            ws.send_json({"type": "join", "display_name": "Alice"})
            joined = ws.receive_json()
            self.assertEqual(joined["type"], "joined")
            self.assertEqual(joined["call_id"], "room-1")
            self.assertEqual(joined["participant_id"], "alice")
            self.assertEqual(joined["peers"], [])

    def test_second_join_notifies_first_peer(self):
        client_a = TestClient(app)
        client_b = TestClient(app)
        with client_a.websocket_connect(_url("room-2", "alice")) as ws_a:
            ws_a.send_json({"type": "join", "display_name": "Alice"})
            self.assertEqual(ws_a.receive_json()["type"], "joined")
            with client_b.websocket_connect(_url("room-2", "bob")) as ws_b:
                ws_b.send_json({"type": "join", "display_name": "Bob"})
                joined_b = ws_b.receive_json()
                self.assertEqual(
                    [p["participant_id"] for p in joined_b["peers"]], ["alice"]
                )
                notice = ws_a.receive_json()
                self.assertEqual(notice["type"], "peer-joined")
                self.assertEqual(notice["participant_id"], "bob")
                self.assertEqual(notice["display_name"], "Bob")

    def test_offer_answer_ice_relay_between_two_peers(self):
        results: dict = {}
        errors: list = []

        def run_bob():
            try:
                client = TestClient(app)
                with client.websocket_connect(_url("room-3", "bob")) as ws_b:
                    ws_b.send_json({"type": "join", "display_name": "Bob"})
                    ws_b.receive_json()  # joined (sees alice)
                    offer = ws_b.receive_json()
                    results["offer"] = offer
                    ws_b.send_json(
                        {
                            "type": "answer",
                            "to": "alice",
                            "payload": {"sdp": "fake-answer-sdp"},
                        }
                    )
                    ice = ws_b.receive_json()
                    results["ice"] = ice
            except Exception as exc:  # noqa: BLE001 - surfaced below
                errors.append(exc)

        bob_thread = threading.Thread(target=run_bob, daemon=True)
        bob_thread.start()

        client_a = TestClient(app)
        with client_a.websocket_connect(_url("room-3", "alice")) as ws_a:
            ws_a.send_json({"type": "join", "display_name": "Alice"})
            ws_a.receive_json()  # joined (empty roster)
            notice = ws_a.receive_json()  # peer-joined bob
            self.assertEqual(notice["type"], "peer-joined")

            ws_a.send_json(
                {
                    "type": "offer",
                    "to": "bob",
                    "payload": {"sdp": "fake-offer-sdp"},
                }
            )
            answer = ws_a.receive_json()
            self.assertEqual(answer["type"], "answer")
            self.assertEqual(answer["from"], "bob")
            ws_a.send_json(
                {
                    "type": "ice",
                    "to": "bob",
                    "payload": {"candidate": "fake-candidate"},
                }
            )

        bob_thread.join(timeout=15)
        self.assertEqual(errors, [])
        self.assertEqual(results["offer"]["type"], "offer")
        self.assertEqual(results["offer"]["from"], "alice")
        self.assertEqual(results["offer"]["payload"], {"sdp": "fake-offer-sdp"})
        self.assertEqual(results["ice"]["type"], "ice")
        self.assertEqual(results["ice"]["from"], "alice")

    def test_relay_to_unknown_peer_returns_error(self):
        client = TestClient(app)
        with client.websocket_connect(_url("room-4", "alice")) as ws:
            ws.send_json({"type": "join", "display_name": "Alice"})
            ws.receive_json()  # joined
            ws.send_json(
                {"type": "offer", "to": "ghost", "payload": {"sdp": "x"}}
            )
            err = ws.receive_json()
            self.assertEqual(err["type"], "error")

    def test_missing_ids_rejected(self):
        client = TestClient(app)
        with client.websocket_connect("/ws/signal") as ws:
            err = ws.receive_json()
            self.assertEqual(err["type"], "error")


if __name__ == "__main__":
    unittest.main()
