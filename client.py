#!/usr/bin/env python3
"""Terminal client for DNS-only Tic-Tac-Toe."""
import argparse
import base64
import json
import os
import random
import re
import string
import time
from typing import Any

import dns.resolver

ALLOWED = re.compile(r"^[a-z0-9_-]{1,32}$")


def clean_token(value: str, fallback: str) -> str:
    value = value.strip().lower().replace(".", "-")[:32]
    value = re.sub(r"[^a-z0-9_-]", "-", value).strip("-")
    return value if ALLOWED.match(value or "") else fallback


def nonce() -> str:
    return "n" + "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))


def decode_txt(strings: list[str]) -> dict[str, Any]:
    joined = "".join(strings)
    if not joined.startswith("v1|"):
        raise ValueError(f"unknown response format: {joined[:20]}")
    b64 = joined[3:]
    b64 += "=" * (-len(b64) % 4)
    return json.loads(base64.urlsafe_b64decode(b64.encode("ascii")).decode("utf-8"))


class DNSGameClient:
    def __init__(self, server: str, port: int, zone: str, room: str, player: str, timeout: float):
        self.zone = zone.rstrip(".").lower()
        self.room = clean_token(room, "room")
        self.player = clean_token(player, "player")
        self.seq = 0
        self.event_id = 0
        self.resolver = dns.resolver.Resolver(configure=False)
        self.resolver.nameservers = [server]
        self.resolver.port = port
        self.resolver.timeout = timeout
        self.resolver.lifetime = timeout

    def request(self, command: str, *args: str, retry: int = 2) -> dict[str, Any]:
        self.seq += 1
        labels = [nonce(), self.room, self.player, str(self.seq), str(self.event_id), clean_token(command, "poll")]
        labels.extend(clean_token(a, "arg") for a in args)
        qname = ".".join(labels) + "." + self.zone
        last_err = None
        for _ in range(retry + 1):
            try:
                answer = self.resolver.resolve(qname, "TXT", raise_on_no_answer=True)
                chunks: list[str] = []
                for rr in answer:
                    for part in rr.strings:
                        chunks.append(part.decode("utf-8"))
                payload = decode_txt(chunks)
                self.event_id = max(self.event_id, int(payload.get("event_id", self.event_id) or 0))
                return payload
            except Exception as e:
                last_err = e
                time.sleep(0.25)
        raise RuntimeError(f"DNS request failed: {last_err}")


def clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def render_board(board: str) -> str:
    cells = [str(i + 1) if ch == "-" else ch for i, ch in enumerate(board)]
    return f"""
     {cells[0]} | {cells[1]} | {cells[2]}
    ---+---+---
     {cells[3]} | {cells[4]} | {cells[5]}
    ---+---+---
     {cells[6]} | {cells[7]} | {cells[8]}
"""


def my_symbol(payload: dict[str, Any], player: str) -> str:
    for p in payload.get("players", []):
        if p.get("id") == player:
            return p.get("symbol", "?")
    return "?"


def print_state(payload: dict[str, Any], player: str) -> None:
    clear()
    print("DNS TIC-TAC-TOE")
    print(f"Room: {payload.get('room')} | You: {player} ({my_symbol(payload, player)})")
    print(f"Status: {payload.get('status')} | Turn: {payload.get('turn')} | Winner: {payload.get('winner')}")
    print(render_board(payload.get("board", "---------")))
    players = ", ".join(f"{p['id']}={p['symbol']}" for p in payload.get("players", [])) or "none"
    print(f"Players: {players}")
    msg = payload.get("message")
    if msg:
        print(f"Message: {msg}")
    events = payload.get("events", [])[-5:]
    if events:
        print("\nRecent events:")
        for e in events:
            print(f"  #{e['id']} {e['type']} {e.get('player') or ''} {e.get('data')}")


def choose_room(arg_room: str | None) -> str:
    if arg_room:
        return clean_token(arg_room, "room")
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def main() -> None:
    parser = argparse.ArgumentParser(description="Play Tic-Tac-Toe fully over DNS TXT queries")
    parser.add_argument("--server", required=True, help="DNS server IP/hostname")
    parser.add_argument("--port", type=int, default=53535)
    parser.add_argument("--zone", default="game.local")
    parser.add_argument("--room", help="Room code. Omit to create a random room code locally.")
    parser.add_argument("--player", required=True)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--poll", type=float, default=1.0, help="Polling delay while waiting")
    args = parser.parse_args()

    room = choose_room(args.room)
    client = DNSGameClient(args.server, args.port, args.zone, room, args.player, args.timeout)
    print(f"Joining room {room} as {client.player} via DNS TXT queries...")
    state = client.request("join")
    while True:
        print_state(state, client.player)
        sym = my_symbol(state, client.player)
        if state.get("status") == "finished":
            choice = input("Game finished. Type r to reset, q to quit, or Enter to poll: ").strip().lower()
            if choice == "q":
                try: client.request("leave")
                except Exception: pass
                return
            if choice == "r":
                state = client.request("reset")
            else:
                state = client.request("poll")
            continue

        if state.get("status") == "waiting":
            print(f"\nWaiting for another player. Give them this room code: {room}")
            time.sleep(args.poll)
            state = client.request("poll")
            continue

        if sym not in ("X", "O"):
            print("\nYou are spectating. Press Ctrl+C to quit.")
            time.sleep(args.poll)
            state = client.request("poll")
            continue

        if state.get("turn") != sym:
            print("\nWaiting for opponent move...")
            time.sleep(args.poll)
            state = client.request("poll")
            continue

        move = input("Your move [1-9], r reset, q quit: ").strip().lower()
        if move == "q":
            try: client.request("leave")
            except Exception: pass
            return
        if move == "r":
            state = client.request("reset")
            continue
        if move in [str(i) for i in range(1, 10)]:
            state = client.request("move", move)
        else:
            state = client.request("poll")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBye")
