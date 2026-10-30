"""Kleine Prompt-Helfer – zentral, damit Tests sie leicht monkeypatchen können."""

from __future__ import annotations

import getpass
import sys


def is_tty() -> bool:
    """``True`` nur wenn stdin ein Terminal ist (Agenten liefern meist False)."""
    try:
        return bool(sys.stdin.isatty())
    except Exception:
        return False


def ask(question: str, *, default: str | None = None) -> str:
    prompt = f"{question} [{default}]: " if default else f"{question}: "
    try:
        return input(prompt)
    except EOFError:
        return ""


def ask_secret(question: str) -> str:
    try:
        return getpass.getpass(f"{question}: ")
    except (EOFError, KeyboardInterrupt):
        return ""


def confirm(question: str, *, default: bool = False) -> bool:
    suffix = "[J/n]" if default else "[j/N]"
    answer = ask(f"{question} {suffix}").strip().lower()
    if not answer:
        return default
    return answer in ("j", "ja", "y", "yes")
