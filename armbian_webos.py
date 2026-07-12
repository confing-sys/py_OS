#!/usr/bin/env python3
"""
Armbian WebOS Terminal — симуляция ОС на Python с реальным OTA‑обновлением и настоящим APT.
Кроссплатформенная версия (Windows / Linux / macOS)
"""

import os
import sys
import json
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

# ... (все функции get_node, resolve_path и т.д. без изменений) ...
def get_node(path_list):
    node = fs
    for part in path_list:
        if node["type"] != "dir" or part not in node["children"]:
            return None
        node = node["children"][part]
    return node

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

# ─── Команды (все предыдущие, плюс обновлённая cmd_apt) ─────────
# ... (все старые функции без изменений) ...

def cmd_apt(args):
    """Реальная работа с apt: на Linux/WSL вызывает системный apt, иначе эмулирует."""
    # Определяем, есть ли настоящий apt
    apt_path = shutil.which("apt")
    use_sudo = (os.name == 'posix' and os.geteuid() != 0)  # нужен ли sudo на Linux

    if os.name == 'posix' and apt_path:
        # Linux с apt
        cmd = []
        if use_sudo:
            cmd.append("sudo")
        cmd.append("apt")
        cmd.extend(args)
        try:
            subprocess.run(cmd, check=False)
        except FileNotFoundError:
            print("apt: не удалось выполнить (проверьте права sudo)")
        return

    # Проверяем Windows WSL
    if os.name == 'nt':
        wsl = shutil.which("wsl")
        if wsl:
            cmd = ["wsl", "apt"] + args
            try:
                subprocess.run(cmd, check=False)
                return
            except Exception:
                pass
        # Если ни apt, ни wsl нет – выводим подсказку
        print("apt недоступен в Windows без WSL.")
        print("  - Установите WSL и попробуйте снова.")
        print("  - Или используйте winget: winget install <пакет>")
        return

    # Если ничего не подошло, симуляция
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
            print(f"Установка {pkg}... (эмуляция: пакет не установлен)")
        else:
            print("apt install: укажите пакет")

# ... (остальные команды без изменений) ...

# ─── OTA-обновление (кроссплатформенное) ─────────────────────────
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

# ─── Словарь команд (все команды) ────────────────────────────────
commands = {
    "help": cmd_help, "man": cmd_man, "ls": cmd_ls, "cd": cmd_cd,
    "pwd": cmd_pwd, "cat": cmd_cat, "touch": cmd_touch, "mkdir": cmd_mkdir,
    "rm": cmd_rm, "cp": cmd_cp, "mv": cmd_mv, "echo": cmd_echo,
    "grep": cmd_grep, "chmod": cmd_chmod, "whoami": cmd_whoami,
    "hostname": cmd_hostname, "date": cmd_date, "cal": cmd_cal,
    "uname": cmd_uname, "clear": cmd_clear, "history": cmd_history,
    "nano": cmd_nano, "exit": cmd_exit, "shutdown": cmd_shutdown,
    "ifconfig": cmd_ifconfig, "ping": cmd_ping, "netstat": cmd_netstat,
    "nslookup": cmd_nslookup, "wget": cmd_wget, "curl": cmd_curl,
    "top": cmd_top, "ps": cmd_ps, "kill": cmd_kill, "df": cmd_df,
    "free": cmd_free, "lsblk": cmd_lsblk, "uptime": cmd_uptime,
    "dmesg": cmd_dmesg, "apt": cmd_apt, "dpkg": cmd_dpkg,
    "armbian-config": cmd_armbian_config, "head": cmd_head,
    "tail": cmd_tail, "wc": cmd_wc, "sort": cmd_sort, "uniq": cmd_uniq,
    "diff": cmd_diff, "tar": cmd_tar, "gzip": cmd_gzip,
    "systemctl": cmd_systemctl, "journalctl": cmd_journalctl,
    "timedatectl": cmd_timedatectl, "ota-update": cmd_ota_update,
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

        # Разбор строки с учётом кавычек
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

    # Сохранение истории
    try:
        readline.write_history_file(histfile)
    except Exception:
        pass

if __name__ == "__main__":
    main()
