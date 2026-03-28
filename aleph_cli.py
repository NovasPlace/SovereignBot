#!/usr/bin/env python3
"""ALEPH Bootstrap CLI — Zero-Config Node Operations"""

import argparse
import subprocess
import os
import sys
import time
import re

def spin_tunnel(port: int = 8800) -> tuple[subprocess.Popen, str]:
    """Launch cloudflared quick tunnel and wait for the live URL."""
    print("\033[38;2;29;207;176m[ALEPH]\033[0m \033[38;2;250;200;80mProvisioning ephemeral federated tunnel...\033[0m")
    
    # Check if cloudflared is installed
    try:
        subprocess.run(["cloudflared", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("\033[31m[ALEPH ERROR] 'cloudflared' not found. Please install cloudflared to use --join.\033[0m")
        sys.exit(1)

    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    url = None
    url_pattern = re.compile(r"(https://[a-zA-Z0-9-]+\.trycloudflare\.com)")
    
    start_time = time.time()
    for line in iter(proc.stdout.readline, ''):
        match = url_pattern.search(line)
        if match:
            url = match.group(1)
            break
            
        if time.time() - start_time > 15:
            print("\033[31m[ALEPH TIMEOUT] Failed to acquire tunnel URL within 15 seconds.\033[0m")
            proc.terminate()
            sys.exit(1)
            
    if not url:
        print("\033[31m[ALEPH ERROR] Could not parse trycloudflare.com URL.\033[0m")
        proc.terminate()
        sys.exit(1)
        
    return proc, url

def main() -> None:
    parser = argparse.ArgumentParser(description="ALEPH Sovereign Node CLI")
    parser.add_argument("--join", action="store_true", help="Auto-provision a tunnel and join the federated mesh")
    args, unknown = parser.parse_known_args()
    
    tunnel_proc = None
    if args.join:
        tunnel_proc, url = spin_tunnel(port=8800)
        # Inject the parsed ephemeral URL into the environment for daemon + routes to pick up
        os.environ["ALEPH_NODE_URL"] = url
        
        # Display the "UX Banner" using pure ANSI (dependency-free)
        print(f"\n\033[38;2;29;207;176m● NODE ONLINE\033[0m")
        print(f"You have joined the ALEPH Federated Network.")
        print(f"Live URI: \033[1;38;2;255;255;255m{url}\033[0m\n")
    else:
        # Default local URL unless overridden in .env
        if "ALEPH_NODE_URL" not in os.environ:
            os.environ["ALEPH_NODE_URL"] = "http://localhost:8800"
            
    try:
        # Import and run Sovereign daemon
        from sovereign.daemon import run
        # Pass remaining arguments to the daemon framework if applicable
        sys.argv = [sys.argv[0]] + unknown
        run()
    except KeyboardInterrupt:
        pass
    finally:
        if tunnel_proc:
            print("\n\033[38;2;250;200;80m[ALEPH] Tearing down ephemeral tunnel...\033[0m")
            tunnel_proc.terminate()
            tunnel_proc.wait()

if __name__ == "__main__":
    main()
