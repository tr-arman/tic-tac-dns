# external
from sqlite3 import connect
from threading import RLock
from time import time


EMPTY: str = '-'
WIN: tuple[tuple[int, int, int], ...] = ((0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6))


def clean(s: str) -> str:
 out: str = ''.join(c for c in str(s).lower() if c.isalnum() or c in ('-', '_'))
 return out or 'anon'


def winner(board: str) -> str | None:
 for a, b, c in WIN:
  if board[a] != EMPTY and board[a] == board[b] == board[c]: return board[a]
 return None


class Game:
 def __init__(self, path: str = 'dns-tac-toe.db') -> None:
  self.lock = RLock()
  self.db = connect(path, check_same_thread=False)
  self.db.row_factory = lambda cur, row: {col[0]: row[i] for i, col in enumerate(cur.description)}
  with self.db:
   self.db.execute('create table if not exists room(id text primary key, board text, x text, o text, turn text, state text, msg text, ts real)')
   self.db.execute('create table if not exists req(room text, player text, seq int, frame text, primary key(room, player, seq))')

 def dispatch(self, room: str, player: str, seq: int, cmd: str, args: list[str]) -> str:
  room, player, cmd = clean(room), clean(player), clean(cmd)
  with self.lock:
   if old := self.db.execute('select frame from req where room=? and player=? and seq=?', (room, player, seq)).fetchone(): return old['frame']
   self.open(room)
   frame: str = self.join(room, player) if cmd == 'join' else self.poll(room, player) if cmd == 'poll' else self.move(room, player, args) if cmd == 'move' else self.reset(room, player) if cmd == 'reset' else self.poll(room, player, 'unknown command')
   self.db.execute('insert or replace into req values(?, ?, ?, ?)', (room, player, seq, frame))
   self.db.commit(); return frame

 def open(self, room: str) -> None:
  if not self.db.execute('select id from room where id=?', (room,)).fetchone():
   self.db.execute('insert into room values(?, ?, ?, ?, ?, ?, ?, ?)', (room, EMPTY * 9, None, None, 'X', 'waiting', 'room created', time()))

 def room(self, room: str) -> dict:
  return self.db.execute('select * from room where id=?', (room,)).fetchone()

 def mark(self, r: dict, player: str) -> str:
  return 'X' if r['x'] == player else 'O' if r['o'] == player else 'S'

 def join(self, room: str, player: str) -> str:
  r: dict = self.room(room)
  if player in (r['x'], r['o']): return self.poll(room, player, 'reconnected')
  if not r['x']:
   self.db.execute('update room set x=?, msg=?, ts=? where id=?', (player, f'{player} joined as X', time(), room))
  elif not r['o']:
   self.db.execute('update room set o=?, state=?, msg=?, ts=? where id=?', (player, 'playing', f'{player} joined as O', time(), room))
  else: return self.poll(room, player, 'room full; spectator')
  return self.poll(room, player)

 def move(self, room: str, player: str, args: list[str]) -> str:
  r: dict = self.room(room); mark: str = self.mark(r, player)
  if mark == 'S': return self.poll(room, player, 'spectators cannot move')
  if r['state'] != 'playing': return self.poll(room, player, 'waiting for second player')
  if r['turn'] != mark: return self.poll(room, player, f'not your turn; waiting for {r["turn"]}')
  try: pos: int = int(args[0]) - 1
  except Exception: return self.poll(room, player, 'press 1-9 to move')
  board: list[str] = list(r['board'])
  if pos < 0 or pos > 8 or board[pos] != EMPTY: return self.poll(room, player, 'invalid move')
  board[pos] = mark; b: str = ''.join(board)
  state, turn, msg = 'playing', ('O' if mark == 'X' else 'X'), f'{player} placed {mark} at {pos + 1}'
  if winner(b): state, turn, msg = 'finished', mark, f'{player} wins'
  elif EMPTY not in b: state, msg = 'draw', 'draw'
  self.db.execute('update room set board=?, turn=?, state=?, msg=?, ts=? where id=?', (b, turn, state, msg, time(), room))
  return self.poll(room, player)

 def reset(self, room: str, player: str) -> str:
  r: dict = self.room(room); state: str = 'playing' if r['x'] and r['o'] else 'waiting'
  self.db.execute('update room set board=?, turn=?, state=?, msg=?, ts=? where id=?', (EMPTY * 9, 'X', state, f'{player} reset the board', time(), room))
  return self.poll(room, player)

 def poll(self, room: str, player: str, msg: str | None = None) -> str:
  r: dict = self.room(room); board: str = r['board']; cell: list[str] = [board[i] if board[i] != EMPTY else str(i + 1) for i in range(9)]
  return f'''DNS TAC TOE
room: {room}     you: {player} ({self.mark(r, player)})
X: {r['x'] or '-'}     O: {r['o'] or '-'}
state: {r['state']}     turn: {r['turn']}

        {cell[0]} | {cell[1]} | {cell[2]}
       ---+---+---
        {cell[3]} | {cell[4]} | {cell[5]}
       ---+---+---
        {cell[6]} | {cell[7]} | {cell[8]}

keys: 1-9 move | r reset | q quit
server: {msg or r['msg'] or ''}'''
