"""Tiny DNS protocol helpers using only the Python standard library.
Supports enough DNS to run DNS Tac Toe: one-question queries and TXT answers.
No dnslib, dnspython, or external DNS packages.
"""
from __future__ import annotations

import random
import socket
import struct
from typing import Tuple, Optional

TYPE_TXT = 16
CLASS_IN = 1


def encode_name(name: str) -> bytes:
    name = name.strip('.')
    if not name:
        return b'\x00'
    out = bytearray()
    for label in name.split('.'):
        raw = label.encode('ascii')
        if len(raw) > 63:
            raise ValueError(f'DNS label too long: {label!r}')
        out.append(len(raw))
        out.extend(raw)
    out.append(0)
    return bytes(out)


def decode_name(packet: bytes, offset: int) -> Tuple[str, int]:
    labels = []
    jumped = False
    original_next = offset
    seen = set()
    while True:
        if offset >= len(packet):
            raise ValueError('name offset out of packet')
        length = packet[offset]
        # compression pointer: top two bits set
        if (length & 0xC0) == 0xC0:
            if offset + 1 >= len(packet):
                raise ValueError('truncated compression pointer')
            ptr = ((length & 0x3F) << 8) | packet[offset + 1]
            if ptr in seen:
                raise ValueError('compression pointer loop')
            seen.add(ptr)
            if not jumped:
                original_next = offset + 2
                jumped = True
            offset = ptr
            continue
        if length == 0:
            offset += 1
            if not jumped:
                original_next = offset
            break
        offset += 1
        label = packet[offset:offset + length]
        if len(label) != length:
            raise ValueError('truncated label')
        labels.append(label.decode('ascii', errors='replace'))
        offset += length
    return '.'.join(labels), original_next


def parse_query(packet: bytes) -> dict:
    if len(packet) < 12:
        raise ValueError('packet too short')
    tid, flags, qdcount, ancount, nscount, arcount = struct.unpack('!HHHHHH', packet[:12])
    if qdcount < 1:
        raise ValueError('no question in query')
    qname, off = decode_name(packet, 12)
    if off + 4 > len(packet):
        raise ValueError('truncated question')
    qtype, qclass = struct.unpack('!HH', packet[off:off + 4])
    question = packet[12:off + 4]
    return {
        'id': tid,
        'flags': flags,
        'qname': qname,
        'qtype': qtype,
        'qclass': qclass,
        'question': question,
    }


def _txt_rdata(text: str) -> bytes:
    raw = text.encode('utf-8')
    chunks = []
    # One TXT string is max 255 bytes. Multiple strings are valid TXT RDATA.
    for i in range(0, len(raw), 255):
        chunk = raw[i:i + 255]
        chunks.append(bytes([len(chunk)]) + chunk)
    return b''.join(chunks) or b'\x00'


def build_txt_response(query: dict, text: str, ttl: int = 0, rcode: int = 0) -> bytes:
    tid = query['id']
    # response + authoritative answer + recursion not available
    flags = 0x8400 | (rcode & 0xF)
    answer_count = 1 if rcode == 0 and query.get('qtype') in (TYPE_TXT, 255) else 0
    header = struct.pack('!HHHHHH', tid, flags, 1, answer_count, 0, 0)
    body = query['question']
    if answer_count:
        rdata = _txt_rdata(text)
        # name pointer to qname at offset 12
        body += struct.pack('!HHHIH', 0xC00C, TYPE_TXT, CLASS_IN, ttl, len(rdata)) + rdata
    return header + body


def build_query(qname: str, qtype: int = TYPE_TXT) -> Tuple[int, bytes]:
    tid = random.randint(0, 65535)
    flags = 0x0100  # standard query, recursion desired
    header = struct.pack('!HHHHHH', tid, flags, 1, 0, 0, 0)
    question = encode_name(qname) + struct.pack('!HH', qtype, CLASS_IN)
    return tid, header + question


def parse_txt_response(packet: bytes, expected_id: Optional[int] = None) -> str:
    if len(packet) < 12:
        raise ValueError('response too short')
    tid, flags, qdcount, ancount, *_ = struct.unpack('!HHHHHH', packet[:12])
    if expected_id is not None and tid != expected_id:
        raise ValueError('DNS transaction ID mismatch')
    rcode = flags & 0xF
    if rcode != 0:
        raise ValueError(f'DNS error rcode={rcode}')
    off = 12
    for _ in range(qdcount):
        _, off = decode_name(packet, off)
        off += 4
    texts = []
    for _ in range(ancount):
        _, off = decode_name(packet, off)
        if off + 10 > len(packet):
            raise ValueError('truncated answer header')
        atype, aclass, ttl, rdlen = struct.unpack('!HHIH', packet[off:off + 10])
        off += 10
        rdata = packet[off:off + rdlen]
        off += rdlen
        if atype == TYPE_TXT:
            i = 0
            parts = []
            while i < len(rdata):
                ln = rdata[i]
                i += 1
                parts.append(rdata[i:i + ln].decode('utf-8', errors='replace'))
                i += ln
            texts.append(''.join(parts))
    if not texts:
        raise ValueError('no TXT answer')
    return texts[0]


def udp_txt_query(server: str, port: int, qname: str, timeout: float = 2.0) -> str:
    tid, packet = build_query(qname)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        s.sendto(packet, (server, port))
        data, _ = s.recvfrom(4096)
    return parse_txt_response(data, tid)
