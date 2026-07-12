#!/usr/bin/env python3
"""
Armbian WebOS Terminal — симуляция ОС на Python с реальным OTA‑обновлением и реальным APT.
Кроссплатформенная версия (Windows / Linux / macOS)
"""

import os
import sys
import shutil
import subprocess
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ---------- кросс‑платформенный readline ----------
try:
    import readline
except ImportError:
    try:
        import pyreadline3 as readline
    except ImportError:
        readline = None
        print("Предупреждение: история команд недоступна (установите pyreadline3 на Windows)")

VERSION = "1.0.0"
USER = "armbian"
HOSTNAME = "armbian-pc"

UPDATE_URL = "https://raw.githubusercontent.com/confing-sys/py_OS/main/armbian_webos.py"
VERSION_URL = "https://raw.githubusercontent.com/confing-sys/py_OS/main/version.txt"

# ─── Виртуальная файловая система (в памяти) ──────────────────────
fs = {
    "/": {
        "type": "dir",
        "children": {
            "bin": {"type": "dir", "children": {}},
            "boot": {"type": "dir", "children": {}},
            "dev": {"type": "dir", "children": {}},
            "etc": {
                "type": "dir",
                "children": {
                    "hostname": {"type": "file", "content": HOSTNAME},
                    "passwd": {"type": "file", "content": "root:x:0:0:root:/root:/bin/bash\narmbian:x:1000:1000::/home/armbian:/bin/bash"},
                },
            },
            "home": {
                "type": "dir",
                "children": {
                    "armbian": {
                        "type": "dir",
                        "children": {
                            ".bashrc": {"type": "file", "content": "export PS1='\\u@\\h:\\w$ '"},
                            "documents": {
                                "type": "dir",
                                "children": {
                                    "readme.txt": {"type": "file", "content": "Добро пожаловать в Armbian WebOS!\nИспользуйте help для списка команд.\nOTA‑обновление: ota-update"},
                                    "notes.txt": {"type": "file", "content": "Купить молоко\nПозвонить маме\n"},
                                },
                            },
                            "downloads": {"type": "dir", "children": {}},
                            "music": {"type": "dir", "children": {}},
                        }
                    }
                },
            },
            "media": {"type": "dir", "children": {}},
            "mnt": {"type": "dir", "children": {}},
            "opt": {"type": "dir", "children": {}},
            "proc": {"type": "dir", "children": {}},
            "root": {"type": "dir", "children": {}},
            "run": {"type": "dir", "children": {}},
            "srv": {"type": "dir", "children": {}},
            "sys": {"type": "dir", "children": {}},
            "tmp": {"type": "dir", "children": {}},
            "usr": {"type": "dir", "children": {}},
            "var": {"type": "dir", "children": {}},
        },
    }
}

cwd = ["/", "home", "armbian"]

# ─── Вспомогательные функции ──────────────────────────────────────
def get_node(path_list):
    node = fs
    for part in path_list:
        if node["type"] != "dir" or part not in node["children"]:
            return None
        node = node["children"][part]
    return node

def get_cwd_node():
    return get_node(cwd)

def path_to_str(path_list):
    if path_list == ["/"]:
        return "/"
    return "/" + "/".join(path_list[1:])

def resolve_path(input_str):
    if not input_str.strip():
        return cwd.copy()
    parts = input_str.split("/")
    if input_str.startswith("/"):
        resolved = ["/"]
        parts = input_str[1:].split("/")
    elif input_str.startswith("~"):
        resolved = ["/", "home", "armbian"]
        if len(input_str) > 1 and input_str[1] == "/":
            parts = input_str[2:].split("/")
        else:
            parts = input_str[1:].split("/")
    else:
        resolved = cwd.copy()
        parts = input_str.split("/")
    for part in parts:
        if part == "" or part == ".":
            continue
        elif part == "..":
            if len(resolved) > 1:
                resolved.pop()
        else:
            resolved.append(part)
    return resolved

def parent_path(path_list):
    if len(path_list) <= 1:
        return ["/"]
    return path_list[:-1]

def prompt():
    p = path_to_str(cwd).replace("/home/armbian", "~")
    return f"{USER}@{HOSTNAME}:{p}$ "

# ─── Команды (реализованы полностью) ─────────────────────────────
def cmd_help(args):
    print("Доступные команды Armbian WebOS:")
    cmds = [
        "help", "man <cmd>", "ls [-la]", "cd", "pwd", "cat", "touch", "mkdir", "rm [-r]",
        "cp", "mv", "echo", "grep", "chmod", "whoami", "hostname", "date", "cal",
        "uname", "clear", "history", "nano", "exit", "shutdown",
        "─── Сеть ───", "ifconfig", "ping", "netstat", "nslookup", "wget", "curl",
        "─── Система ───", "top", "ps", "kill", "df", "free", "lsblk", "uptime", "dmesg",
        "─── Пакеты ───", "apt update/upgrade/install", "dpkg", "armbian-config",
        "─── Обработка ───", "head", "tail", "wc", "sort", "uniq", "diff", "tar", "gzip",
        "─── Сервисы ───", "systemctl", "journalctl", "timedatectl",
        "─── Обновление ───", "ota-update — реальное OTA обновление"
    ]
    for c in cmds:
        print(f"  {c}")

def cmd_man(args):
    manuals = {
        "ls": "ls - список файлов и папок.",
        "nano": "nano - встроенный текстовый редактор.",
        "apt": "apt - менеджер пакетов (реальный или симуляция).",
        "ota-update": "ota-update - проверить и установить обновление системы.",
    }
    cmd = args[0] if args else ""
    print(manuals.get(cmd, f"Нет руководства для '{cmd}'."))

def cmd_ls(args):
    long_format = "-l" in args
    show_all = "-a" in args
    path_arg = next((a for a in args if not a.startswith("-")), None)
    target = resolve_path(path_arg) if path_arg else cwd
    node = get_node(target)
    if not node or node["type"] != "dir":
        print("ls: нет такого каталога")
        return
    entries = list(node["children"].items())
    if not show_all:
        entries = [(n, v) for n, v in entries if not n.startswith(".")]
    entries.sort(key=lambda x: (x[1]["type"] != "dir", x[0]))
    if long_format:
        for name, n in entries:
            perms = "drwxr-xr-x" if n["type"] == "dir" else "-rw-r--r--"
            size = len(n.get("content", "")) if n["type"] == "file" else 0
            print(f"{perms} 1 {USER} {USER} {size:>6} {name}")
    else:
        line = []
        for name, n in entries:
            if n["type"] == "dir":
                line.append(f"\033[94m{name}\033[0m" if os.name != 'nt' else name)
            else:
                line.append(name)
        print("  ".join(line) if line else "")

def cmd_cd(args):
    if not args:
        cwd.clear()
        cwd.extend(["/", "home", "armbian"])
        return
    target = resolve_path(args[0])
    node = get_node(target)
    if not node:
        print(f"cd: '{args[0]}' не существует")
    elif node["type"] != "dir":
        print(f"cd: '{args[0]}' не каталог")
    else:
        cwd.clear()
        cwd.extend(target)

def cmd_pwd(args):
    print(path_to_str(cwd))

def cmd_cat(args):
    if not args:
        print("cat: требуется имя файла")
        return
    path = resolve_path(args[0])
    node = get_node(path)
    if not node:
        print(f"cat: {args[0]}: нет такого файла")
    elif node["type"] == "dir":
        print(f"cat: {args[0]}: это каталог")
    else:
        print(node.get("content", ""))

def cmd_touch(args):
    if not args:
        print("touch: требуется имя файла")
        return
    path = resolve_path(args[0])
    parent = get_node(parent_path(path))
    name = path[-1]
    if not parent or parent["type"] != "dir":
        print("touch: неверный путь")
        return
    if name not in parent["children"]:
        parent["children"][name] = {"type": "file", "content": ""}
    else:
        print(f"touch: файл '{name}' уже существует (обновлён)")

def cmd_mkdir(args):
    if not args:
        print("mkdir: требуется имя каталога")
        return
    path = resolve_path(args[0])
    parent = get_node(parent_path(path))
    name = path[-1]
    if not parent or parent["type"] != "dir":
        print("mkdir: неверный путь")
        return
    if name in parent["children"]:
        print(f"mkdir: '{name}' уже существует")
    else:
        parent["children"][name] = {"type": "dir", "children": {}}

def cmd_rm(args):
    recursive = "-r" in args or "-rf" in args
    targets = [a for a in args if not a.startswith("-")]
    if not targets:
        print("rm: требуется имя файла/каталога")
        return
    path = resolve_path(targets[0])
    parent = get_node(parent_path(path))
    name = path[-1]
    if not parent or name not in parent["children"]:
        print(f"rm: '{targets[0]}' не найден")
        return
    if parent["children"][name]["type"] == "dir" and not recursive:
        print("rm: невозможно удалить каталог без -r")
        return
    del parent["children"][name]

def cmd_cp(args):
    if len(args) < 2:
        print("cp: требуется источник и цель")
        return
    src = resolve_path(args[0])
    dst = resolve_path(args[1])
    src_node = get_node(src)
    if not src_node:
        print(f"cp: '{args[0]}' не найден")
        return
    if src_node["type"] == "dir":
        print("cp: пропуск каталога (без -r)")
        return
    dst_parent = get_node(parent_path(dst))
    if not dst_parent or dst_parent["type"] != "dir":
        print("cp: неверный путь назначения")
        return
    dst_name = dst[-1]
    dst_parent["children"][dst_name] = {"type": "file", "content": src_node.get("content", "")}

def cmd_mv(args):
    if len(args) < 2:
        print("mv: требуется источник и цель")
        return
    src = resolve_path(args[0])
    dst = resolve_path(args[1])
    src_node = get_node(src)
    if not src_node:
        print(f"mv: '{args[0]}' не найден")
        return
    dst_parent = get_node(parent_path(dst))
    if not dst_parent or dst_parent["type"] != "dir":
        print("mv: неверный путь назначения")
        return
    dst_name = dst[-1]
    dst_parent["children"][dst_name] = src_node
    src_parent = get_node(parent_path(src))
    del src_parent["children"][src[-1]]

def cmd_echo(args):
    text = " ".join(args)
    if ">" in text:
        parts = text.split(">")
        content = parts[0].strip()
        file_path = resolve_path(parts[1].strip())
        parent = get_node(parent_path(file_path))
        if parent and parent["type"] == "dir":
            parent["children"][file_path[-1]] = {"type": "file", "content": content}
        else:
            print("echo: ошибка записи")
    else:
        print(text)

def cmd_grep(args):
    if len(args) < 2:
        print("grep: требуется шаблон и файл")
        return
    pattern, file_arg = args[0], args[1]
    path = resolve_path(file_arg)
    node = get_node(path)
    if not node or node["type"] != "file":
        print(f"grep: {file_arg}: нет такого файла")
        return
    for i, line in enumerate(node.get("content", "").splitlines(), 1):
        if pattern in line:
            print(f"{i}:{line}")

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
    path = resolve_path(args[0])
    node = get_node(path)
    if node and node["type"] == "dir":
        print(f"nano: {args[0]}: это каталог")
        return
    content = node.get("content", "") if node else ""
    print(f"Редактирование: {path_to_str(path)}")
    print("Вводите строки (пустая строка + Enter завершает, ':q' выход без сохранения)")
    lines = content.splitlines()
    for idx, line in enumerate(lines):
        print(f"{idx+1}: {line}")
    new_lines = []
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
    new_content = "\n".join(new_lines)
    parent = get_node(parent_path(path))
    if parent and parent["type"] == "dir":
        parent["children"][path[-1]] = {"type": "file", "content": new_content}
        print(f"Файл '{args[0]}' сохранён")
    else:
        print("Ошибка сохранения")

def cmd_exit(args):
    print("Выход из оболочки...")
    sys.exit(0)

def cmd_shutdown(args):
    print("Система останавливается...")
    sys.exit(0)

# ─── Сетевые команды ──────────────────────────────────────────────
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

# ─── Системные команды ────────────────────────────────────────────
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

# ─── Пакетный менеджер (реальный + симуляция) ────────────────────
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
            subprocess.run(["wsl", "apt"] + args, check=False)
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

# ─── Обработка текста ─────────────────────────────────────────────
def cmd_head(args):
    if not args:
        return
    node = get_node(resolve_path(args[0]))
    if node and node["type"] == "file":
        print("\n".join(node.get("content", "").splitlines()[:10]))

def cmd_tail(args):
    if not args:
        return
    node = get_node(resolve_path(args[0]))
    if node and node["type"] == "file":
        print("\n".join(node.get("content", "").splitlines()[-10:]))

def cmd_wc(args):
    if not args:
        return
    node = get_node(resolve_path(args[0]))
    if node and node["type"] == "file":
        lines = node.get("content", "").splitlines()
        print(f"{len(lines)} строк")

def cmd_sort(args):
    if not args:
        return
    node = get_node(resolve_path(args[0]))
    if node and node["type"] == "file":
        print("\n".join(sorted(node.get("content", "").splitlines())))

def cmd_uniq(args):
    if not args:
        return
    node = get_node(resolve_path(args[0]))
    if node and node["type"] == "file":
        seen = set()
        for line in node.get("content", "").splitlines():
            if line not in seen:
                print(line)
                seen.add(line)

def cmd_diff(args):
    if len(args) < 2:
        print("diff: два файла")
        return
    a = get_node(resolve_path(args[0]))
    b = get_node(resolve_path(args[1]))
    if a and b and a["type"] == "file" and b["type"] == "file":
        if a["content"] != b["content"]:
            print("(файлы различаются)")
        else:
            print("(файлы идентичны)")

def cmd_tar(args):
    print("tar: симуляция архивации (создан архив.tar)")

def cmd_gzip(args):
    print("gzip: симуляция сжатия")

# ─── Сервисы ──────────────────────────────────────────────────────
def cmd_systemctl(args):
    if "status" in args:
        print("● armbian-ota.service - OTA Update Service")
    else:
        print("systemctl: status|start|stop")

def cmd_journalctl(args):
    print("-- Logs begin at Mon 2024-01-01 00:00:00 UTC. --")

def cmd_timedatectl(args):
    print(datetime.now().strftime("Local time: %a %Y-%m-%d %H:%M:%S %Z"))

# ─── OTA-обновление ──────────────────────────────────────────────
def cmd_ota_update(args):
    print("══════════════════════════════════════")
    print("🔄 ЗАПУСК OTA ОБНОВЛЕНИЯ ARMBRIAN")
    print("══════════════════════════════════════")
    print("🔍 Проверка наличия обновлений...")
    try:
        with urllib.request.urlopen(VERSION_URL, timeout=5) as resp:
            latest_version = resp.read().decode().strip()
    except Exception as e:
        print(f"❌ Не удалось проверить обновление: {e}")
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
    try:
        with urllib.request.urlopen(UPDATE_URL, timeout=30) as resp:
            new_code = resp.read()
    except Exception as e:
        print(f"❌ Ошибка загрузки: {e}")
        return
    current_file = Path(__file__).resolve()
    backup_file = current_file.with_suffix(".py.bak")
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

# ─── Словарь команд ───────────────────────────────────────────────
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
    "ota-update": cmd_ota_update,
}

# ─── Главный цикл ─────────────────────────────────────────────────
def main():
    if readline is not None:
        readline.set_history_length(1000)
        histfile = os.path.join(os.path.expanduser("~"), ".armbian_webos_history")
        try:
            readline.read_history_file(histfile)
        except FileNotFoundError:
            pass

    print("🛠️ Armbian 24.5.0 (ядро 5.15.93) — загрузка завершена.")
    print("Добро пожаловать! Введите help для списка команд.")
    print("Попробуйте: ota-update, apt update, nano readme.txt\n")

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
