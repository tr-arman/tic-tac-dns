# external
from argparse import ArgumentParser
from random import choice
from string import ascii_lowercase, digits
from threading import Thread
from time import sleep
from tkinter import Tk, Text

# internal
from dns import Dns


def arguments() -> dict:
 parser = ArgumentParser()
 for arg in ('server', 'room', 'player'):
  parser.add_argument(f'--{arg}', required=True)
 parser.add_argument('--port', default=53535, type=int)
 parser.add_argument('--zone', default='game.local')
 return parser.parse_args().__dict__


class Client:
 def __init__(self) -> None:
  self.args: dict = arguments()
  self.dns: Dns = Dns()
  self.seq: int = 0
  self.active: bool = True
  self.root: Tk = Tk()
  self.root.title(f'DNS Tac Toe - {self.args["player"]}')
  self.text: Text = Text(self.root, width=58, height=21, font=('Courier', 16), bg='black', fg='white')
  self.text.pack(); self.text.focus_set()
  self.text.bind('<Key>', self.key)
  self.root.protocol('WM_DELETE_WINDOW', self.close)

 def nonce(self) -> str:
  return 'n' + ''.join(choice(ascii_lowercase + digits) for _ in range(8))

 def qname(self, cmd: str, *args: str) -> str:
  self.seq += 1
  return '.'.join([self.nonce(), self.args['room'], self.args['player'], str(self.seq), cmd, *map(str, args), self.args['zone']])

 def send(self, cmd: str, *args: str) -> None:
  try: frame: str = self.dns.ask(self.args['server'], self.args['port'], self.qname(cmd, *args))
  except Exception as e: frame = f'DNS TAC TOE\n\nrequest failed: {e}'
  self.root.after(0, lambda: self.draw(frame))

 def draw(self, frame: str) -> None:
  self.text.delete('1.0', 'end')
  self.text.insert('1.0', frame)

 def key(self, event) -> str:
  c: str = event.char.lower()
  if c in '123456789': Thread(target=self.send, args=('move', c), daemon=True).start()
  if c == 'r': Thread(target=self.send, args=('reset',), daemon=True).start()
  if c == 'q': self.close()
  return 'break'

 def poll(self) -> None:
  self.send('join')
  while self.active:
   self.send('poll'); sleep(1)

 def close(self) -> None:
  self.active = False
  try: self.root.destroy()
  except Exception: pass

 def main(self) -> None:
  Thread(target=self.poll, daemon=True).start()
  self.root.mainloop()


if __name__ == '__main__':
 (_ := Client()).main()
