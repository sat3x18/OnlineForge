# keeper.py | Python 3.10+ | OnlineForge — Discord 24/7 Token Online Keeper
# deps: websocket-client, requests, colorama
#
# Discord Gateway flow per token:
#   1. GET /gateway/bot → wss URL
#   2. Connect WSS
#   3. Receive OP10 Hello → start heartbeat thread at hello.heartbeat_interval
#   4. Send OP2 Identify with token + presence {status: "online", activities: []}
#   5. Heartbeat loop: send OP1 every interval ms, expect OP11 ACK
#   6. On OP7 Reconnect or socket close → reconnect with exponential backoff
#   7. On OP9 Invalid Session → re-identify after 1-5s
#
# Token stays "online" as long as the gateway connection lives and heartbeats land.

import json
import random
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import requests
import websocket   # websocket-client

from ui import (
    UI, RESET, R1, R2, R3, R4, R5, BORDER,
    WHITE, MUTED, SUCCESS, WARNING, DANGER, CYAN,
    PRINT_LOCK, center, clear
)

# ── Constants ──────────────────────────────────────────────────────────────────

GATEWAY_VERSION = 10
GATEWAY_INTENTS = 0          # user token — no intents needed for presence
USER_AGENT      = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
BASE_BACKOFF    = 2.0        # seconds, doubles each reconnect attempt
MAX_BACKOFF     = 120.0

# OP codes
OP_DISPATCH      = 0
OP_HEARTBEAT     = 1
OP_IDENTIFY      = 2
OP_RESUME        = 6
OP_RECONNECT     = 7
OP_INVALID_SES   = 9
OP_HELLO         = 10
OP_HEARTBEAT_ACK = 11

# Status strings
ST_CONNECTING   = "CONNECTING"
ST_ONLINE       = "ONLINE ●"
ST_RECONNECTING = "RECONNECTING"
ST_INVALID      = "INVALID TOKEN"
ST_ERROR        = "ERROR"
ST_STOPPED      = "STOPPED"


# ── TokenWorker ────────────────────────────────────────────────────────────────

@dataclass
class TokenWorker:
    """One persistent gateway connection per Discord token."""
    raw_token: str
    idx:       int

    # live fields — read by dashboard
    username:  str  = "unknown"
    status:    str  = ST_CONNECTING
    uptime:    float = 0.0         # seconds connected
    hb_sent:   int  = 0
    hb_ack:    int  = 0
    reconnects: int = 0
    _connected_at: float = field(default=0.0, repr=False)
    _session_id:   str   = field(default="",  repr=False)
    _seq:          int   = field(default=0,   repr=False)
    _stop_flag:    bool  = field(default=False, repr=False)
    _ws:           Optional[websocket.WebSocketApp] = field(default=None, repr=False)
    _hb_thread:    Optional[threading.Thread]       = field(default=None, repr=False)
    _hb_interval:  float = field(default=41.25, repr=False)
    _hb_ack_ok:    bool  = field(default=True,  repr=False)
    _lock:         threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _identify(self):
        payload = {
            "op": OP_IDENTIFY,
            "d": {
                "token": self.raw_token,
                "properties": {
                    "os":      "Windows",
                    "browser": "Chrome",
                    "device":  "",
                },
                "presence": {
                    "status":     "online",
                    "since":      0,
                    "activities": [],
                    "afk":        False,
                },
                "compress": False,
                "intents":  GATEWAY_INTENTS,
            }
        }
        self._ws.send(json.dumps(payload))

    def _heartbeat_loop(self):
        """Fires OP1 every hb_interval ms. Detects zombie connections via ACK miss."""
        while not self._stop_flag:
            time.sleep(self._hb_interval)
            if self._stop_flag:
                break
            if not self._hb_ack_ok:
                # Missed ACK — zombie connection, force reconnect
                _log(self.idx, self.username, f"{WARNING}HB ACK missed — forcing reconnect{RESET}", "warn")
                try:
                    self._ws.close()
                except Exception:
                    pass
                break
            self._hb_ack_ok = False
            try:
                self._ws.send(json.dumps({"op": OP_HEARTBEAT, "d": self._seq or None}))
                self.hb_sent += 1
            except Exception:
                break

    def _on_message(self, ws, raw):
        try:
            msg = json.loads(raw)
        except Exception:
            return

        op  = msg.get("op")
        data = msg.get("d") or {}
        seq  = msg.get("s")
        if seq:
            self._seq = seq

        if op == OP_HELLO:
            self._hb_interval = data.get("heartbeat_interval", 41250) / 1000.0
            # Jitter first heartbeat per Discord spec
            time.sleep(random.uniform(0, self._hb_interval))
            self._hb_ack_ok = True
            ws.send(json.dumps({"op": OP_HEARTBEAT, "d": self._seq or None}))
            self.hb_sent += 1
            # Start persistent heartbeat thread
            self._hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
            self._hb_thread.start()
            self._identify()

        elif op == OP_DISPATCH:
            event = msg.get("t")
            if event == "READY":
                self._session_id  = data.get("session_id", "")
                user              = data.get("user", {})
                self.username     = f"{user.get('username','?')}#{user.get('discriminator','0')}"
                self.status       = ST_ONLINE
                self._connected_at = time.time()
                _log(self.idx, self.username, f"{SUCCESS}READY — online{RESET}", "ok")
            elif event == "RESUMED":
                self.status = ST_ONLINE
                _log(self.idx, self.username, f"{SUCCESS}RESUMED{RESET}", "ok")

        elif op == OP_HEARTBEAT_ACK:
            self._hb_ack_ok = True
            self.hb_ack += 1
            if self._connected_at:
                self.uptime = time.time() - self._connected_at

        elif op == OP_RECONNECT:
            _log(self.idx, self.username, f"{WARNING}OP7 RECONNECT received{RESET}", "warn")
            ws.close()

        elif op == OP_INVALID_SES:
            resumable = bool(data)
            _log(self.idx, self.username, f"{DANGER}OP9 INVALID SESSION (resumable={resumable}){RESET}", "warn")
            time.sleep(random.uniform(1, 5))
            if resumable and self._session_id:
                self._resume(ws)
            else:
                self._identify()

    def _resume(self, ws):
        ws.send(json.dumps({
            "op": OP_RESUME,
            "d":  {
                "token":      self.raw_token,
                "session_id": self._session_id,
                "seq":        self._seq,
            }
        }))

    def _on_error(self, ws, err):
        _log(self.idx, self.username, f"{DANGER}WS error: {str(err)[:60]}{RESET}", "warn")

    def _on_close(self, ws, code, reason):
        if not self._stop_flag:
            self.status = ST_RECONNECTING
            _log(self.idx, self.username,
                 f"{WARNING}Closed (code={code}) — will reconnect{RESET}", "warn")

    def _on_open(self, ws):
        self.status = ST_CONNECTING
        _log(self.idx, self.username, f"{MUTED}Gateway connected — awaiting HELLO{RESET}", "info")

    def _get_gateway_url(self) -> str:
        try:
            r = requests.get(
                "https://discord.com/api/v10/gateway",
                headers={"User-Agent": USER_AGENT},
                timeout=8,
            )
            url = r.json().get("url", "wss://gateway.discord.gg")
            return f"{url}/?v={GATEWAY_VERSION}&encoding=json"
        except Exception:
            return f"wss://gateway.discord.gg/?v={GATEWAY_VERSION}&encoding=json"

    def run(self):
        """Main loop — runs forever until stop() is called. Handles reconnects."""
        backoff = BASE_BACKOFF
        while not self._stop_flag:
            url = self._get_gateway_url()
            self._hb_ack_ok = True

            self._ws = websocket.WebSocketApp(
                url,
                header={"User-Agent": USER_AGENT},
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )

            # run_forever blocks until socket closes
            self._ws.run_forever(ping_interval=0)

            if self._stop_flag:
                break

            if self.status == ST_INVALID:
                break   # don't retry invalid tokens

            self.reconnects += 1
            _log(self.idx, self.username,
                 f"{WARNING}Reconnect #{self.reconnects} in {backoff:.0f}s{RESET}", "warn")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)

        self.status = ST_STOPPED

    def stop(self):
        self._stop_flag = True
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass


# ── Shared log ring-buffer (last 22 lines) ───────────────────────────────────

_LOG_BUFFER: list[str] = []
_LOG_LOCK   = threading.Lock()
_LOG_MAX    = 22

def _log(idx: int, username: str, msg: str, level: str = "info"):
    ts  = time.strftime("%H:%M:%S")
    tag = f"{MUTED}[{ts}]{RESET} {R4}#{idx:>2}{RESET} {R2}{username[:18]:<18}{RESET}"
    line = f"{tag}  {msg}"
    with _LOG_LOCK:
        _LOG_BUFFER.append(line)
        if len(_LOG_BUFFER) > _LOG_MAX:
            _LOG_BUFFER.pop(0)


# ── Dashboard renderer ────────────────────────────────────────────────────────

def _uptime_str(sec: float) -> str:
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}h {m:02d}m {s:02d}s"

def _status_col(s: str) -> str:
    if "ONLINE" in s:   return f"{SUCCESS}{s}{RESET}"
    if "RECONNECT" in s: return f"{WARNING}{s}{RESET}"
    if "INVALID" in s:  return f"{DANGER}{s}{RESET}"
    return f"{MUTED}{s}{RESET}"

def _render_dashboard(workers: list[TokenWorker]):
    UI.banner()

    online = sum(1 for w in workers if "ONLINE" in w.status)
    recon  = sum(1 for w in workers if "RECONNECT" in w.status)
    inv    = sum(1 for w in workers if w.status == ST_INVALID)
    total  = len(workers)

    print(UI.top("Status Overview"))
    print(UI.row())
    print(UI.row(
        f"{R1}Tokens {BORDER}│{RESET}  "
        f"{SUCCESS}● {online} online{RESET}   "
        f"{WARNING}↺ {recon} reconnecting{RESET}   "
        f"{DANGER}✗ {inv} invalid{RESET}   "
        f"{MUTED}total: {total}{RESET}"
    ))
    print(UI.row())
    print(UI.div("Token Workers"))
    print(UI.row())

    # Table header
    hdr = (
        f"{MUTED}{'#':>2}  {'Username':<20}  {'Status':<16}  "
        f"{'Uptime':<14}  {'HB':>4}  {'Recon':>5}{RESET}"
    )
    print(UI.row(hdr))
    print(UI.row(f"{BORDER}{'─'*70}{RESET}"))

    for w in workers:
        num_col = f"{R4}{w.idx:>2}{RESET}"
        usr_col = f"{R2}{w.username[:20]:<20}{RESET}"
        sts_col = f"{_status_col(w.status):<16}"
        upt_col = f"{CYAN}{_uptime_str(w.uptime):<14}{RESET}"
        hb_col  = f"{MUTED}{w.hb_ack:>4}{RESET}"
        rc_col  = f"{WARNING if w.reconnects else MUTED}{w.reconnects:>5}{RESET}"
        print(UI.row(f"{num_col}  {usr_col}  {sts_col}  {upt_col}  {hb_col}  {rc_col}"))

    print(UI.row())
    print(UI.div("Live Log"))
    print(UI.row())

    with _LOG_LOCK:
        log_lines = list(_LOG_BUFFER)

    # Pad to full height so box doesn't collapse
    while len(log_lines) < 8:
        log_lines.append("")

    for line in log_lines[-8:]:
        print(UI.row(line))

    print(UI.row())
    print(UI.bot())
    print()
    print(center(f"{MUTED}  [Q] Quit   [R] Reload tokens.txt   running 24/7 — {time.strftime('%H:%M:%S')}{RESET}"))


# ── Token loader ──────────────────────────────────────────────────────────────

def _load_tokens(path: str) -> list[str]:
    """
    Load tokens from two sources, merged:
    1. DISCORD_TOKENS env var — comma-separated. Set this on Railway/VPS/Render.
       Example: DISCORD_TOKENS=tok1,tok2,tok3
    2. tokens.txt file — one per line (fallback / local use).
    Env var wins if set. Both can be active at once.
    """
    import os
    results: list[str] = []

    env = os.environ.get("DISCORD_TOKENS", "").strip()
    if env:
        for t in env.split(","):
            t = t.strip()
            if t:
                results.append(t)

    try:
        with open(path, "r", encoding="utf-8") as f:
            for l in f:
                l = l.strip()
                if l and not l.startswith("#"):
                    results.append(l)
    except FileNotFoundError:
        pass

    return results


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    TOKEN_FILE = "tokens.txt"

    UI.banner()
    print(UI.top("OnlineForge — 24/7 Token Online Keeper"))
    print(UI.row())
    print(UI.row(f"{R2}Put Discord tokens in tokens.txt (one per line) then start.{RESET}"))
    print(UI.row(f"{MUTED}Format: raw token, one per line. Email:pass:user:token format also supported.{RESET}"))
    print(UI.row())
    print(UI.bot())
    print()

    # Parse tokens — support raw token OR email:pass:user:token format
    raw_tokens = _load_tokens(TOKEN_FILE)
    tokens: list[str] = []
    for raw in raw_tokens:
        parts = raw.split(":")
        if len(parts) >= 4:
            tokens.append(parts[-1].strip())   # last field = token
        else:
            tokens.append(raw.strip())

    if not tokens:
        print(center(f"{DANGER}No tokens found in {TOKEN_FILE}. Add tokens and restart.{RESET}\n"))
        input(center(f"{MUTED}Press Enter to exit...{RESET}"))
        sys.exit(0)

    print(center(f"{SUCCESS}Loaded {len(tokens)} token(s) from {TOKEN_FILE}{RESET}"))
    print(center(f"{MUTED}Starting gateway connections...{RESET}\n"))
    time.sleep(1)

    # Spawn one worker per token
    workers: list[TokenWorker] = []
    for i, tok in enumerate(tokens, start=1):
        w = TokenWorker(raw_token=tok, idx=i)
        workers.append(w)
        t = threading.Thread(target=w.run, daemon=True, name=f"worker-{i}")
        t.start()
        # Stagger connections — 500ms apart so Discord doesn't rate-limit
        time.sleep(0.5)

    # ── Dashboard refresh loop ────────────────────────────────────────────────
    import sys as _sys
    import select

    def _kbhit() -> bool:
        """Non-blocking keypress check (Windows + Unix)."""
        try:
            import msvcrt
            return msvcrt.kbhit()
        except ImportError:
            return bool(select.select([_sys.stdin], [], [], 0)[0])

    def _getch() -> str:
        try:
            import msvcrt
            return msvcrt.getwch()
        except ImportError:
            return _sys.stdin.read(1)

    try:
        while True:
            _render_dashboard(workers)
            # Refresh every 2s, but check for keypress
            for _ in range(20):
                time.sleep(0.1)
                if _kbhit():
                    ch = _getch().lower()
                    if ch == "q":
                        raise KeyboardInterrupt
                    elif ch == "r":
                        # Hot-reload tokens.txt — add new workers for new tokens
                        new_raw = _load_tokens(TOKEN_FILE)
                        new_toks = []
                        for raw in new_raw:
                            parts = raw.split(":")
                            new_toks.append(parts[-1].strip() if len(parts) >= 4 else raw.strip())
                        existing = {w.raw_token for w in workers}
                        added = 0
                        for tok in new_toks:
                            if tok not in existing:
                                i = len(workers) + 1
                                w = TokenWorker(raw_token=tok, idx=i)
                                workers.append(w)
                                threading.Thread(target=w.run, daemon=True, name=f"worker-{i}").start()
                                existing.add(tok)
                                added += 1
                                time.sleep(0.3)
                        if added:
                            _log(0, "system", f"{SUCCESS}Hot-reload: +{added} token(s){RESET}", "ok")
    except KeyboardInterrupt:
        print()
        print(center(f"{WARNING}Stopping all workers...{RESET}"))
        for w in workers:
            w.stop()
        time.sleep(1)
        print(center(f"{MUTED}All connections closed. Goodbye.{RESET}\n"))
        sys.exit(0)


if __name__ == "__main__":
    main()
