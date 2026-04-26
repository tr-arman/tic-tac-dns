#!/usr/bin/env python3
"""
DNS Tic-Tac-Toe authoritative server.

All game traffic is DNS TXT queries. Run locally on 53535, or on port 53
for a delegated real subdomain.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import random
import re
import sqlite3
import string
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from dnslib import DNSLabel, DNSRecord, QTYPE, RR, TXT
from dnslib.server import BaseResolver, DNSLogger, DNSServer

ALLOWED = re.compile(r"^[a-z0-9_-]{1,32}$")
BOARD_EMPTY = "---------"


def now() -> int:
    return int(time.time())


def clean_token(value: str, fallback: str = "anon") -> str:
    value = value.strip().lower().replace(".", "-")[:32]
    value = re.sub(r"[^a-z0-9_-]", "-", value)
    value = value.strip("-")
    return value if ALLOWED.match(value or "") else fallback


def random_room() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(6))


def encode_payload(payload: dict[str, Any]) -> list[str]:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    b64 = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    data = "v1|" + b64
    # TXT string limit is 255 bytes. Stay below that.
    return [data[i : i + 240] for i in range(0, len(data), 240)] or ["v1|e30"]


def winner(board: str) -> Optional[str]:
    wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
    for a,b,c in wins:
        if board[a] != "-" and board[a] == board[b] == board[c]:
            return board[a]
    if "-" not in board:
        return "draw"
    return None


@dataclass
class Request:
    nonce: str
    room: str
    player: str
    seq: int
    since: int
    command: str
    args: list[str]


class Store:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        with self.db:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("""
            CREATE TABLE IF NOT EXISTS rooms(
                room TEXT PRIMARY KEY,
                board TEXT NOT NULL,
                turn TEXT NOT NULL,
                status TEXT NOT NULL,
                winner TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )""")
            self.db.execute("""
            CREATE TABLE IF NOT EXISTS players(
                room TEXT NOT NULL,
                player TEXT NOT NULL,
                symbol TEXT NOT NULL,
                last_seen INTEGER NOT NULL,
                PRIMARY KEY(room, player)
            )""")
            self.db.execute("""
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room TEXT NOT NULL,
                ts INTEGER NOT NULL,
                type TEXT NOT NULL,
                player TEXT,
                data TEXT NOT NULL
            )""")
            self.db.execute("""
            CREATE TABLE IF NOT EXISTS processed(
                room TEXT NOT NULL,
                player TEXT NOT NULL,
                seq INTEGER NOT NULL,
                response TEXT NOT NULL,
                ts INTEGER NOT NULL,
                PRIMARY KEY(room, player, seq)
            )""")

    def _event(self, room: str, typ: str, player: Optional[str], data: dict[str, Any]) -> int:
        cur = self.db.execute(
            "INSERT INTO events(room,ts,type,player,data) VALUES(?,?,?,?,?)",
            (room, now(), typ, player, json.dumps(data, separators=(",", ":"))),
        )
        return int(cur.lastrowid)

    def _ensure_room(self, room: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO rooms(room,board,turn,status,winner,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (room, BOARD_EMPTY, "X", "waiting", None, now(), now()),
        )

    def _room(self, room: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM rooms WHERE room=?", (room,)).fetchone()
        if row is None:
            self._ensure_room(room)
            row = self.db.execute("SELECT * FROM rooms WHERE room=?", (room,)).fetchone()
        return row

    def _players(self, room: str) -> list[sqlite3.Row]:
        return list(self.db.execute("SELECT * FROM players WHERE room=? ORDER BY symbol", (room,)).fetchall())

    def _snapshot(self, room: str, since: int = 0, message: str = "ok", ok: bool = True) -> dict[str, Any]:
        r = self._room(room)
        players = [{"id": p["player"], "symbol": p["symbol"]} for p in self._players(room)]
        events = []
        for e in self.db.execute(
            "SELECT * FROM events WHERE room=? AND id>? ORDER BY id ASC LIMIT 25", (room, since)
        ).fetchall():
            events.append({
                "id": e["id"], "ts": e["ts"], "type": e["type"], "player": e["player"],
                "data": json.loads(e["data"]),
            })
        latest = self.db.execute("SELECT COALESCE(MAX(id),0) AS id FROM events WHERE room=?", (room,)).fetchone()["id"]
        return {
            "ok": ok,
            "message": message,
            "room": room,
            "board": r["board"],
            "turn": r["turn"],
            "status": r["status"],
            "winner": r["winner"],
            "players": players,
            "events": events,
            "event_id": latest,
            "server_time": now(),
        }

    def handle(self, req: Request) -> dict[str, Any]:
        with self.lock:
            cached = self.db.execute(
                "SELECT response FROM processed WHERE room=? AND player=? AND seq=?",
                (req.room, req.player, req.seq),
            ).fetchone()
            if cached:
                return json.loads(cached["response"])

            with self.db:
                payload = self._handle_uncached(req)
                self.db.execute(
                    "INSERT OR REPLACE INTO processed(room,player,seq,response,ts) VALUES(?,?,?,?,?)",
                    (req.room, req.player, req.seq, json.dumps(payload, separators=(",", ":")), now()),
                )
                return payload

    def _handle_uncached(self, req: Request) -> dict[str, Any]:
        if not ALLOWED.match(req.room) or not ALLOWED.match(req.player):
            return {"ok": False, "message": "bad room/player token", "server_time": now()}
        self._ensure_room(req.room)
        self.db.execute("UPDATE rooms SET updated_at=? WHERE room=?", (now(), req.room))

        if req.command == "newroom":
            # Useful for raw DNS clients. Normal client picks a room locally.
            room = random_room()
            self._ensure_room(room)
            self._event(room, "room_created", req.player, {})
            return self._snapshot(room, req.since, "room created")

        if req.command == "join":
            return self._join(req)
        if req.command == "poll":
            self._touch(req.room, req.player)
            return self._snapshot(req.room, req.since)
        if req.command == "move":
            return self._move(req)
        if req.command == "reset":
            return self._reset(req)
        if req.command == "leave":
            return self._leave(req)
        return self._snapshot(req.room, req.since, f"unknown command: {req.command}", False)

    def _touch(self, room: str, player: str) -> None:
        self.db.execute("UPDATE players SET last_seen=? WHERE room=? AND player=?", (now(), room, player))

    def _join(self, req: Request) -> dict[str, Any]:
        existing = self.db.execute("SELECT * FROM players WHERE room=? AND player=?", (req.room, req.player)).fetchone()
        if existing:
            self._touch(req.room, req.player)
            self._event(req.room, "rejoined", req.player, {"symbol": existing["symbol"]})
            return self._snapshot(req.room, req.since, f"rejoined as {existing['symbol']}")

        symbols = {p["symbol"] for p in self._players(req.room)}
        if "X" not in symbols:
            sym = "X"
        elif "O" not in symbols:
            sym = "O"
        else:
            # spectating is allowed but cannot move
            sym = "S"
        self.db.execute(
            "INSERT INTO players(room,player,symbol,last_seen) VALUES(?,?,?,?)",
            (req.room, req.player, sym, now()),
        )
        count_playing = len([p for p in self._players(req.room) if p["symbol"] in ("X", "O")])
        if count_playing == 2:
            self.db.execute("UPDATE rooms SET status='playing',updated_at=? WHERE room=? AND status='waiting'", (now(), req.room))
        self._event(req.room, "joined", req.player, {"symbol": sym})
        return self._snapshot(req.room, req.since, f"joined as {sym}")

    def _move(self, req: Request) -> dict[str, Any]:
        if not req.args:
            return self._snapshot(req.room, req.since, "move needs a cell number 1-9", False)
        try:
            pos = int(req.args[0]) - 1
        except ValueError:
            return self._snapshot(req.room, req.since, "bad move position", False)
        if pos < 0 or pos > 8:
            return self._snapshot(req.room, req.since, "move must be 1-9", False)

        player = self.db.execute("SELECT * FROM players WHERE room=? AND player=?", (req.room, req.player)).fetchone()
        if not player:
            return self._snapshot(req.room, req.since, "join first", False)
        sym = player["symbol"]
        if sym not in ("X", "O"):
            return self._snapshot(req.room, req.since, "spectators cannot move", False)

        r = self._room(req.room)
        if r["status"] == "waiting":
            return self._snapshot(req.room, req.since, "waiting for second player", False)
        if r["status"] == "finished":
            return self._snapshot(req.room, req.since, "game is finished; use reset", False)
        if r["turn"] != sym:
            return self._snapshot(req.room, req.since, f"not your turn; it is {r['turn']}'s turn", False)
        board = r["board"]
        if board[pos] != "-":
            return self._snapshot(req.room, req.since, "cell already taken", False)

        new_board = board[:pos] + sym + board[pos + 1:]
        win = winner(new_board)
        if win == "draw":
            status, win_value, next_turn = "finished", "draw", r["turn"]
        elif win in ("X", "O"):
            status, win_value, next_turn = "finished", win, r["turn"]
        else:
            status, win_value, next_turn = "playing", None, "O" if sym == "X" else "X"
        self.db.execute(
            "UPDATE rooms SET board=?,turn=?,status=?,winner=?,updated_at=? WHERE room=?",
            (new_board, next_turn, status, win_value, now(), req.room),
        )
        self._touch(req.room, req.player)
        self._event(req.room, "move", req.player, {"symbol": sym, "cell": pos + 1})
        if status == "finished":
            self._event(req.room, "finished", None, {"winner": win_value})
        return self._snapshot(req.room, req.since, "move accepted")

    def _reset(self, req: Request) -> dict[str, Any]:
        self._ensure_room(req.room)
        self.db.execute(
            "UPDATE rooms SET board=?,turn='X',status=CASE WHEN (SELECT COUNT(*) FROM players WHERE room=? AND symbol IN ('X','O')) >= 2 THEN 'playing' ELSE 'waiting' END,winner=NULL,updated_at=? WHERE room=?",
            (BOARD_EMPTY, req.room, now(), req.room),
        )
        self._touch(req.room, req.player)
        self._event(req.room, "reset", req.player, {})
        return self._snapshot(req.room, req.since, "game reset")

    def _leave(self, req: Request) -> dict[str, Any]:
        self.db.execute("DELETE FROM players WHERE room=? AND player=?", (req.room, req.player))
        self._event(req.room, "left", req.player, {})
        return self._snapshot(req.room, req.since, "left room")


class TicTacToeResolver(BaseResolver):
    def __init__(self, zone: str, store: Store):
        self.zone = zone.rstrip(".").lower()
        self.zone_label = DNSLabel(self.zone)
        self.store = store

    def _parse(self, qname: str) -> Request:
        name = qname.rstrip(".").lower()
        if not name.endswith(self.zone):
            raise ValueError("query outside zone")
        prefix = name[: -(len(self.zone))].rstrip(".")
        parts = prefix.split(".") if prefix else []
        # <nonce>.<room>.<player>.<seq>.<since>.<command>[.<args>].zone
        if len(parts) < 6:
            raise ValueError("expected nonce.room.player.seq.since.command[.args].zone")
        nonce, room, player, seq, since, command, *args = parts
        return Request(
            nonce=clean_token(nonce, "n"), room=clean_token(room, "room"), player=clean_token(player, "anon"),
            seq=int(seq), since=int(since), command=clean_token(command, "poll"),
            args=[clean_token(a, "arg") for a in args],
        )

    def resolve(self, request: DNSRecord, handler: Any) -> DNSRecord:
        qname = str(request.q.qname)
        qtype = QTYPE[request.q.qtype]
        reply = request.reply()
        reply.header.ra = 0
        reply.header.aa = 1
        if qtype not in ("TXT", "ANY"):
            reply.add_answer(RR(request.q.qname, QTYPE.TXT, rdata=TXT(encode_payload({"ok": False, "message": "use TXT queries"})), ttl=0))
            return reply
        try:
            req = self._parse(qname)
            payload = self.store.handle(req)
        except Exception as e:
            payload = {"ok": False, "message": str(e), "server_time": now()}
        reply.add_answer(RR(request.q.qname, QTYPE.TXT, rdata=TXT(encode_payload(payload)), ttl=0))
        return reply


def main() -> None:
    parser = argparse.ArgumentParser(description="DNS-only Tic-Tac-Toe authoritative server")
    parser.add_argument("--zone", default="game.local", help="DNS zone/subdomain, e.g. ttt.example.com")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=53535)
    parser.add_argument("--db", default="dns_ttt.sqlite3")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    store = Store(args.db)
    resolver = TicTacToeResolver(args.zone, store)
    logger = DNSLogger("-request,-reply,-truncated,-error" if args.quiet else "request,reply,truncated,error", False)
    udp = DNSServer(resolver, port=args.port, address=args.host, logger=logger, tcp=False)
    tcp = DNSServer(resolver, port=args.port, address=args.host, logger=logger, tcp=True)
    udp.start_thread()
    tcp.start_thread()
    print(f"DNS Tic-Tac-Toe server authoritative for {args.zone.rstrip('.')} on {args.host}:{args.port} UDP/TCP")
    print(f"State database: {os.path.abspath(args.db)}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping")


if __name__ == "__main__":
    main()
