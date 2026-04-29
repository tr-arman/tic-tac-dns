# external
from argparse import ArgumentParser
from socket import socket, AF_INET, SOCK_DGRAM, SOL_SOCKET, SO_REUSEADDR
from time import strftime

# internal
from dns import Dns, TXT
from game import Game


def arguments() -> dict:
 parser = ArgumentParser()
 parser.add_argument('--host', default='0.0.0.0')
 parser.add_argument('--port', default=53535, type=int)
 parser.add_argument('--zone', default='game.local')
 parser.add_argument('--db', default='dns-tac-toe.db')
 return parser.parse_args().__dict__


class Server:
 def __init__(self, args: dict | None = None) -> None:
  self.args: dict = args or arguments()
  self.dns: Dns = Dns()
  self.game: Game = Game(self.args['db'])

 def log(self, msg: str) -> None:
  print(f'[{strftime("%H:%M:%S")}] {msg}', flush=True)

 def parse(self, name: str) -> tuple[str, str, int, str, list[str]]:
  zone: str = '.' + self.args['zone'].strip('.').lower()
  name = name.strip('.').lower()
  if not name.endswith(zone): raise ValueError('wrong zone')
  parts: list[str] = [p for p in name[:-len(zone)].split('.') if p]
  if len(parts) < 5: raise ValueError('nonce.room.player.seq.command.args.zone')
  _, room, player, seq, cmd, *args = parts
  return room, player, int(seq), cmd, args

 def handle(self, data: bytes, addr: tuple[str, int]) -> bytes | None:
  try:
   req: dict = self.dns.request(data)
   room, player, seq, cmd, args = self.parse(req['name'])
   self.log(f'{addr[0]}:{addr[1]} {req["name"]}')
   frame: str = 'DNS TAC TOE\n\nTXT records only.' if req['type'] != TXT else self.game.dispatch(room, player, seq, cmd, args)
   return self.dns.response(req, frame)
  except Exception as e:
   try: req = self.dns.request(data)
   except Exception: return None
   return self.dns.response(req, f'DNS TAC TOE\n\nerror: {e}')

 def main(self) -> None:
  with socket(AF_INET, SOCK_DGRAM) as sock:
   sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
   sock.bind((self.args['host'], self.args['port']))
   self.log(f'listening on {self.args["host"]}:{self.args["port"]} for *.{self.args["zone"]}')
   while True:
    data, addr = sock.recvfrom(4096)
    if res := self.handle(data, addr): sock.sendto(res, addr)


if __name__ == '__main__':
 (_ := Server()).main()
