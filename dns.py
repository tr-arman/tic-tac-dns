# external
from random import randint
from socket import socket, AF_INET, SOCK_DGRAM
from struct import pack, unpack


TXT: int = 16
IN: int = 1


class Dns:
 def pack_name(self, name: str) -> bytes:
  out: bytes = b''
  for label in name.strip('.').split('.'):
   raw: bytes = label.encode()
   if len(raw) > 63: raise ValueError('label too long')
   out += bytes([len(raw)]) + raw
  return out + b'\x00'

 def unpack_name(self, data: bytes, off: int) -> tuple[str, int]:
  labels: list[str] = []
  jumped: bool = False
  next_off: int = off
  seen: set[int] = set()
  while True:
   ln: int = data[off]
   if ln & 0xc0 == 0xc0:
    ptr: int = ((ln & 0x3f) << 8) | data[off + 1]
    if ptr in seen: raise ValueError('pointer loop')
    seen.add(ptr)
    if not jumped: next_off = off + 2
    jumped = True; off = ptr; continue
   if ln == 0:
    off += 1
    if not jumped: next_off = off
    break
   off += 1
   labels.append(data[off:off + ln].decode(errors='replace'))
   off += ln
  return '.'.join(labels), next_off

 def query(self, name: str) -> tuple[int, bytes]:
  tid: int = randint(0, 0xffff)
  return tid, pack('!HHHHHH', tid, 0x0100, 1, 0, 0, 0) + self.pack_name(name) + pack('!HH', TXT, IN)

 def request(self, data: bytes) -> dict:
  tid, _, qd, _, _, _ = unpack('!HHHHHH', data[:12])
  if qd != 1: raise ValueError('one question only')
  name, off = self.unpack_name(data, 12)
  qtype, qclass = unpack('!HH', data[off:off + 4])
  return {'id': tid, 'name': name, 'type': qtype, 'class': qclass, 'question': data[12:off + 4]}

 def response(self, req: dict, text: str) -> bytes:
  raw: bytes = text.encode()
  rdata: bytes = b''
  for i in range(0, len(raw), 255):
   c: bytes = raw[i:i + 255]
   rdata += bytes([len(c)]) + c
  head: bytes = pack('!HHHHHH', req['id'], 0x8400, 1, 1, 0, 0)
  ans: bytes = pack('!HHHIH', 0xc00c, TXT, IN, 0, len(rdata)) + rdata
  return head + req['question'] + ans

 def answer(self, data: bytes, tid: int) -> str:
  rid, _, qd, an, _, _ = unpack('!HHHHHH', data[:12])
  if rid != tid: raise ValueError('transaction mismatch')
  off: int = 12
  for _ in range(qd): _, off = self.unpack_name(data, off); off += 4
  out: list[str] = []
  for _ in range(an):
   _, off = self.unpack_name(data, off)
   qtype, _, _, ln = unpack('!HHIH', data[off:off + 10]); off += 10
   end: int = off + ln
   if qtype != TXT: off = end; continue
   while off < end:
    size: int = data[off]; off += 1
    out.append(data[off:off + size].decode(errors='replace')); off += size
  return ''.join(out)

 def ask(self, host: str, port: int, name: str) -> str:
  tid, packet = self.query(name)
  with socket(AF_INET, SOCK_DGRAM) as sock:
   sock.settimeout(2)
   sock.sendto(packet, (host, port))
   data, _ = sock.recvfrom(4096)
  return self.answer(data, tid)
