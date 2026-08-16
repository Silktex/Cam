#!/usr/bin/env python3
import subprocess
import sys

if len(sys.argv) < 2:
    print("Usage: python3 run_on_ind.py <command>")
    sys.exit(1)

cmd = " ".join(sys.argv[1:])
# Escape single quotes
escaped_cmd = cmd.replace("'", "'\"'\"'")
remote_cmd = f"ssh -i ~/.ssh/id_rc_ed25519 -o StrictHostKeyChecking=no posh@10.10.2.21 '{escaped_cmd}'"

p = subprocess.Popen(
    ["ssh", "ap", remote_cmd],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)
stdout, stderr = p.communicate()
sys.stdout.write(stdout)
sys.stderr.write(stderr)
sys.exit(p.returncode)
