#!/usr/bin/env python3
"""
Armbian WebOS Terminal — реальная ФС (песочница), OTA, apt, Desktop Environment.
Кроссплатформенная (Windows / Linux / macOS).
"""

import os
import sys
import shutil
import subprocess
import time
import ssl
from datetime import datetime
from pathlib import Path

# ---------- библиотека для надёжных HTTP-запросов ----------
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

VERSION = "1.2.0"
USER = "armbian"
HOSTNAME = "armbian-pc"

UPDATE_URL = "https://raw.githubusercontent.com/confing-sys/py_OS/main/armbian_webos.py"
VERSION_URL = "https://raw.githubusercontent.com/confing-sys/py_OS/main/version.txt"

# ─── Настройка песочницы (реальная файловая система) ─────────────
SANDBOX = os.path.join(os.path.expanduser("~"), "armbian_os")
os.makedirs(SANDBOX, exist_ok=True)
cwd_real = [SANDBOX]  # текущий путь внутри песочницы (список)

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

# ─── Команды ─────────────────────────────────────────────────────
def cmd_help(args):
    print("Доступные команды Armbian WebOS (реальная ФС):")
    cmds = [
        "help", "man <cmd>", "ls [-la]", "cd", "pwd", "cat", "touch", "mkdir", "rm [-r]",
        "cp", "mv", "echo", "grep", "chmod", "whoami", "hostname", "date", "cal",
        "uname", "clear", "history", "nano", "exit", "shutdown",
        "─── Сеть ───", "ifconfig", "ping", "netstat", "nslookup", "wget", "curl",
        "─── Система ───", "top", "ps", "kill", "df", "free", "lsblk", "uptime", "dmesg",
        "─── Пакеты ───", "apt update/upgrade/install", "dpkg", "armbian-config",
        "─── Обработка ───", "head", "tail", "wc", "sort", "uniq", "diff", "tar", "gzip",
        "─── Сервисы ───", "systemctl", "journalctl", "timedatectl",
        "─── GUI ───", "de / desktop / startx — текстовый рабочий стол",
        "               mc — файловый менеджер", "calc — калькулятор",
        "─── Обновление ───", "ota-update — реальное OTA обновление"
    ]
    for c in cmds:
        print(f"  {c}")

def cmd_man(args):
    manuals = {
        "ls": "ls - список файлов и папок.",
        "nano": "nano - текстовый редактор.",
        "apt": "apt - менеджер пакетов (реальный через WSL).",
        "de": "de / desktop / startx - текстовый рабочий стол с меню.",
        "mc": "mc - двухпанельный файловый менеджер.",
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
    dirs = []
    files = []
    for e in entries:
        full = os.path.join(target, e)
        if os.path.isdir(full):
            dirs.append(e)
        else:
            files.append(e)
    dirs.sort()
    files.sort()
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
    if not args:
        target = os.path.join(SANDBOX, "home", "armbian")
    else:
        target = resolve_path(args[0])
    change_dir(target)

def cmd_pwd(args):
    print(real_path_to_virtual(get_cwd_real()))

def cmd_cat(args):
    if not args:
        print("cat: требуется имя файла")
        return
    target = resolve_path(args[0])
    if not os.path.exists(target):
        print(f"cat: {args[0]}: нет такого файла")
    elif os.path.isdir(target):
        print(f"cat: {args[0]}: это каталог")
    else:
        try:
            with open(target, "r", encoding="utf-8") as f:
                print(f.read())
        except Exception as e:
            print(f"cat: ошибка чтения: {e}")

def cmd_touch(args):
    if not args:
        print("touch: требуется имя файла")
        return
    target = resolve_path(args[0])
    parent = os.path.dirname(target)
    if not os.path.isdir(parent):
        print("touch: неверный путь")
        return
    Path(target).touch()

def cmd_mkdir(args):
    if not args:
        print("mkdir: требуется имя каталога")
        return
    target = resolve_path(args[0])
    try:
        os.makedirs(target, exist_ok=True)
    except Exception as e:
        print(f"mkdir: ошибка: {e}")

def cmd_rm(args):
    recursive = "-r" in args or "-rf" in args
    targets = [a for a in args if not a.startswith("-")]
    if not targets:
        print("rm: требуется имя файла/каталога")
        return
    target = resolve_path(targets[0])
    if not os.path.exists(target):
        print(f"rm: '{targets[0]}' не найден")
        return
    if os.path.isdir(target) and not recursive:
        print("rm: невозможно удалить каталог без -r")
        return
    try:
        if os.path.isdir(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
    except Exception as e:
        print(f"rm: ошибка: {e}")

def cmd_cp(args):
    if len(args) < 2:
        print("cp: требуется источник и цель")
        return
    src = resolve_path(args[0])
    dst = resolve_path(args[1])
    if not os.path.exists(src):
        print(f"cp: '{args[0]}' не найден")
        return
    if os.path.isdir(src):
        print("cp: пропуск каталога (без -r)")
        return
    try:
        shutil.copy2(src, dst)
    except Exception as e:
        print(f"cp: ошибка: {e}")

def cmd_mv(args):
    if len(args) < 2:
        print("mv: требуется источник и цель")
        return
    src = resolve_path(args[0])
    dst = resolve_path(args[1])
    if not os.path.exists(src):
        print(f"mv: '{args[0]}' не найден")
        return
    try:
        shutil.move(src, dst)
    except Exception as e:
        print(f"mv: ошибка: {e}")

def cmd_echo(args):
    text = " ".join(args)
    if ">" in text:
        parts = text.split(">")
        content = parts[0].strip()
        file_path = resolve_path(parts[1].strip())
        parent = os.path.dirname(file_path)
        if os.path.isdir(parent):
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                print(f"echo: ошибка записи: {e}")
        else:
            print("echo: ошибка записи")
    else:
        print(text)

def cmd_grep(args):
    if len(args) < 2:
        print("grep: требуется шаблон и файл")
        return
    pattern, file_arg = args[0], args[1]
    target = resolve_path(file_arg)
    if not os.path.isfile(target):
        print(f"grep: {file_arg}: нет такого файла")
        return
    try:
        with open(target, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if pattern in line:
                    print(f"{i}:{line.rstrip()}")
    except Exception as e:
        print(f"grep: ошибка: {e}")

def cmd_chmod(args):
    if args:
        print(f"chmod: права '{args[0]}' установлены (симуляция)")

def cmd_whoami(args):
    print(USER)

def cmd_hostname(args):
    print(HOSTNAME)

def cmd_date(args):
    print(datetime.now().strftime("%a %b %d %H:%M:%S %Z %Y"))

def cmd_cal(args):
    from calendar import TextCalendar
    now = datetime.now()
    TextCalendar().prmonth(now.year, now.month)

def cmd_uname(args):
    if "-a" in args:
        print(f"Linux {HOSTNAME} 5.15.93-armbian #1 SMP Armbian 24.5.0 aarch64 GNU/Linux")
    else:
        print("Linux")

def cmd_clear(args):
    os.system('clear' if os.name != 'nt' else 'cls')

def cmd_history(args):
    if readline is None:
        print("История команд недоступна (нет readline)")
        return
    for i in range(1, readline.get_current_history_length() + 1):
        entry = readline.get_history_item(i)
        if entry:
            print(f"{i}  {entry}")

def cmd_nano(args):
    if not args:
        print("nano: укажите имя файла")
        return
    target = resolve_path(args[0])
    if os.path.isdir(target):
        print(f"nano: {args[0]}: это каталог")
        return
    content = ""
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                content = f.read()
        except:
            pass
    print(f"Редактирование: {real_path_to_virtual(target)}")
    print("Вводите строки (пустая строка + Enter завершает, Ctrl+C для выхода, ':q' выход без сохранения)")
    if content:
        for idx, line in enumerate(content.splitlines(), 1):
            print(f"{idx}: {line}")
    new_lines = []
    try:
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line == "":
                break
            if line == ":q":
                print("Отмена сохранения")
                return
            new_lines.append(line)
    except KeyboardInterrupt:
        print()
        if new_lines:
            ans = input("Сохранить изменения перед выходом? (y/N): ").strip().lower()
            if ans == 'y':
                try:
                    with open(target, "w", encoding="utf-8") as f:
                        f.write("\n".join(new_lines))
                    print(f"Файл '{args[0]}' сохранён")
                except Exception as e:
                    print(f"Ошибка сохранения: {e}")
            else:
                print("Изменения не сохранены.")
        else:
            print("Нет изменений для сохранения.")
        return

    new_content = "\n".join(new_lines)
    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Файл '{args[0]}' сохранён")
    except Exception as e:
        print(f"Ошибка сохранения: {e}")

def cmd_exit(args):
    print("Выход из оболочки...")
    sys.exit(0)

def cmd_shutdown(args):
    print("Система останавливается...")
    sys.exit(0)

# ─── Сетевые команды (эмуляция) ──────────────────────────────────
def cmd_ifconfig(args):
    print("eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500")
    print("        inet 192.168.1.42  netmask 255.255.255.0  broadcast 192.168.1.255")
    print("lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536")
    print("        inet 127.0.0.1  netmask 255.0.0.0")

def cmd_ping(args):
    target = args[0] if args else "google.com"
    print(f"PING {target} 56(84) bytes of data.")
    for i in range(3):
        print(f"64 bytes from {target}: icmp_seq={i+1} ttl=118 time={15+5*i} ms")
    print(f"--- {target} ping statistics ---")
    print("3 packets transmitted, 3 received, 0% packet loss")

def cmd_netstat(args):
    print("Active Internet connections (w/o servers)")
    print("Proto Recv-Q Send-Q Local Address           Foreign Address         State")
    print("tcp        0      0 192.168.1.42:22         10.0.0.5:54321         ESTABLISHED")

def cmd_nslookup(args):
    host = args[0] if args else "armbian.com"
    print(f"Server:         8.8.8.8")
    print(f"Address:        8.8.8.8#53")
    print(f"Name:   {host}")
    print(f"Address: 93.184.216.34")

def cmd_wget(args):
    if not args:
        print("wget: укажите URL")
        return
    print(f"--{datetime.now().isoformat()}--  {args[0]}")
    print("HTTP request sent, awaiting response... 200 OK")
    print("Length: 12345 (12K) [text/html]")
    print("Saving to: ‘index.html’")
    print("100%[===================>] 12.34K  --.-KB/s    in 0.01s")

def cmd_curl(args):
    if not args:
        print("curl: укажите URL")
        return
    print("<html><body><h1>Armbian WebOS</h1></body></html>")

# ─── Системные команды (эмуляция) ────────────────────────────────
def cmd_top(args):
    print("top - 12:34:56 up 2:15,  1 user,  load average: 0.08, 0.03, 0.01")
    print("Tasks:  42 total,   1 running,  41 sleeping,   0 stopped,   0 zombie")
    print("%Cpu(s):  2.3 us,  1.0 sy,  0.0 ni, 96.7 id,  0.0 wa,  0.0 hi,  0.0 si")
    print("MiB Mem :    982.1 total,    234.5 free,    567.8 used,    179.8 buff/cache")

def cmd_ps(args):
    print("  PID TTY          TIME CMD")
    print("    1 ?        00:00:02 systemd")
    print("  345 ?        00:00:00 sshd")
    print(" 1234 pts/0    00:00:01 bash")

def cmd_kill(args):
    if not args:
        print("kill: требуется PID")
    else:
        print(f"Процесс {args[0]} завершён (симуляция)")

def cmd_df(args):
    print("Filesystem     1K-blocks    Used Available Use% Mounted on")
    print("/dev/mmcblk0p1  30951488 4590840  26360648  15% /")

def cmd_free(args):
    print("              total        used        free      shared  buff/cache   available")
    print("Mem:         1005636      581244      239876       12344      184516      349120")

def cmd_lsblk(args):
    print("NAME        MAJ:MIN RM   SIZE RO TYPE MOUNTPOINT")
    print("mmcblk0     179:0    0  29.7G  0 disk")
    print("├─mmcblk0p1 179:1    0  29.5G  0 part /")

def cmd_uptime(args):
    print(" 12:34:56 up 2:15,  1 user,  load average: 0.08, 0.03, 0.01")

def cmd_dmesg(args):
    print("[    0.000000] Booting Linux on physical CPU 0x0")
    print("[    0.000000] Linux version 5.15.93-armbian ...")

# ─── Пакетный менеджер (реальный через WSL) ──────────────────────
def cmd_apt(args):
    apt_path = shutil.which("apt")
    use_sudo = (os.name == 'posix' and os.geteuid() != 0)

    if os.name == 'posix' and apt_path:
        cmd = []
        if use_sudo:
            cmd.append("sudo")
        cmd.append("apt")
        cmd.extend(args)
        subprocess.run(cmd, check=False)
        return

    if os.name == 'nt':
        wsl = shutil.which("wsl")
        if wsl:
            subprocess.run(["wsl", "sudo", "apt"] + args, check=False)
            return
        print("apt недоступен в Windows без WSL.")
        print("  Установите WSL или используйте winget.")
        return

    print("apt: симуляция (реальный apt не обнаружен)")
    if not args:
        print("update | upgrade | install")
    elif args[0] == "update":
        print("Чтение списков пакетов… (эмуляция)")
    elif args[0] == "upgrade":
        print("Обновление пакетов… (эмуляция)")
    elif args[0] == "install":
        pkg = args[1] if len(args) > 1 else None
        if pkg:
            print(f"Установка {pkg}... (эмуляция)")
        else:
            print("apt install: укажите пакет")

def cmd_dpkg(args):
    if "-l" in args:
        print("ii  armbian-config  24.5.0  all  Armbian configuration utility")
    else:
        print("dpkg: используйте -l")

def cmd_armbian_config(args):
    print("Armbian-config (симуляция): системные настройки, сеть, обновление.")
    print("Используйте ota-update для обновления прошивки.")

# ─── Обработка текста (реальные файлы) ───────────────────────────
def cmd_head(args):
    if not args:
        return
    target = resolve_path(args[0])
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                lines = f.readlines()[:10]
                for line in lines:
                    print(line.rstrip())
        except Exception as e:
            print(f"head: ошибка: {e}")

def cmd_tail(args):
    if not args:
        return
    target = resolve_path(args[0])
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                lines = f.readlines()[-10:]
                for line in lines:
                    print(line.rstrip())
        except Exception as e:
            print(f"tail: ошибка: {e}")

def cmd_wc(args):
    if not args:
        return
    target = resolve_path(args[0])
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                count = sum(1 for _ in f)
            print(f"{count} строк")
        except Exception as e:
            print(f"wc: ошибка: {e}")

def cmd_sort(args):
    if not args:
        return
    target = resolve_path(args[0])
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                lines = sorted(line.rstrip() for line in f)
            print("\n".join(lines))
        except Exception as e:
            print(f"sort: ошибка: {e}")

def cmd_uniq(args):
    if not args:
        return
    target = resolve_path(args[0])
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                seen = set()
                for line in f:
                    line = line.rstrip()
                    if line not in seen:
                        print(line)
                        seen.add(line)
        except Exception as e:
            print(f"uniq: ошибка: {e}")

def cmd_diff(args):
    if len(args) < 2:
        print("diff: требуется два файла")
        return
    a = resolve_path(args[0])
    b = resolve_path(args[1])
    if os.path.isfile(a) and os.path.isfile(b):
        import difflib
        with open(a, "r", encoding="utf-8") as fa, open(b, "r", encoding="utf-8") as fb:
            diff = difflib.unified_diff(fa.readlines(), fb.readlines(), fromfile=args[0], tofile=args[1])
            sys.stdout.writelines(diff)
    else:
        print("diff: оба аргумента должны быть файлами")

def cmd_tar(args):
    print("tar: симуляция архивации (создан архив.tar)")

def cmd_gzip(args):
    print("gzip: симуляция сжатия")

# ─── Сервисы (эмуляция) ─────────────────────────────────────────
def cmd_systemctl(args):
    if "status" in args:
        print("● armbian-ota.service - OTA Update Service")
    else:
        print("systemctl: status|start|stop")

def cmd_journalctl(args):
    print("-- Logs begin at Mon 2024-01-01 00:00:00 UTC. --")

def cmd_timedatectl(args):
    print(datetime.now().strftime("Local time: %a %Y-%m-%d %H:%M:%S %Z"))

# ─── Псевдо‑рабочий стол и файловый менеджер ────────────────────
def cmd_de(args):
    """Текстовый рабочий стол с меню."""
    print("\n" * 2)
    print("╔══════════════════════════════════════════╗")
    print("║        Armbian Desktop Environment       ║")
    print("╠══════════════════════════════════════════╣")
    print("║                                          ║")
    print("║   📁 File Manager       (mc)            ║")
    print("║   📝 Text Editor        (nano)          ║")
    print("║   🧮 Calculator         (calc)          ║")
    print("║   💻 Terminal           (back)          ║")
    print("║   ⏻  Shutdown           (shutdown)      ║")
    print("║                                          ║")
    print("╚══════════════════════════════════════════╝")
    print("\nИспользуйте стрелки ↑↓ и Enter для выбора, Esc для выхода")

    items = [
        ("File Manager", "mc"),
        ("Text Editor", "nano "),
        ("Calculator", "calc"),
        ("Terminal", ""),
        ("Shutdown", "shutdown"),
    ]
    current = 0
    if os.name != 'nt':
        import tty, termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                sys.stdout.write("\033[2J\033[H")
                print("╔══════════════════════════════════════════╗")
                print("║        Armbian Desktop Environment       ║")
                print("╠══════════════════════════════════════════╣")
                print("║                                          ║")
                for i, (label, _) in enumerate(items):
                    if i == current:
                        print(f"║  \033[7m {label:37} \033[0m  ║")
                    else:
                        print(f"║   {label:37}   ║")
                print("║                                          ║")
                print("╚══════════════════════════════════════════╝")
                sys.stdout.flush()
                key = sys.stdin.read(1)
                if key == '\x1b':
                    next1, next2 = sys.stdin.read(2)
                    if next1 == '[':
                        if next2 == 'A':
                            current = (current - 1) % len(items)
                        elif next2 == 'B':
                            current = (current + 1) % len(items)
                elif key == '\r':
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                    chosen_cmd = items[current][1]
                    if chosen_cmd:
                        if chosen_cmd == "shutdown":
                            cmd_shutdown([])
                        elif chosen_cmd == "mc":
                            cmd_mc([])
                        else:
                            if chosen_cmd == "nano ":
                                filename = input("Введите имя файла: ")
                                cmd_nano([filename])
                            elif chosen_cmd == "calc":
                                cmd_calc([])
                    break
                elif key == '\x1b':
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                    break
        except:
            pass
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            print("\nРабочий стол закрыт.")
    else:
        print("\n(Интерактивное меню недоступно на Windows без дополнительных модулей)")
        print("Выполните 'mc', 'nano <file>', 'calc' или 'shutdown' вручную.")

def cmd_mc(args):
    """Простой двухпанельный файловый менеджер (упрощённый)."""
    left_path = get_cwd_real()
    right_path = get_cwd_real()

    def show_panels():
        print("\n" + "="*80)
        print(f"{'Left':<38} │ {'Right':>38}")
        print("="*80)
        left_items = os.listdir(left_path) if os.path.isdir(left_path) else []
        right_items = os.listdir(right_path) if os.path.isdir(right_path) else []
        max_lines = max(len(left_items), len(right_items), 20)
        for i in range(max_lines):
            left = left_items[i] if i < len(left_items) else ""
            right = right_items[i] if i < len(right_items) else ""
            print(f"{left:<38} │ {right:>38}")
        print("="*80)
        print("F5 Copy  F6 Move  F10 Quit")
        print(f"Left:  {real_path_to_virtual(left_path)}")
        print(f"Right: {real_path_to_virtual(right_path)}")

    show_panels()
    while True:
        cmd = input("mc> ").strip().lower()
        if cmd in ('q', 'quit', 'f10', 'exit'):
            break
        elif cmd.startswith('cd '):
            _, new_dir = cmd.split(maxsplit=1)
            new = resolve_path(new_dir)
            if os.path.isdir(new):
                left_path = new
        elif cmd == 'copy' or cmd == 'f5':
            src = input("Source file: ")
            dst = input("Destination: ")
            try:
                shutil.copy2(resolve_path(src), resolve_path(dst))
                print("Copied.")
            except Exception as e:
                print(f"Error: {e}")
        elif cmd == 'move' or cmd == 'f6':
            src = input("Source file: ")
            dst = input("Destination: ")
            try:
                shutil.move(resolve_path(src), resolve_path(dst))
                print("Moved.")
            except Exception as e:
                print(f"Error: {e}")
        else:
            print("Commands: cd, copy, move, quit")
        show_panels()

def cmd_calc(args):
    """Простой калькулятор."""
    print("Калькулятор (введите выражение, 'exit' для выхода)")
    while True:
        try:
            expr = input("calc> ")
            if expr.lower() in ('exit', 'quit', 'q'):
                break
            result = eval(expr)
            print(f"= {result}")
        except Exception as e:
            print(f"Ошибка: {e}")

# ─── OTA-обновление (настоящее) ──────────────────────────────────
def cmd_ota_update(args):
    print("══════════════════════════════════════")
    print("🔄 ЗАПУСК OTA ОБНОВЛЕНИЯ ARMBRIAN")
    print("══════════════════════════════════════")
    print("🔍 Проверка наличия обновлений...")

    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

    latest_version = None
    for attempt in range(3):
        try:
            resp = session.get(VERSION_URL, timeout=15)
            resp.raise_for_status()
            latest_version = resp.text.strip()
            break
        except requests.exceptions.SSLError:
            try:
                resp = session.get(VERSION_URL, timeout=15, verify=False)
                latest_version = resp.text.strip()
                print("⚠️  SSL проверка отключена (небезопасно)")
                break
            except Exception as e:
                if attempt == 2:
                    print(f"❌ Не удалось проверить версию: {e}")
                    return
        except requests.exceptions.ConnectionError as e:
            if attempt == 2:
                print(f"❌ Ошибка соединения: {e}")
                return
        except Exception as e:
            if attempt == 2:
                print(f"❌ Ошибка: {e}")
                return
        time.sleep(2)

    if not latest_version:
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

    new_code = None
    for attempt in range(3):
        try:
            resp = session.get(UPDATE_URL, timeout=30, verify=True)
            resp.raise_for_status()
            new_code = resp.content
            break
        except requests.exceptions.SSLError:
            try:
                resp = session.get(UPDATE_URL, timeout=30, verify=False)
                new_code = resp.content
                print("⚠️  SSL проверка отключена при загрузке обновления")
                break
            except Exception as e:
                if attempt == 2:
                    print(f"❌ Ошибка загрузки: {e}")
        except Exception as e:
            if attempt == 2:
                print(f"❌ Ошибка загрузки: {e}")
        time.sleep(2)

    if new_code is None and os.name == 'nt':
        print("⚠️  Попытка загрузки через PowerShell...")
        try:
            ps_cmd = f"powershell -Command \"[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '{UPDATE_URL}' -OutFile '{backup_file}' -UseBasicParsing\""
            subprocess.run(ps_cmd, shell=True, check=True)
            with open(backup_file, "rb") as f:
                new_code = f.read()
        except Exception as e:
            print(f"❌ Не удалось загрузить через PowerShell: {e}")

    if new_code is None:
        print("❌ Все способы загрузки не сработали.")
        return

    shutil.copy2(current_file, backup_file)
    try:
        with open(current_file, "wb") as f:
            f.write(new_code)
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

# ─── Словарь команд (полный) ─────────────────────────────────────
commands = {
    "help": cmd_help,
    "man": cmd_man,
    "ls": cmd_ls,
    "cd": cmd_cd,
    "pwd": cmd_pwd,
    "cat": cmd_cat,
    "touch": cmd_touch,
    "mkdir": cmd_mkdir,
    "rm": cmd_rm,
    "cp": cmd_cp,
    "mv": cmd_mv,
    "echo": cmd_echo,
    "grep": cmd_grep,
    "chmod": cmd_chmod,
    "whoami": cmd_whoami,
    "hostname": cmd_hostname,
    "date": cmd_date,
    "cal": cmd_cal,
    "uname": cmd_uname,
    "clear": cmd_clear,
    "history": cmd_history,
    "nano": cmd_nano,
    "exit": cmd_exit,
    "shutdown": cmd_shutdown,
    "ifconfig": cmd_ifconfig,
    "ping": cmd_ping,
    "netstat": cmd_netstat,
    "nslookup": cmd_nslookup,
    "wget": cmd_wget,
    "curl": cmd_curl,
    "top": cmd_top,
    "ps": cmd_ps,
    "kill": cmd_kill,
    "df": cmd_df,
    "free": cmd_free,
    "lsblk": cmd_lsblk,
    "uptime": cmd_uptime,
    "dmesg": cmd_dmesg,
    "apt": cmd_apt,
    "dpkg": cmd_dpkg,
    "armbian-config": cmd_armbian_config,
    "head": cmd_head,
    "tail": cmd_tail,
    "wc": cmd_wc,
    "sort": cmd_sort,
    "uniq": cmd_uniq,
    "diff": cmd_diff,
    "tar": cmd_tar,
    "gzip": cmd_gzip,
    "systemctl": cmd_systemctl,
    "journalctl": cmd_journalctl,
    "timedatectl": cmd_timedatectl,
    "de": cmd_de,
    "desktop": cmd_de,
    "startx": cmd_de,
    "mc": cmd_mc,
    "calc": cmd_calc,
    "ota-update": cmd_ota_update,
}

# ─── Главный цикл ─────────────────────────────────────────────────
def main():
    # Создаём базовые каталоги внутри песочницы
    for d in ["home/armbian", "etc", "tmp", "bin", "usr", "var"]:
        os.makedirs(os.path.join(SANDBOX, d), exist_ok=True)
    armbian_home = os.path.join(SANDBOX, "home", "armbian")
    change_dir(armbian_home)

    if readline is not None:
        readline.set_history_length(1000)
        histfile = os.path.join(os.path.expanduser("~"), ".armbian_webos_history")
        try:
            readline.read_history_file(histfile)
        except FileNotFoundError:
            pass

    print("🛠️ Armbian 24.5.0 (ядро 5.15.93) — загрузка завершена.")
    print("Реальная файловая система в песочнице:", SANDBOX)
    print("Добро пожаловать! Введите help для списка команд.")
    print("Попробуйте: de (рабочий стол), ota-update, apt update, nano readme.txt\n")

    while True:
        try:
            line = input(prompt())
        except (EOFError, KeyboardInterrupt):
            print("\nИспользуйте 'exit' для выхода")
            continue
        if not line.strip():
            continue
        parts = []
        current = ""
        in_quotes = False
        for ch in line:
            if ch == '"':
                in_quotes = not in_quotes
            elif ch == ' ' and not in_quotes:
                if current:
                    parts.append(current)
                    current = ""
            else:
                current += ch
        if current:
            parts.append(current)
        cmd = parts[0]
        args = parts[1:]
        if cmd in commands:
            try:
                commands[cmd](args)
            except Exception as e:
                print(f"Ошибка выполнения команды: {e}")
        else:
            print(f"{cmd}: команда не найдена")

    if readline is not None:
        try:
            readline.write_history_file(histfile)
        except Exception:
            pass

if __name__ == "__main__":
    main()
