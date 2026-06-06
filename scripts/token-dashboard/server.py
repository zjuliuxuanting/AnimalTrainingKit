#!/usr/bin/env python3
"""Token Monitor — lightweight HTTP server for the dashboard."""

import http.server
import json
import os
import socketserver
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

TOKEN_DIR = os.environ.get(
    "TOKEN_DIR",
    str(Path.home()) + "/.claude-adapter/token_usage",
)
PORT = int(os.environ.get("TOKEN_PORT", "8100"))


class TokenHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence request logs

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.lstrip("/")

        if path == "" or path == "index.html":
            self.serve_file("index.html", "text/html")
            return

        # /api/summary — compact summary for the all.json fallback
        if path == "api/summary":
            self.serve_json(self.summary())
            return

        # /api/tokens — full token records
        if path == "api/tokens":
            self.serve_json(self.all_records())
            return

        # /YYYY-MM-DD.jsonl — individual day files
        m = re.match(r"^(\d{4}-\d{2}-\d{2})\.jsonl$", path)
        if m:
            self.serve_jsonl(m.group(1))
            return

        # /all.json — combined file
        if path == "all.json":
            self.serve_json(self.all_records())
            return

        self.send_error(404)

    def serve_file(self, name, mime):
        dashboard = os.path.dirname(os.path.abspath(__file__))
        fp = os.path.join(dashboard, name)
        try:
            with open(fp, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_error(404)

    def serve_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def serve_jsonl(self, date):
        fp = os.path.join(TOKEN_DIR, f"{date}.jsonl")
        try:
            with open(fp, "r") as f:
                lines = f.readlines()
            records = []
            for line in lines:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            self.serve_json(records)
        except FileNotFoundError:
            self.serve_json([])

    def all_records(self):
        records = []
        try:
            for fname in sorted(os.listdir(TOKEN_DIR)):
                if not fname.endswith(".jsonl"):
                    continue
                fp = os.path.join(TOKEN_DIR, fname)
                with open(fp, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                records.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
        except FileNotFoundError:
            pass
        return records

    def summary(self):
        records = self.all_records()
        today = records[-30:]  # last 30 records
        return {"count": len(records), "recent": today}


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    with ReusableTCPServer(("", PORT), TokenHandler) as httpd:
        print(f"Token Monitor listening on http://localhost:{PORT}")
        httpd.serve_forever()
