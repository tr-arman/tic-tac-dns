# DNS Tic-Tac-Toe — real DNS-only multiplayer

This is a fully playable two-player Tic-Tac-Toe game where the game traffic runs over DNS TXT queries/responses.

It is not HTTP, WebSocket, UDP game packets, or a separate API. The client sends commands by resolving DNS names. The server returns game state in TXT records.

## What is included

- Persistent rooms using SQLite
- Two-player symbol assignment: first player = X, second player = O
- Reconnect support using the same room/player name
- Spectators after the first two players
- Turn validation
- Win/draw detection
- Reset/leave commands
- Sequence numbers and idempotent command handling
- Event history and polling
- UDP and TCP DNS server support
- TXT payload encoding with base64url JSON
- TTL 0 to reduce caching issues

## Install

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Local test

Terminal 1:

```bash
python server.py --zone game.local --host 0.0.0.0 --port 53535
```

Terminal 2:

```bash
python client.py --server 127.0.0.1 --port 53535 --zone game.local --room demo --player arman
```

Terminal 3:

```bash
python client.py --server 127.0.0.1 --port 53535 --zone game.local --room demo --player friend
```

## Raw DNS examples

Join:

```bash
dig @127.0.0.1 -p 53535 TXT n1.demo.arman.1.0.join.game.local +short
```

Move to cell 5:

```bash
dig @127.0.0.1 -p 53535 TXT n2.demo.arman.2.0.move.5.game.local +short
```

Poll:

```bash
dig @127.0.0.1 -p 53535 TXT n3.demo.arman.3.0.poll.game.local +short
```

The response starts with `v1|` followed by base64url-encoded compact JSON.

## DNS protocol

Query format:

```text
<nonce>.<room>.<player>.<client_seq>.<since_event_id>.<command>[.<args>].<zone>
```

Examples:

```text
n8sd91ab.demo.arman.1.0.join.game.local
n8sd91ac.demo.arman.2.0.move.5.game.local
n8sd91ad.demo.arman.3.2.poll.game.local
```

Commands:

| Command | Args | Description |
|---|---:|---|
| `join` | none | Join or reconnect to a room |
| `poll` | none | Fetch latest state/events |
| `move` | cell 1-9 | Make a move |
| `reset` | none | Reset the board |
| `leave` | none | Leave the room |

## Running it on a real domain

You need a domain or subdomain you control, plus a VPS with a public IP.

Example:

- Domain: `example.com`
- DNS game zone: `ttt.example.com`
- VPS public IP: `203.0.113.10`

At your DNS provider, delegate the subdomain:

```text
ns1.ttt.example.com.    A     203.0.113.10
ttt.example.com.        NS    ns1.ttt.example.com.
```

Then run the server on the VPS:

```bash
sudo python server.py --zone ttt.example.com --host 0.0.0.0 --port 53 --db /var/lib/dns-ttt/dns_ttt.sqlite3 --quiet
```

Open firewall ports:

```bash
sudo ufw allow 53/udp
sudo ufw allow 53/tcp
```

Then clients can play with:

```bash
python client.py --server 203.0.113.10 --port 53 --zone ttt.example.com --room demo --player arman
```

You can also query through normal recursive resolvers after delegation propagates, but for gameplay direct-to-authoritative is more reliable because recursive DNS resolvers may cache or rate-limit weird-looking queries.

## Why direct-to-authoritative is recommended

The game is still DNS-only either way. But direct-to-authoritative avoids:

- resolver caching despite TTL 0
- ISP DNS filtering
- EDNS/TXT quirks
- recursive resolver rate limits
- delays from global DNS propagation

## Limitations

This is viable for Tic-Tac-Toe and similar turn-based games. It is not viable for fast real-time games. DNS is still request/response, small, cache-prone, and often monitored.
