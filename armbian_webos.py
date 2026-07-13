#!/usr/bin/env python3
"""
Armbian WebOS Terminal — реальная ФС, OTA, apt, Desktop Environment, C/C++ compiler,
менеджер пакетов .pyos, алиасы команд.
Кроссплатформенная (Windows / Linux / macOS).
"""

import os
import sys
import shutil
import subprocess
import time
import ssl
import tempfile
import zipfile
import json
from datetime import datetime
from pathlib import Path

# ---------- надёжные HTTP-запросы ----------
try:
    import requests
except ImportError:
    print("Установите библиотеку requests: pip install requests")
    sys.exit(1)

# ---------- кросс‑платформенный readline ----------
try:
    import readline
except ImportError:
    try:
        import pyreadline3 as readline
    except ImportError:
        readline = None
        print("Предупреждение: история команд недоступна (установите pyreadline3 на Windows)")

VERSION = "1.7.0"
USER = "armbian"
HOSTNAME = "armbian-pc"

UPDATE_URL = "https://raw.githubusercontent.com/confing-sys/py_OS/main/armbian_webos.py"
VERSION_URL = "https://raw.githubusercontent.com/confing-sys/py_OS/main/version.txt"

# ─── Настройка песочницы (реальная файловая система) ─────────────
SANDBOX = os.path.join(os.path.expanduser("~"), "armbian_os")
os.makedirs(SANDBOX, exist_ok=True)
cwd_real = [SANDBOX]  # текущий путь внутри песочницы (список)

# ─── База данных установленных .pyos пакетов ─────────────────────
PACKAGES_DB = os.path.join(SANDBOX, "var", "lib", "pyos", "packages.json")

# ─── Алиасы (глобальный словарь) ─────────────────────────────────
aliases = {}

def load_aliases():
    """Загружает алиасы из ~/.bashrc внутри песочницы."""
    global aliases
    aliases = {}
    bashrc = os.path.join(SANDBOX, "home", "armbian", ".bashrc")
    if os.path.isfile(bashrc):
        with open(bashrc, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("alias "):
                    # формат: alias name='command' или alias name="command"
                    parts = line[6:].split("=", 1)
                    if len(parts) == 2:
                        name = parts[0].strip()
                        command = parts[1].strip().strip("'\"")
                        aliases[name] = command

def save_aliases():
    """Сохраняет алиасы в ~/.bashrc (перезаписывает строки алиасов)."""
    bashrc = os.path.join(SANDBOX, "home", "armbian", ".bashrc")
    lines = []
    if os.path.isfile(bashrc):
        with open(bashrc, "r", encoding="utf-8") as f:
            lines = f.readlines()
    # Удаляем старые alias строки
    new_lines = [line for line in lines if not line.strip().startswith("alias ")]
    # Добавляем текущие алиасы
    for name, cmd in aliases.items():
        new_lines.append(f"alias {name}='{cmd}'\n")
    with open(bashrc, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

def load_pkg_db():
    if os.path.exists(PACKAGES_DB):
        with open(PACKAGES_DB, 'r') as f:
            return json.load(f)
    return {}

def save_pkg_db(db):
    os.makedirs(os.path.dirname(PACKAGES_DB), exist_ok=True)
    with open(PACKAGES_DB, 'w') as f:
        json.dump(db, f, indent=2)

# ─── Вспомогательные функции для реальной ФС ─────────────────────
def get_real_path(path_list):
    return os.path.join(*path_list)

def real_path_to_virtual(abs_path):
    rel = os.path.relpath(abs_path, SANDBOX)
    if rel == ".":
        return "/"
    return "/" + rel.replace("\\", "/")

def virtual_path_to_real(virt_path):
    if virt_path == "/":
        return SANDBOX
    parts = virt_path.strip("/").split("/")
    return os.path.normpath(os.path.join(SANDBOX, *parts))

def get_cwd_real():
    return get_real_path(cwd_real)

def resolve_path(input_str):
    if not input_str.strip():
        return get_cwd_real()
    if input_str.startswith("/"):
        target = virtual_path_to_real(input_str)
    elif input_str.startswith("~"):
        home_real = os.path.join(SANDBOX, "home", "armbian")
        if input_str == "~":
            target = home_real
        else:
            rest = input_str[2:] if input_str.startswith("~/") else input_str[1:]
            target = os.path.normpath(os.path.join(home_real, rest.lstrip("/")))
    else:
        target = os.path.normpath(os.path.join(get_cwd_real(), input_str))
    # защита от выхода за пределы песочницы
    common = os.path.commonpath([os.path.abspath(target), os.path.abspath(SANDBOX)])
    if common != os.path.abspath(SANDBOX):
        target = SANDBOX
    return target

def prompt():
    cwd_virt = real_path_to_virtual(get_cwd_real())
    if cwd_virt.startswith("/home/armbian"):
        cwd_virt = "~" + cwd_virt[len("/home/armbian"):]
    elif cwd_virt == "/home/armbian":
        cwd_virt = "~"
    return f"{USER}@{HOSTNAME}:{cwd_virt}$ "

def change_dir(target_real):
    if os.path.isdir(target_real):
        cwd_real.clear()
        rel = os.path.relpath(target_real, SANDBOX)
        if rel == ".":
            cwd_real.append(SANDBOX)
        else:
            parts = rel.split(os.sep)
            new_path = [SANDBOX] + parts
            cwd_real.extend(new_path)
    else:
        print("cd: нет такого каталога")

# ─── Преобразование пути Windows → WSL (для компиляторов) ────────
def windows_to_wsl_path(win_path):
    abs_path = os.path.abspath(win_path)
    drive, tail = os.path.splitdrive(abs_path)
    if drive:
        drive_letter = drive[0].lower()
        wsl_path = f"/mnt/{drive_letter}/{tail.replace(os.sep, '/')}"
    else:
        wsl_path = abs_path.replace(os.sep, '/')
    return wsl_path

def prepare_compiler_args(args):
    wsl_args = []
    for arg in args:
        if (os.path.splitdrive(arg)[0] and os.path.isabs(arg)) or arg.startswith(SANDBOX):
            try:
                resolved = resolve_path(arg)
                wsl_args.append(windows_to_wsl_path(resolved))
            except:
                wsl_args.append(arg)
        else:
            wsl_args.append(arg)
    return wsl_args

def run_wsl_command(cmd_name, args):
    wsl = shutil.which("wsl")
    if not wsl:
        print(f"{cmd_name}: WSL не установлен.")
        return
    wsl_args = [cmd_name] + prepare_compiler_args(args)
    try:
        subprocess.run(["wsl"] + wsl_args, check=False)
    except Exception as e:
        print(f"{cmd_name}: ошибка выполнения через WSL: {e}")

# ─── Команды ─────────────────────────────────────────────────────
def cmd_help(args):
    print("Доступные команды Armbian WebOS (реальная ФС):")
    cmds = [
        "help", "man <cmd>", "ls [-la]", "cd", "pwd", "cat", "touch", "mkdir", "rm [-r]",
        "cp", "mv", "echo", "grep", "chmod", "whoami", "hostname", "date", "cal",
        "uname", "clear", "history", "nano", "exit", "shutdown",
        "─── Алиасы ───", "alias [имя='команда'] — создать/посмотреть алиасы",
        "─── Сеть ───", "ifconfig", "ping", "netstat", "nslookup", "wget", "curl",
        "─── Система ───", "top", "ps", "kill", "df", "free", "lsblk", "uptime", "dmesg",
        "─── Пакеты ───", "apt update/upgrade/install", "dpkg", "armbian-config",
        "─── Пакеты .pyos ───", "pkg install <файл.pyos>", "pkg remove <имя>", "pkg list",
        "─── Обработка ───", "head", "tail", "wc", "sort", "uniq", "diff", "tar", "gzip",
        "─── Сервисы ───", "systemctl", "journalctl", "timedatectl",
        "─── GUI ───", "de / desktop / startx — полноэкранный рабочий стол",
        "               mc — файловый менеджер", "calc — калькулятор",
        "─── Компиляторы ───", "gcc [файлы...] — C компилятор (через WSL)",
        "               g++ [файлы...] — C++ компилятор (через WSL)",
        "               make [цели] — сборка проектов (через WSL)",
        "               build <файл> — быстрая компиляция C",
        "─── Обновление ───", "ota-update — реальное OTA обновление"
    ]
    for c in cmds:
        print(f"  {c}")

def cmd_man(args):
    manuals = {
        "ls": "ls - список файлов и папок.",
        "nano": "nano - текстовый редактор.",
        "apt": "apt - менеджер пакетов (реальный через WSL).",
        "de": "de / desktop / startx - полноэкранный рабочий стол с меню.",
        "mc": "mc - двухпанельный файловый менеджер.",
        "gcc": "gcc - компилятор C (требуется WSL и установленный gcc)",
        "g++": "g++ - компилятор C++ (требуется WSL и установленный g++)",
        "make": "make - утилита сборки (требуется WSL и make)",
        "build": "build <файл> - скомпилировать один C-файл",
        "pkg": "pkg install|remove|list — менеджер пакетов .pyos",
        "alias": "alias [name='command'] — создать алиас, alias без аргументов — показать все",
        "ota-update": "ota-update - обновление скрипта.",
    }
    cmd = args[0] if args else ""
    print(manuals.get(cmd, f"Нет руководства для '{cmd}'."))

def cmd_ls(args):
    long_format = "-l" in args
    show_all = "-a" in args
    path_arg = next((a for a in args if not a.startswith("-")), None)
    target = resolve_path(path_arg) if path_arg else get_cwd_real()
    if not os.path.isdir(target):
        print("ls: нет такого каталога")
        return
    entries = os.listdir(target)
    if not show_all:
        entries = [e for e in entries if not e.startswith(".")]
    dirs, files = [], []
    for e in entries:
        full = os.path.join(target, e)
        if os.path.isdir(full): dirs.append(e)
        else: files.append(e)
    dirs.sort(); files.sort()
    sorted_entries = [(d, True) for d in dirs] + [(f, False) for f in files]
    if long_format:
        for name, is_dir in sorted_entries:
            full = os.path.join(target, name)
            if is_dir:
                print(f"drwxr-xr-x 1 {USER} {USER}          0 {name}")
            else:
                size = os.path.getsize(full)
                print(f"-rw-r--r-- 1 {USER} {USER} {size:>10} {name}")
    else:
        line = []
        for name, is_dir in sorted_entries:
            if is_dir:
                line.append(f"\033[94m{name}\033[0m" if os.name != 'nt' else name + "/")
            else:
                line.append(name)
        print("  ".join(line) if line else "")

def cmd_cd(args):
    if not args: target = os.path.join(SANDBOX, "home", "armbian")
    else: target = resolve_path(args[0])
    change_dir(target)

def cmd_pwd(args):
    print(real_path_to_virtual(get_cwd_real()))

def cmd_cat(args):
    if not args: print("cat: требуется имя файла"); return
    target = resolve_path(args[0])
    if not os.path.exists(target): print(f"cat: {args[0]}: нет такого файла")
    elif os.path.isdir(target): print(f"cat: {args[0]}: это каталог")
    else:
        try:
            with open(target, "r", encoding="utf-8") as f: print(f.read())
        except Exception as e: print(f"cat: ошибка чтения: {e}")

def cmd_touch(args):
    if not args: print("touch: требуется имя файла"); return
    target = resolve_path(args[0])
    parent = os.path.dirname(target)
    if not os.path.isdir(parent): print("touch: неверный путь"); return
    Path(target).touch()

def cmd_mkdir(args):
    if not args: print("mkdir: требуется имя каталога"); return
    target = resolve_path(args[0])
    try: os.makedirs(target, exist_ok=True)
    except Exception as e: print(f"mkdir: ошибка: {e}")

def cmd_rm(args):
    recursive = "-r" in args or "-rf" in args
    targets = [a for a in args if not a.startswith("-")]
    if not targets: print("rm: требуется имя файла/каталога"); return
    target = resolve_path(targets[0])
    if not os.path.exists(target): print(f"rm: '{targets[0]}' не найден"); return
    if os.path.isdir(target) and not recursive: print("rm: невозможно удалить каталог без -r"); return
    try:
        if os.path.isdir(target): shutil.rmtree(target)
        else: os.remove(target)
    except Exception as e: print(f"rm: ошибка: {e}")

def cmd_cp(args):
    if len(args) < 2: print("cp: требуется источник и цель"); return
    src, dst = resolve_path(args[0]), resolve_path(args[1])
    if not os.path.exists(src): print(f"cp: '{args[0]}' не найден"); return
    if os.path.isdir(src): print("cp: пропуск каталога (без -r)"); return
    try: shutil.copy2(src, dst)
    except Exception as e: print(f"cp: ошибка: {e}")

def cmd_mv(args):
    if len(args) < 2: print("mv: требуется источник и цель"); return
    src, dst = resolve_path(args[0]), resolve_path(args[1])
    if not os.path.exists(src): print(f"mv: '{args[0]}' не найден"); return
    try: shutil.move(src, dst)
    except Exception as e: print(f"mv: ошибка: {e}")

def cmd_echo(args):
    text = " ".join(args)
    if ">" in text:
        parts = text.split(">")
        content, file_path = parts[0].strip(), resolve_path(parts[1].strip())
        parent = os.path.dirname(file_path)
        if os.path.isdir(parent):
            try:
                with open(file_path, "w", encoding="utf-8") as f: f.write(content)
            except Exception as e: print(f"echo: ошибка записи: {e}")
        else: print("echo: ошибка записи")
    else: print(text)

def cmd_grep(args):
    if len(args) < 2: print("grep: требуется шаблон и файл"); return
    pattern, file_arg = args[0], args[1]
    target = resolve_path(file_arg)
    if not os.path.isfile(target): print(f"grep: {file_arg}: нет такого файла"); return
    try:
        with open(target, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if pattern in line: print(f"{i}:{line.rstrip()}")
    except Exception as e: print(f"grep: ошибка: {e}")

def cmd_chmod(args):
    if args: print(f"chmod: права '{args[0]}' установлены (симуляция)")

def cmd_whoami(args): print(USER)
def cmd_hostname(args): print(HOSTNAME)
def cmd_date(args): print(datetime.now().strftime("%a %b %d %H:%M:%S %Z %Y"))
def cmd_cal(args):
    from calendar import TextCalendar
    TextCalendar().prmonth(datetime.now().year, datetime.now().month)
def cmd_uname(args):
    if "-a" in args: print(f"Linux {HOSTNAME} 5.15.93-armbian #1 SMP Armbian 24.5.0 aarch64 GNU/Linux")
    else: print("Linux")
def cmd_clear(args): os.system('clear' if os.name != 'nt' else 'cls')
def cmd_history(args):
    if readline is None: print("История команд недоступна")
    else:
        for i in range(1, readline.get_current_history_length()+1):
            entry = readline.get_history_item(i)
            if entry: print(f"{i}  {entry}")

def cmd_nano(args):
    if not args: print("nano: укажите имя файла"); return
    target = resolve_path(args[0])
    if os.path.isdir(target): print(f"nano: {args[0]}: это каталог"); return
    content = ""
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as f: content = f.read()
        except: pass
    print(f"Редактирование: {real_path_to_virtual(target)}")
    print("Вводите строки (пустая строка + Enter завершает, Ctrl+C для выхода, ':q' выход без сохранения)")
    if content:
        for idx, line in enumerate(content.splitlines(), 1): print(f"{idx}: {line}")
    new_lines = []
    try:
        while True:
            try: line = input()
            except EOFError: break
            if line == "": break
            if line == ":q": print("Отмена сохранения"); return
            new_lines.append(line)
    except KeyboardInterrupt:
        print()
        if new_lines:
            ans = input("Сохранить изменения перед выходом? (y/N): ").strip().lower()
            if ans == 'y':
                try:
                    with open(target, "w", encoding="utf-8") as f: f.write("\n".join(new_lines))
                    print(f"Файл '{args[0]}' сохранён")
                except Exception as e: print(f"Ошибка сохранения: {e}")
            else: print("Изменения не сохранены.")
        else: print("Нет изменений для сохранения.")
        return
    new_content = "\n".join(new_lines)
    try:
        with open(target, "w", encoding="utf-8") as f: f.write(new_content)
        print(f"Файл '{args[0]}' сохранён")
    except Exception as e: print(f"Ошибка сохранения: {e}")

def cmd_exit(args): print("Выход из оболочки..."); sys.exit(0)
def cmd_shutdown(args): print("Система останавливается..."); sys.exit(0)

# ─── Сетевые команды (эмуляция) ──────────────────────────────────
def cmd_ifconfig(args):
    print("eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500")
    print("        inet 192.168.1.42  netmask 255.255.255.0  broadcast 192.168.1.255")
    print("lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536")
    print("        inet 127.0.0.1  netmask 255.0.0.0")
def cmd_ping(args):
    target = args[0] if args else "google.com"
    print(f"PING {target} 56(84) bytes of data.")
    for i in range(3): print(f"64 bytes from {target}: icmp_seq={i+1} ttl=118 time={15+5*i} ms")
    print(f"--- {target} ping statistics ---\n3 packets transmitted, 3 received, 0% packet loss")
def cmd_netstat(args):
    print("Active Internet connections (w/o servers)")
    print("Proto Recv-Q Send-Q Local Address           Foreign Address         State")
    print("tcp        0      0 192.168.1.42:22         10.0.0.5:54321         ESTABLISHED")
def cmd_nslookup(args):
    host = args[0] if args else "armbian.com"
    print(f"Server:         8.8.8.8\nAddress:        8.8.8.8#53\nName:   {host}\nAddress: 93.184.216.34")
def cmd_wget(args):
    if not args: print("wget: укажите URL"); return
    print(f"--{datetime.now().isoformat()}--  {args[0]}\nHTTP request sent, awaiting response... 200 OK")
    print("Length: 12345 (12K) [text/html]\nSaving to: ‘index.html’\n100%[===================>] 12.34K  --.-KB/s    in 0.01s")
def cmd_curl(args):
    if not args: print("curl: укажите URL"); return
    print("<html><body><h1>Armbian WebOS</h1></body></html>")

# ─── Системные команды (эмуляция) ────────────────────────────────
def cmd_top(args):
    print("top - 12:34:56 up 2:15,  1 user,  load average: 0.08, 0.03, 0.01")
    print("Tasks:  42 total,   1 running,  41 sleeping,   0 stopped,   0 zombie")
    print("%Cpu(s):  2.3 us,  1.0 sy,  0.0 ni, 96.7 id,  0.0 wa,  0.0 hi,  0.0 si")
    print("MiB Mem :    982.1 total,    234.5 free,    567.8 used,    179.8 buff/cache")
def cmd_ps(args): print("  PID TTY          TIME CMD\n    1 ?        00:00:02 systemd\n  345 ?        00:00:00 sshd\n 1234 pts/0    00:00:01 bash")
def cmd_kill(args):
    if not args: print("kill: требуется PID")
    else: print(f"Процесс {args[0]} завершён (симуляция)")
def cmd_df(args): print("Filesystem     1K-blocks    Used Available Use% Mounted on\n/dev/mmcblk0p1  30951488 4590840  26360648  15% /")
def cmd_free(args): print("              total        used        free      shared  buff/cache   available\nMem:         1005636      581244      239876       12344      184516      349120")
def cmd_lsblk(args): print("NAME        MAJ:MIN RM   SIZE RO TYPE MOUNTPOINT\nmmcblk0     179:0    0  29.7G  0 disk\n├─mmcblk0p1 179:1    0  29.5G  0 part /")
def cmd_uptime(args): print(" 12:34:56 up 2:15,  1 user,  load average: 0.08, 0.03, 0.01")
def cmd_dmesg(args): print("[    0.000000] Booting Linux on physical CPU 0x0\n[    0.000000] Linux version 5.15.93-armbian ...")

# ─── Пакетный менеджер (реальный через WSL) ──────────────────────
def cmd_apt(args):
    apt_path = shutil.which("apt")
    use_sudo = (os.name == 'posix' and os.geteuid() != 0)
    if os.name == 'posix' and apt_path:
        cmd = (["sudo"] if use_sudo else []) + ["apt"] + args
        subprocess.run(cmd, check=False)
        return
    if os.name == 'nt':
        wsl = shutil.which("wsl")
        if wsl:
            subprocess.run(["wsl", "sudo", "apt"] + args, check=False)
            return
        print("apt недоступен в Windows без WSL.")
        return
    print("apt: симуляция (реальный apt не обнаружен)")
def cmd_dpkg(args):
    if "-l" in args: print("ii  armbian-config  24.5.0  all  Armbian configuration utility")
    else: print("dpkg: используйте -l")
def cmd_armbian_config(args): print("Armbian-config (симуляция). Используйте ota-update.")

# ─── Обработка текста (реальные файлы) ───────────────────────────
def cmd_head(args):
    if not args: return
    target = resolve_path(args[0])
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                for line in f.readlines()[:10]: print(line.rstrip())
        except Exception as e: print(f"head: ошибка: {e}")
def cmd_tail(args):
    if not args: return
    target = resolve_path(args[0])
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                for line in f.readlines()[-10:]: print(line.rstrip())
        except Exception as e: print(f"tail: ошибка: {e}")
def cmd_wc(args):
    if not args: return
    target = resolve_path(args[0])
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                count = sum(1 for _ in f)
            print(f"{count} строк")
        except Exception as e: print(f"wc: ошибка: {e}")
def cmd_sort(args):
    if not args: return
    target = resolve_path(args[0])
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                lines = sorted(line.rstrip() for line in f)
            print("\n".join(lines))
        except Exception as e: print(f"sort: ошибка: {e}")
def cmd_uniq(args):
    if not args: return
    target = resolve_path(args[0])
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                seen = set()
                for line in f:
                    line = line.rstrip()
                    if line not in seen: print(line); seen.add(line)
        except Exception as e: print(f"uniq: ошибка: {e}")
def cmd_diff(args):
    if len(args) < 2: print("diff: требуется два файла"); return
    a, b = resolve_path(args[0]), resolve_path(args[1])
    if os.path.isfile(a) and os.path.isfile(b):
        import difflib
        with open(a, "r", encoding="utf-8") as fa, open(b, "r", encoding="utf-8") as fb:
            diff = difflib.unified_diff(fa.readlines(), fb.readlines(), fromfile=args[0], tofile=args[1])
            sys.stdout.writelines(diff)
    else: print("diff: оба аргумента должны быть файлами")
def cmd_tar(args): print("tar: симуляция архивации (создан архив.tar)")
def cmd_gzip(args): print("gzip: симуляция сжатия")

# ─── Сервисы (эмуляция) ─────────────────────────────────────────
def cmd_systemctl(args):
    if "status" in args: print("● armbian-ota.service - OTA Update Service")
    else: print("systemctl: status|start|stop")
def cmd_journalctl(args): print("-- Logs begin at Mon 2024-01-01 00:00:00 UTC. --")
def cmd_timedatectl(args): print(datetime.now().strftime("Local time: %a %Y-%m-%d %H:%M:%S %Z"))

# ─── Полноэкранный рабочий стол и файловый менеджер ─────────────
def cmd_de(args):
    if os.name != 'nt':
        print("\033[?1049h", end=""); sys.stdout.flush()
    else:
        os.system('mode con cols=100 lines=30')
    items = [
        ("📁 File Manager", "mc"), ("📝 Text Editor", "nano "),
        ("🧮 Calculator", "calc"), ("💻 Terminal", ""), ("⏻  Shutdown", "shutdown"),
    ]
    current = 0; running = True
    try:
        while running:
            if os.name != 'nt': sys.stdout.write("\033[2J\033[H")
            else: os.system('cls')
            width = 50
            print("\n"*4)
            print(" " * ((100 - width) // 2) + "╔" + "═" * (width - 2) + "╗")
            print(" " * ((100 - width) // 2) + "║" + " Armbian Desktop Environment".center(width - 2) + "║")
            print(" " * ((100 - width) // 2) + "╠" + "═" * (width - 2) + "╣")
            print(" " * ((100 - width) // 2) + "║" + " " * (width - 2) + "║")
            for i, (label, _) in enumerate(items):
                text = f" {label} "
                line = "\033[7m" + text.center(width - 2) + "\033[0m" if i == current else text.center(width - 2)
                print(" " * ((100 - width) // 2) + "║" + line + "║")
            print(" " * ((100 - width) // 2) + "║" + " " * (width - 2) + "║")
            print(" " * ((100 - width) // 2) + "╚" + "═" * (width - 2) + "╝")
            print("\n" + " " * ((100 - width) // 2) + "↑↓: выбор   Enter: запуск   Esc: выход")
            sys.stdout.flush()
            if os.name != 'nt':
                import tty, termios
                fd = sys.stdin.fileno(); old_settings = termios.tcgetattr(fd)
                try:
                    tty.setraw(fd)
                    key = sys.stdin.read(1)
                    if key == '\x1b':
                        seq = sys.stdin.read(2)
                        if seq == '[A': current = (current - 1) % len(items)
                        elif seq == '[B': current = (current + 1) % len(items)
                        else: running = False
                    elif key == '\r':
                        chosen_cmd = items[current][1]
                        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                        if chosen_cmd:
                            if os.name != 'nt': print("\033[?1049l", end=""); sys.stdout.flush()
                            if chosen_cmd == "shutdown": cmd_shutdown([])
                            elif chosen_cmd == "mc": cmd_mc([])
                            elif chosen_cmd == "nano ":
                                filename = input("Введите имя файла: "); cmd_nano([filename])
                            elif chosen_cmd == "calc": cmd_calc([])
                        running = False
                finally: termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            else:
                choice = input("Выберите номер (1-5) или q для выхода: ").strip().lower()
                if choice == 'q': running = False
                elif choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(items):
                        chosen_cmd = items[idx][1]
                        if chosen_cmd == "shutdown": cmd_shutdown([])
                        elif chosen_cmd == "mc": cmd_mc([])
                        elif chosen_cmd == "nano ":
                            filename = input("Введите имя файла: "); cmd_nano([filename])
                        elif chosen_cmd == "calc": cmd_calc([])
                        running = False
    finally:
        if os.name != 'nt': print("\033[?1049l", end=""); sys.stdout.flush()
        print("Рабочий стол закрыт.")

def cmd_mc(args):
    if os.name != 'nt': print("\033[?1049h", end=""); sys.stdout.flush()
    left_path = get_cwd_real(); right_path = get_cwd_real()
    def show_panels():
        if os.name != 'nt': sys.stdout.write("\033[2J\033[H")
        else: os.system('cls')
        print("="*100)
        print(f"{'Left':<48} │ {'Right':>48}")
        print("="*100)
        left_items = os.listdir(left_path) if os.path.isdir(left_path) else []
        right_items = os.listdir(right_path) if os.path.isdir(right_path) else []
        for i in range(max(len(left_items), len(right_items), 25)):
            left = left_items[i] if i < len(left_items) else ""
            right = right_items[i] if i < len(right_items) else ""
            print(f"{left:<48} │ {right:>48}")
        print("="*100)
        print("F5 Copy  F6 Move  F10/Quit  TAB switch panel  cd <dir>")
        print(f"Left:  {real_path_to_virtual(left_path)}")
        print(f"Right: {real_path_to_virtual(right_path)}")
        sys.stdout.flush()
    show_panels()
    active_panel = 'left'
    while True:
        cmd = input("mc> ").strip().lower()
        if cmd in ('q','quit','f10','exit'): break
        elif cmd == 'tab': active_panel = 'right' if active_panel == 'left' else 'left'
        elif cmd.startswith('cd '):
            _, new_dir = cmd.split(maxsplit=1)
            new = resolve_path(new_dir)
            if os.path.isdir(new):
                if active_panel == 'left': left_path = new
                else: right_path = new
        elif cmd in ('copy','f5'):
            src, dst = input("Source file: "), input("Destination: ")
            try: shutil.copy2(resolve_path(src), resolve_path(dst)); print("Copied.")
            except Exception as e: print(f"Error: {e}")
        elif cmd in ('move','f6'):
            src, dst = input("Source file: "), input("Destination: ")
            try: shutil.move(resolve_path(src), resolve_path(dst)); print("Moved.")
            except Exception as e: print(f"Error: {e}")
        else: print("Commands: cd, copy, move, quit, tab")
        show_panels()
    if os.name != 'nt': print("\033[?1049l", end=""); sys.stdout.flush()

def cmd_calc(args):
    print("Калькулятор (введите выражение, 'exit' для выхода)")
    while True:
        try:
            expr = input("calc> ")
            if expr.lower() in ('exit','quit','q'): break
            result = eval(expr)
            print(f"= {result}")
        except Exception as e: print(f"Ошибка: {e}")

# ─── Компиляторы C/C++ через WSL ─────────────────────────────────
def cmd_gcc(args):
    if not args: print("gcc: не указаны исходные файлы"); return
    run_wsl_command("gcc", args)

def cmd_gpp(args):
    if not args: print("g++: не указаны исходные файлы"); return
    run_wsl_command("g++", args)

def cmd_make_cmd(args):
    run_wsl_command("make", args)

def cmd_build(args):
    if not args: print("build: укажите исходный файл"); return
    src = args[0]
    out = os.path.splitext(os.path.basename(src))[0] + ".out"
    run_wsl_command("gcc", [src, "-o", out])

# ─── Менеджер пакетов .pyos ─────────────────────────────────────
def cmd_pkg_install(args):
    if not args:
        print("pkg install: укажите .pyos файл")
        return
    filename = args[0]
    if not os.path.exists(filename):
        print(f"Файл {filename} не найден")
        return
    try:
        with zipfile.ZipFile(filename, 'r') as zf:
            if 'meta.json' not in zf.namelist():
                print("Ошибка: отсутствует meta.json в пакете")
                return
            meta = json.loads(zf.read('meta.json').decode('utf-8'))
            pkg_name = meta.get('name')
            pkg_version = meta.get('version')
            if not pkg_name:
                print("Ошибка: не указано имя пакета")
                return
            db = load_pkg_db()
            if pkg_name in db:
                print(f"Пакет {pkg_name} уже установлен (версия {db[pkg_name].get('version', '?')}). Удалите сначала.")
                return
            files_map = meta.get('files', {})
            if not files_map:
                print("Пакет не содержит файлов")
                return
            conflicts = []
            for target_rel, src_name in files_map.items():
                target_abs = os.path.join(SANDBOX, target_rel.lstrip('/'))
                if os.path.exists(target_abs):
                    owner = None
                    for name, info in db.items():
                        if target_rel in info.get('files', []):
                            owner = name
                            break
                    if owner:
                        conflicts.append(f"{target_rel} (принадлежит {owner})")
                    else:
                        conflicts.append(f"{target_rel} (неотслеживаемый файл)")
            if conflicts:
                print("Обнаружены конфликты:")
                for c in conflicts:
                    print(f"  - {c}")
                ans = input("Продолжить установку? (y/N): ").strip().lower()
                if ans != 'y':
                    print("Установка отменена.")
                    return
            installed_files = []
            for target_rel, src_name in files_map.items():
                target_abs = os.path.join(SANDBOX, target_rel.lstrip('/'))
                os.makedirs(os.path.dirname(target_abs), exist_ok=True)
                with open(target_abs, 'wb') as out:
                    out.write(zf.read(src_name))
                installed_files.append(target_rel)
                print(f"  Установлен {target_rel}")
            db[pkg_name] = {
                'version': pkg_version,
                'files': installed_files,
                'description': meta.get('description', '')
            }
            save_pkg_db(db)
            print(f"Пакет {pkg_name} {pkg_version} успешно установлен.")
    except zipfile.BadZipFile:
        print("Ошибка: повреждённый архив")
    except Exception as e:
        print(f"Ошибка установки: {e}")

def cmd_pkg_remove(args):
    if not args:
        print("pkg remove: укажите имя пакета")
        return
    pkg_name = args[0]
    db = load_pkg_db()
    if pkg_name not in db:
        print(f"Пакет {pkg_name} не установлен")
        return
    info = db[pkg_name]
    files = info.get('files', [])
    for f_rel in files:
        f_abs = os.path.join(SANDBOX, f_rel.lstrip('/'))
        if os.path.isfile(f_abs):
            os.remove(f_abs)
            print(f"  Удалён {f_rel}")
    del db[pkg_name]
    save_pkg_db(db)
    print(f"Пакет {pkg_name} удалён.")

def cmd_pkg_list(args):
    db = load_pkg_db()
    if not db:
        print("Нет установленных пакетов.")
        return
    for name, info in db.items():
        print(f"{name} {info.get('version','?')} - {info.get('description','')}")

def cmd_pkg(args):
    if not args:
        print("pkg: install|remove|list")
        return
    sub = args[0]
    if sub == "install":
        cmd_pkg_install(args[1:])
    elif sub == "remove":
        cmd_pkg_remove(args[1:])
    elif sub == "list":
        cmd_pkg_list(args[1:])
    else:
        print(f"pkg: неизвестная подкоманда '{sub}'")

# ─── Алиасы ─────────────────────────────────────────────────────
def cmd_alias(args):
    """Управление алиасами: alias name='cmd', alias name, alias (без аргументов)."""
    if not args:
        # Показать все алиасы
        if not aliases:
            print("Нет заданных алиасов.")
        else:
            for name, cmd in aliases.items():
                print(f"alias {name}='{cmd}'")
        return
    # Может быть 'name=cmd' или просто 'name'
    first = args[0]
    if '=' in first:
        # задание алиаса
        try:
            name, cmd_part = first.split('=', 1)
            name = name.strip()
            cmd_part = cmd_part.strip().strip("'\"")
            aliases[name] = cmd_part
            save_aliases()
            print(f"Алиас '{name}' установлен: {cmd_part}")
        except:
            print("Ошибка синтаксиса. Используйте: alias name='команда'")
    else:
        # показать конкретный алиас
        if first in aliases:
            print(f"alias {first}='{aliases[first]}'")
        else:
            print(f"Алиас '{first}' не найден.")

# ─── OTA-обновление (улучшенное: requests + PowerShell) ─────────
def download_text(url, timeout=15):
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.text.strip()
    except Exception:
        if os.name == 'nt':
            try:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
                tmp.close()
                ps_cmd = f"powershell -Command \"[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '{url}' -OutFile '{tmp.name}' -UseBasicParsing\""
                subprocess.run(ps_cmd, shell=True, check=True)
                with open(tmp.name, 'r', encoding='utf-8') as f: data = f.read().strip()
                os.unlink(tmp.name)
                return data
            except: pass
    return None

def download_binary(url, timeout=30):
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    except Exception:
        if os.name == 'nt':
            try:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.py')
                tmp.close()
                ps_cmd = f"powershell -Command \"[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '{url}' -OutFile '{tmp.name}' -UseBasicParsing\""
                subprocess.run(ps_cmd, shell=True, check=True)
                with open(tmp.name, 'rb') as f: data = f.read()
                os.unlink(tmp.name)
                return data
            except: pass
    return None

def cmd_ota_update(args):
    print("══════════════════════════════════════")
    print("🔄 ЗАПУСК OTA ОБНОВЛЕНИЯ ARMBRIAN")
    print("══════════════════════════════════════")
    print("🔍 Проверка наличия обновлений...")
    latest_version = download_text(VERSION_URL, timeout=15)
    if latest_version is None:
        print("❌ Не удалось проверить обновление (ни через requests, ни через PowerShell).")
        return
    print(f"   Текущая версия: {VERSION}")
    print(f"   Доступная версия: {latest_version}")
    if latest_version == VERSION:
        print("✅ У вас уже установлена последняя версия.")
        return
    confirm = input("Установить обновление? (y/N): ").strip().lower()
    if confirm != 'y':
        print("Обновление отменено.")
        return
    print("📥 Загрузка обновления...")
    current_file = Path(__file__).resolve()
    backup_file = current_file.with_suffix(".py.bak")
    new_code = download_binary(UPDATE_URL, timeout=30)
    if new_code is None:
        print("❌ Не удалось загрузить обновление.")
        return
    shutil.copy2(current_file, backup_file)
    try:
        with open(current_file, "wb") as f: f.write(new_code)
        print("✅ Файл обновлён успешно.")
    except Exception as e:
        print(f"❌ Ошибка записи: {e}")
        shutil.copy2(backup_file, current_file)
        return
    print("🔄 Перезапуск приложения...")
    if os.name == 'nt':
        subprocess.Popen([sys.executable] + sys.argv)
        sys.exit(0)
    else:
        os.execv(sys.executable, [sys.executable] + sys.argv)

# ─── Словарь команд ───────────────────────────────────────────────
commands = {
    "help": cmd_help, "man": cmd_man, "ls": cmd_ls, "cd": cmd_cd, "pwd": cmd_pwd,
    "cat": cmd_cat, "touch": cmd_touch, "mkdir": cmd_mkdir, "rm": cmd_rm, "cp": cmd_cp,
    "mv": cmd_mv, "echo": cmd_echo, "grep": cmd_grep, "chmod": cmd_chmod,
    "whoami": cmd_whoami, "hostname": cmd_hostname, "date": cmd_date, "cal": cmd_cal,
    "uname": cmd_uname, "clear": cmd_clear, "history": cmd_history, "nano": cmd_nano,
    "exit": cmd_exit, "shutdown": cmd_shutdown,
    "ifconfig": cmd_ifconfig, "ping": cmd_ping, "netstat": cmd_netstat,
    "nslookup": cmd_nslookup, "wget": cmd_wget, "curl": cmd_curl,
    "top": cmd_top, "ps": cmd_ps, "kill": cmd_kill, "df": cmd_df, "free": cmd_free,
    "lsblk": cmd_lsblk, "uptime": cmd_uptime, "dmesg": cmd_dmesg,
    "apt": cmd_apt, "dpkg": cmd_dpkg, "armbian-config": cmd_armbian_config,
    "head": cmd_head, "tail": cmd_tail, "wc": cmd_wc, "sort": cmd_sort,
    "uniq": cmd_uniq, "diff": cmd_diff, "tar": cmd_tar, "gzip": cmd_gzip,
    "systemctl": cmd_systemctl, "journalctl": cmd_journalctl, "timedatectl": cmd_timedatectl,
    "de": cmd_de, "desktop": cmd_de, "startx": cmd_de, "mc": cmd_mc, "calc": cmd_calc,
    "gcc": cmd_gcc, "g++": cmd_gpp, "make": cmd_make_cmd, "build": cmd_build,
    "pkg": cmd_pkg, "alias": cmd_alias,
    "ota-update": cmd_ota_update,
}

# ─── Главный цикл (с поддержкой алиасов) ─────────────────────────
def main():
    for d in ["home/armbian", "etc", "tmp", "bin", "usr", "var"]:
        os.makedirs(os.path.join(SANDBOX, d), exist_ok=True)
    change_dir(os.path.join(SANDBOX, "home", "armbian"))

    # Загружаем алиасы из .bashrc
    load_aliases()

    if readline is not None:
        readline.set_history_length(1000)
        histfile = os.path.join(os.path.expanduser("~"), ".armbian_webos_history")
        try: readline.read_history_file(histfile)
        except FileNotFoundError: pass

    print("🛠️ Armbian 24.5.0 (ядро 5.15.93) — загрузка завершена.")
    print("Реальная файловая система в песочнице:", SANDBOX)
    print("Добро пожаловать! Введите help для списка команд.")
    print("Попробуйте: alias ll='ls -la', ll, de, ota-update, apt update\n")

    while True:
        try:
            line = input(prompt())
        except (EOFError, KeyboardInterrupt):
            print("\nИспользуйте 'exit' для выхода")
            continue
        if not line.strip(): continue
        parts = []
        current = ""
        in_quotes = False
        for ch in line:
            if ch == '"':
                in_quotes = not in_quotes
            elif ch == ' ' and not in_quotes:
                if current: parts.append(current); current = ""
            else: current += ch
        if current: parts.append(current)
        cmd = parts[0]
        args = parts[1:]

        # Проверяем алиас
        if cmd in aliases:
            alias_cmd = aliases[cmd]
            # Подставляем алиас вместо команды, аргументы передаются как есть
            # Для простоты: если алиас содержит пробелы, считаем что это полная команда, 
            # иначе просто заменяем имя команды
            if ' ' in alias_cmd:
                # Заменяем всю строку: алиас + оставшиеся аргументы
                new_parts = alias_cmd.split() + args
                cmd = new_parts[0]
                args = new_parts[1:]
            else:
                # Просто заменяем имя команды
                cmd = alias_cmd
                # args остаются те же
            # Теперь обрабатываем команду как обычно

        if cmd in commands:
            try: commands[cmd](args)
            except Exception as e: print(f"Ошибка выполнения команды: {e}")
        else:
            if os.name == 'nt':
                wsl = shutil.which("wsl")
                if wsl:
                    try: subprocess.run(["wsl"] + [cmd] + args, check=False)
                    except Exception as e: print(f"Не удалось запустить '{cmd}' через WSL: {e}")
                else: print(f"{cmd}: команда не найдена (WSL не установлен)")
            elif os.name == 'posix':
                try: subprocess.run([cmd] + args, check=False)
                except FileNotFoundError: print(f"{cmd}: команда не найдена")
                except Exception as e: print(f"Ошибка выполнения '{cmd}': {e}")
            else: print(f"{cmd}: команда не найдена")

    if readline is not None:
        try: readline.write_history_file(histfile)
        except: pass

if __name__ == "__main__":
    main()
