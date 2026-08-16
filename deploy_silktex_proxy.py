#!/usr/bin/env python3
import subprocess
import base64
import time
import sys

def run_cmd(cmd):
    b64 = base64.b64encode(cmd.encode()).decode()
    remote_script = f"echo {b64} | base64 -d | sudo bash"
    
    # 1. Try via ap jump (reliable)
    try:
        p = subprocess.Popen(
            ['ssh', '-o', 'ControlPath=none', 'ap', f'ssh -n -i ~/.ssh/id_rc_ed25519 -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=8 posh@10.10.2.21 "{remote_script}"'],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        out, err = p.communicate(timeout=45)
        if p.returncode == 0 or out.strip():
            return out, err, p.returncode
    except Exception as e:
        pass

    # 2. Try direct
    try:
        p = subprocess.Popen(
            ['ssh', '-i', '/home/rc/.ssh/id_ed25519', '-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=5', 'posh@10.10.2.21', f'echo {b64} | base64 -d | sudo bash'],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        out, err = p.communicate(timeout=45)
        return out, err, p.returncode
    except Exception as e:
        return "", str(e), 1

def main():
    print("=== Step 1: Ensuring Apache2 is stopped & disabled on ind ===")
    out, err, code = run_cmd("systemctl stop apache2 && systemctl disable apache2")
    print(out, err)

    print("=== Step 2: Updating silktex-proxy container to bind Port 80 and Port 443 ===")
    proxy_cmd = """
docker stop silktex-proxy 2>/dev/null || true
docker rm silktex-proxy 2>/dev/null || true
docker run -d \
  --name silktex-proxy \
  --restart unless-stopped \
  -e NB_PROXY_TOKEN=nbx_gaDeN1kXWsSdOyRoaipajE1fQw4Mkj2PRLeO \
  -e NB_PROXY_MANAGEMENT_ADDRESS=https://nb.rs74.net \
  -e NB_PROXY_ADDRESS=:8443 \
  -e NB_PROXY_ACME_ADDR=:80 \
  -e NB_PROXY_DOMAIN=proxy.silktex.com \
  -e NB_PROXY_PRIVATE=true \
  -e NB_PROXY_ACME_CERTIFICATES=true \
  -p 80:80 \
  -p 443:8443 \
  netbirdio/reverse-proxy:0.72.2
"""
    out, err, code = run_cmd(proxy_cmd)
    print(out, err)

    print("=== Step 3: Checking docker ps on ind ===")
    out, err, code = run_cmd("docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'")
    print(out)

    print("=== Step 4: Rebuilding & Restarting Camera System Studio Frontend ===")
    rebuild_cmd = "cd /home/posh/projects/camera_system && docker compose up -d --build camera-system"
    out, err, code = run_cmd(rebuild_cmd)
    print(out, err)

if __name__ == '__main__':
    main()
