import os
import re
import shutil
import threading
from colorama import init, Style

init(autoreset=True)

RESET  = Style.RESET_ALL
R1     = "\033[38;2;210;210;210m"
R2     = "\033[38;2;175;175;175m"
R3     = "\033[38;2;140;140;140m"
R4     = "\033[38;2;105;105;105m"
R5     = "\033[38;2;75;75;75m"
R6     = "\033[38;2;45;45;45m"
ROW_COLORS = [R1, R2, R3, R4, R5, R6]

WHITE   = "\033[38;2;250;250;250m"
MUTED   = "\033[38;2;120;120;120m"
BORDER  = "\033[38;2;100;100;100m"
SUCCESS = "\033[38;2;100;220;100m"
WARNING = "\033[38;2;255;170;40m"
DANGER  = "\033[38;2;220;80;80m"
CYAN    = "\033[38;2;80;200;220m"

ANSI_RE    = re.compile(r'\033\[[0-9;]*m')
PRINT_LOCK = threading.Lock()

def get_term_width() -> int:
    try:
        return shutil.get_terminal_size((92, 24)).columns
    except Exception:
        return 92

def vlen(text: str) -> int:
    return len(ANSI_RE.sub('', text))

def center(text: str) -> str:
    w = get_term_width()
    m = max(0, (w - vlen(text)) // 2)
    return " " * m + text

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

class UI:
    W  = 80
    IW = 76   # inner width

    @classmethod
    def banner(cls):
        clear()
        print()
        figure = [
            "⠀⠀⠀⠀⣠⣤⣶⣶⣶⣤⣄⡀",
            "⠀⠀⣴⣾⣿⣿⣿⣿⣿⣧⡀⠈",
            "⠀⣼⣿⣿⣿⣿⣿⣿⣿⡿⠁⠀",
            "⢰⡿⣿⣿⣿⣿⣿⣿⣿⣿⠀⠀",
            "⠘⣽⡿⠿⠿⣿⣿⣿⣿⣿⣦⣤",
            "⠀⣟⠀⠀⠀⣸⣿⡏⠀⠀⠀⢹",
            "⠀⣿⣷⣶⣾⡿⠁⠙⣄⣀⣀⣠",
            "⠀⠙⠙⢿⡿⣷⣶⣤⣿⣿⡿⠿",
            "⠀⠀⠀⠺⡏⡏⡏⡏⡏⠉⠁⠀",
            "⠀⠀⠀⠀⠀⠀⠁⠁⠀⠀⠀⠀",
        ]
        art = [
            "  ██████╗ ███╗   ██╗██╗     ██╗███╗   ██╗███████╗",
            " ██╔═══██╗████╗  ██║██║     ██║████╗  ██║██╔════╝",
            " ██║   ██║██╔██╗ ██║██║     ██║██╔██╗ ██║█████╗  ",
            " ██║   ██║██║╚██╗██║██║     ██║██║╚██╗██║██╔══╝  ",
            " ╚██████╔╝██║ ╚████║███████╗██║██║ ╚████║███████╗",
            "  ╚═════╝ ╚═╝  ╚═══╝╚══════╝╚═╝╚═╝  ╚═══╝╚══════╝",
        ]
        sub_art = [
            "  ███████╗ ██████╗ ██████╗  ██████╗ ███████╗",
            "  ██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝",
            "  █████╗  ██║   ██║██████╔╝██║  ███╗█████╗  ",
            "  ██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝  ",
            "  ██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗",
            "  ╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝",
        ]
        fig_pad  = (len(figure) - len(art)) // 2
        art_full = [""] * fig_pad + art + [""] * (len(figure) - len(art) - fig_pad)
        sa_pad   = (len(figure) - len(sub_art)) // 2
        sa_full  = [""] * sa_pad + sub_art + [""] * (len(figure) - len(sub_art) - sa_pad)
        art_w    = max(vlen(l) for l in art)
        sa_w     = max(vlen(l) for l in sub_art)

        for i, fig in enumerate(figure):
            col  = ROW_COLORS[min(i, len(ROW_COLORS)-1)]
            al   = art_full[i]
            sal  = sa_full[i]
            line = (
                f"{col}{fig}{RESET}  "
                f"{col}{al:<{art_w}}{RESET}  "
                f"{col}{sal:<{sa_w}}{RESET}"
            )
            print(center(line))

        print()
        tag = f"{MUTED}[ 24/7 TOKEN ONLINE KEEPER ]{RESET}"
        print(center(f"{R4}► {RESET}{R2}BLACKFORGE  ONLINE FORGE{RESET}{R4} ◄{RESET}  {tag}"))
        print()

    @classmethod
    def top(cls, title: str = "") -> str:
        if title:
            lbl = f" [ {title} ] "
            v = vlen(lbl); l = (cls.IW - v) // 2; r = cls.IW - v - l
            return center(f"{BORDER}╔{'═'*l}{R2}{lbl}{BORDER}{'═'*r}╗{RESET}")
        return center(f"{BORDER}╔{'═'*cls.IW}╗{RESET}")

    @classmethod
    def bot(cls) -> str:
        return center(f"{BORDER}╚{'═'*cls.IW}╝{RESET}")

    @classmethod
    def div(cls, label: str = "") -> str:
        if label:
            lbl = f" {label} "
            v = vlen(lbl); l = (cls.IW - v) // 2; r = cls.IW - v - l
            return center(f"{BORDER}╠{'═'*l}{MUTED}{lbl}{BORDER}{'═'*r}╣{RESET}")
        return center(f"{BORDER}╠{'═'*cls.IW}╣{RESET}")

    @classmethod
    def row(cls, text: str = "") -> str:
        p = max(0, cls.IW - 4 - vlen(text))
        return center(f"{BORDER}║{RESET}  {text}{' '*p}  {BORDER}║{RESET}")

    @classmethod
    def log(cls, msg: str):
        with PRINT_LOCK:
            print(cls.row(msg))

    @classmethod
    def prompt(cls, label: str = "Choose") -> str:
        print(center(f"{BORDER}╭──────────[ {R2}{label}{RESET}{BORDER} ]──────────╮{RESET}"))
        return center(f"{BORDER}╰─────[ {R2}❯❯{RESET}{BORDER} ]{RESET} ")
