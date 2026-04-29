# dns-tac-toe

Multiplayer Tic-Tac-Toe where input, state, and the rendered game screen are transported through custom DNS TXT packets over UDP.

## run

```bash
python app.py
```

The host starts the DNS server and opens player 1. The terminal prints a player 2 command.

Local second player:

```bash
python client.py --server 127.0.0.1 --port 53535 --zone game.local --room <room> --player player2
```

## protocol

```text
<nonce>.<room>.<player>.<seq>.<command>[.<args>].<zone>
```

Example:

```text
n8d3fe2aa.r9x1k2.player1.4.move.5.game.local
```

The DNS TXT answer is the full ASCII frame shown in the client window.

## notes

No DNS libraries are used. DNS packets are encoded and decoded manually in `dns.py`.
