FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py client.py README.md ./
EXPOSE 53/udp 53/tcp 53535/udp 53535/tcp
CMD ["python", "server.py", "--zone", "game.local", "--host", "0.0.0.0", "--port", "53535", "--db", "/data/dns_ttt.sqlite3", "--quiet"]
