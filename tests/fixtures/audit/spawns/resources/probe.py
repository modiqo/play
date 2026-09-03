from __future__ import annotations
import subprocess


def main() -> int:
    subprocess.run(["docker", "ps"], check=False)
    subprocess.run(["python3", "-V"], check=False)
    return 0
