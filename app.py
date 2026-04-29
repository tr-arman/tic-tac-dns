# external
from argparse import ArgumentParser
from random import choice
from socket import socket, AF_INET, SOCK_DGRAM
from string import ascii_lowercase, digits
from subprocess import Popen
from sys import executable
from threading import Thread
from time import sleep

# internal
from server import Server


def arguments() -> dict:
 parser = ArgumentParser()
 parser.add_argument('--port', default=53535, type=int)
 parser.add_argument('--zone', default='game.local')
 parser.add_argument('--db', default='dns-tac-toe.db')
 return parser.parse_args().__dict__


def local() -> str:
 sock = socket(AF_INET, SOCK_DGRAM)
 try:
  sock.connect(('8.8.8.8', 80)); return sock.getsockname()[0]
 except Exception: return '127.0.0.1'
 finally: sock.close()


def room() -> str:
 return 'r' + ''.join(choice(ascii_lowercase + digits) for _ in range(5))


class App:
 def __init__(self) -> None:
  self.args: dict = arguments()
  self.room: str = room()

 def main(self) -> None:
  args: dict = {'host': '0.0.0.0', 'port': self.args['port'], 'zone': self.args['zone'], 'db': self.args['db']}
  Thread(target=Server(args).main, daemon=True).start(); sleep(.4)
  print('\nplayer 2 command:\n')
  print(f'client.py --server {local()} --port {self.args["port"]} --zone {self.args["zone"]} --room {self.room} --player player2\n')
  Popen([executable, 'client.py', '--server', '127.0.0.1', '--port', str(self.args['port']), '--zone', self.args['zone'], '--room', self.room, '--player', 'player1'])
  while True: sleep(3600)


if __name__ == '__main__':
 (_ := App()).main()
