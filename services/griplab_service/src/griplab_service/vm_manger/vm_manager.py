#!/usr/bin/env python3
"""
Distributed VM Orchestrator (vm_manager.py)
An automated, cross-platform CLI tool to manage developer sandboxes.

Features:
  1. Installs host-level hypervisor tools (QEMU) across macOS, Linux, and Windows.
  2. Implements a modular Tool Recipe Registry (Rust, Node, Python, UV, PostgreSQL, etc.)
     to compile custom read-only base templates.
  3. Spawns thin writable workspace overlays via QCOW2 backing layers.
  4. Manages runtime VM processes and automates host discovery via local SSH Config integration.

Zero external library dependencies. Uses Python standard library only.
"""

import os
import sys
import json
import platform
import subprocess
import argparse
import shutil
import uuid
import time
import socket
from pathlib import Path

# --- Constants & Paths ---
APP_DIR = Path.home() / ".config" / "distrovm"
DB_FILE = APP_DIR / "vms.json"
BASE_IMG_DIR = APP_DIR / "base_images"
INSTANCE_DIR = APP_DIR / "instances"
SSH_CONFIG_FILE = Path.home() / ".ssh" / "config"

# --- Tool Recipe Registry ---
TOOL_RECIPES = {
    "rust": {
        "description": "Rust Language Toolchain (rustup, rustc, cargo)",
        "commands": [
            "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y",
            "echo 'export PATH=\"$HOME/.cargo/bin:$PATH\"' >> $HOME/.bashrc"
        ]
    },
    "node": {
        "description": "Node.js Environment (via fnm manager)",
        "commands": [
            "curl -fsSL https://fnm.vercel.sh/install | bash",
            "export PATH=\"$HOME/.local/share/fnm:$PATH\"",
            "eval \"$(fnm env)\"",
            "fnm install --lts"
        ]
    },
    "python": {
        "description": "Python Toolchain (via pyenv with developer headers)",
        "commands": [
            "sudo apt-get update && sudo apt-get install -y make build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev",
            "curl https://pyenv.run | bash",
            "echo 'export PYENV_ROOT=\"$HOME/.pyenv\"' >> $HOME/.bashrc",
            "echo '[[ -d $PYENV_ROOT/bin ]] && export PATH=\"$PYENV_ROOT/bin:$PATH\"' >> $HOME/.bashrc",
            "echo 'eval \"$(pyenv init -)\"' >> $HOME/.bashrc"
        ]
    },
    "uv": {
        "description": "Astral UV (Extremely fast Python packager)",
        "commands": [
            "curl -LsSf https://astral.sh/uv/install.sh | sh"
        ]
    },
    "postgresql": {
        "description": "PostgreSQL Database Engine Server",
        "commands": [
            "sudo apt-get update && sudo apt-get install -y postgresql postgresql-contrib",
            "sudo systemctl enable postgresql",
            "sudo systemctl start postgresql"
        ]
    }
}


def init_directories():
    """Initializes local storage directories and configurations."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    BASE_IMG_DIR.mkdir(parents=True, exist_ok=True)
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    SSH_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    if not DB_FILE.exists():
        with open(DB_FILE, "w") as f:
            json.dump({"bases": {}, "instances": {}}, f, indent=4)


def load_db():
    """Loads current database model."""
    init_directories()
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        print("[!] Database file corrupted. Resetting state.", file=sys.stderr)
        return {"bases": {}, "instances": {}}


def save_db(db):
    """Commits database changes."""
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=4)


# --- System Architecture Helpers ---
def get_host_arch():
    machine = platform.machine().lower()
    if "arm" in machine or "aarch64" in machine:
        return "aarch64"
    return "x86_64"


def get_qemu_executable(arch):
    if arch == "aarch64":
        return "qemu-system-aarch64"
    return "qemu-system-x86_64"


def get_acceleration_flags(arch):
    system = platform.system().lower()
    host_arch = get_host_arch()

    if host_arch != arch:
        return []

    if system == "darwin":  # macOS (Hypervisor.framework)
        if arch == "aarch64":
            return ["-accel", "hvf", "-cpu", "host"]
        return ["-accel", "hvf", "-cpu", "max"]
    elif system == "linux":  # Linux (KVM)
        return ["-enable-kvm", "-cpu", "host"]
    elif system == "windows":  # Windows (Windows Hypervisor Platform)
        return ["-accel", "whpx", "-cpu", "host"]
    
    return []


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def get_unused_port(start=2222):
    port = start
    while is_port_in_use(port):
        port += 1
    return port


# --- Feature 1: Host Dependency Manager ---
def setup_host_environment(args):
    """Installs hypervisor packages natively according to current OS."""
    system = platform.system().lower()
    print(f"[*] Detecting Host OS: {system.upper()}...")
    
    if system == "darwin":
        if shutil.which("brew"):
            print("[*] Homebrew detected. Installing QEMU virtualizer...")
            subprocess.run(["brew", "install", "qemu"], check=True)
            print("[+] QEMU installed successfully!")
        else:
            print("[-] Error: Homebrew is required on macOS to automate setup.", file=sys.stderr)
            print("    Please install Homebrew (https://brew.sh/) or install QEMU manually.", file=sys.stderr)
            sys.exit(1)
            
    elif system == "linux":
        # Check package manager
        if shutil.which("apt-get"):
            print("[*] Debian/Ubuntu system detected. Installing virtualization utilities...")
            subprocess.run(["sudo", "apt-get", "update"], check=True)
            subprocess.run(["sudo", "apt-get", "install", "-y", "qemu-system-x86", "qemu-utils", "iproute2"], check=True)
            print("[+] QEMU and utilities installed successfully!")
        else:
            print("[-] Unsupported Linux package manager. Please install QEMU system utilities manually.", file=sys.stderr)
            sys.exit(1)
            
    elif system == "windows":
        print("[*] Windows detected. To run QEMU properly:")
        print("    1. Install Chocolatey package manager (https://chocolatey.org/)")
        print("    2. Open administrative powershell and run: `choco install qemu`")
        print("    3. Enable 'Windows Hypervisor Platform' via optional system features.")
    else:
        print(f"[-] Unsupported operating system: {system}", file=sys.stderr)


# --- Feature 2 & 3: Read-Only Template Manager & Provisioner ---
def list_recipes(args):
    """Lists available pre-defined compiler toolchain install recipes."""
    print("\n=== AVAILABLE DEVELOPMENT TOOL RECIPES ===")
    for key, val in TOOL_RECIPES.items():
        print(f"• {key:<12} : {val['description']}")
    print()


def compile_base_template(args):
    """Compiles custom read-only VM bases by automating tool installations inside a clean OS seed."""
    db = load_db()
    name = args.name
    tools = args.tools or []
    
    if name in db["bases"]:
        print(f"[-] Error: A base image named '{name}' already exists.", file=sys.stderr)
        sys.exit(1)

    # Validate tools requested
    invalid_tools = [t for t in tools if t not in TOOL_RECIPES]
    if invalid_tools:
        print(f"[-] Error: Unrecognized tool recipes requested: {invalid_tools}", file=sys.stderr)
        print("    Run `python vm_manager.py list-recipes` to view choices.", file=sys.stderr)
        sys.exit(1)

    source_path = Path(args.source).resolve()
    if not source_path.exists():
        print(f"[-] Error: Original cloud image file not found at: {source_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Preparing temporary Workspace to compile base image '{name}'...")
    dest_path = BASE_IMG_DIR / f"{name}.qcow2"
    
    # Copy fresh seed disk image
    shutil.copy2(source_path, dest_path)
    
    if tools:
        print(f"[*] Booting sandbox VM to execute installations: {', '.join(tools)}...")
        temp_port = get_unused_port()
        arch = args.arch or get_host_arch()
        qemu_bin = get_qemu_executable(arch)
        accel = get_acceleration_flags(arch)
        
        # Build boot command
        boot_cmd = [
            qemu_bin,
            "-m", "4096",
            "-smp", "2",
            "-drive", f"file={dest_path},if=virtio",
            "-net", "nic,model=virtio",
            "-net", f"user,hostfwd=tcp::{temp_port}-:22",
            "-nographic"
        ]
        boot_cmd.extend(accel)
        
        # Spawn VM
        p = subprocess.Popen(boot_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        print(f"[*] VM Booted inside engine (PID: {p.pid}). Waiting for SSH server to wake up on port {temp_port}...")
        # Simple loop waiting for port availability
        ssh_ready = False
        for _ in range(15):
            time.sleep(3)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('127.0.0.1', temp_port)) == 0:
                    ssh_ready = True
                    break
        
        if not ssh_ready:
            print("[-] Error: SSH host connection failed inside guest compilation sandbox. Terminating boot.", file=sys.stderr)
            p.terminate()
            dest_path.unlink()
            sys.exit(1)

        print("[+] Guest VM SSH server ready. Initiating provisioning scripts...")
        
        # Execute selected tool installation lines
        ssh_user = args.user
        ssh_opts = ["-p", str(temp_port), "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", f"{ssh_user}@localhost"]
        
        for tool in tools:
            print(f"[*] Installing tool recipe: {tool}...")
            recipe = TOOL_RECIPES[tool]
            for cmd in recipe["commands"]:
                full_ssh_cmd = ["ssh"] + ssh_opts + [cmd]
                subprocess.run(full_ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
        print("[*] Provisioning finished. Powering down template sandbox...")
        # Send poweroff signal
        subprocess.run(["ssh"] + ssh_opts + ["sudo poweroff"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p.wait()

    # Seal the filesystem - remove write permissions to secure template integrity
    os.chmod(dest_path, 0o444)
    
    db["bases"][name] = {
        "path": str(dest_path),
        "arch": args.arch or get_host_arch(),
        "tools": tools
    }
    save_db(db)
    print(f"[+] Compiled Read-Only Toolchain Base Template successfully: '{name}'!")


# --- Feature 4: Writable Workspace Overlays ---
def create_workspace(args):
    """Creates a light writable Copy-on-Write QCOW2 overlay linked to a specified base."""
    db = load_db()
    
    if not db["bases"]:
        print("[-] Error: No compiled bases found. Run 'compile-base' first.", file=sys.stderr)
        sys.exit(1)

    selected_base = args.base
    if not selected_base:
        bases = list(db["bases"].keys())
        print("\n=== SELECT REGISTERED BASE IMAGE ===")
        for i, b in enumerate(bases, 1):
            print(f"[{i}] {b} (Tools: {', '.join(db['bases'][b]['tools'])})")
        while True:
            try:
                ch = int(input(f"Selection (1-{len(bases)}): "))
                if 1 <= ch <= len(bases):
                    selected_base = bases[ch-1]
                    break
            except ValueError:
                pass
            print("[-] Invalid choice.")

    base_info = db["bases"][selected_base]
    name = args.name or f"ws-{uuid.uuid4().hex[:6]}"
    
    if name in db["instances"]:
        print(f"[-] Error: Workspace '{name}' already exists.", file=sys.stderr)
        sys.exit(1)

    ram = args.ram or 4096
    cpus = args.cpus or 4
    port = args.ssh_port or get_unused_port(2222)

    # Double check port collision
    for inst in db["instances"].values():
        if inst["ssh_port"] == port:
            print(f"[-] Error: Selected port {port} is occupied by workspace VM '{inst['name']}'.", file=sys.stderr)
            sys.exit(1)

    instance_disk = INSTANCE_DIR / f"{name}.qcow2"
    
    # Create backing file connection
    cmd = [
        "qemu-img", "create",
        "-f", "qcow2",
        "-b", base_info["path"],
        "-F", "qcow2",
        str(instance_disk)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)

    db["instances"][name] = {
        "name": name,
        "base": selected_base,
        "disk_path": str(instance_disk),
        "ram": ram,
        "cpus": cpus,
        "ssh_port": port,
        "arch": base_info["arch"],
        "pid": None,
        "ssh_user": args.user
    }
    save_db(db)
    print(f"[+] Writable development overlay '{name}' constructed!")
    print(f"    - To start, run: `python vm_manager.py start {name}`")


# --- Feature 5: Runtime State, Host Discovery & SSH Configuration Sync ---

def update_ssh_config():
    """Reads all running instances and writes their current ports to the SSH config file

    to ensure 'ssh <vm_name>' connects seamlessly.
    """
    db = load_db()
    lines = []
    
    # Read existing config file if present, excluding our managed block
    if SSH_CONFIG_FILE.exists():
        with open(SSH_CONFIG_FILE, "r") as f:
            content = f.read()
            # Clip old managed block
            if "# --- DISTROVM START ---" in content:
                before = content.split("# --- DISTROVM START ---")[0]
                after = content.split("# --- DISTROVM END ---")[-1]
                lines.append(before.strip())
                lines.append(after.strip())
            else:
                lines.append(content.strip())
    
    # Generate new managed block
    managed_block = ["\n# --- DISTROVM START ---"]
    for name, inst in db["instances"].items():
        # Check if the process is actually running before listing, otherwise we can still
        # write the configuration entries so terminal IDE handles bookmarks neatly.
        managed_block.append(f"Host {name}")
        managed_block.append("    HostName 127.0.0.1")
        managed_block.append(f"    Port {inst['ssh_port']}")
        managed_block.append(f"    User {inst['ssh_user']}")
        managed_block.append("    ForwardAgent yes")
        managed_block.append("    StrictHostKeyChecking no")
        managed_block.append("    UserKnownHostsFile /dev/null")
        managed_block.append("    LogLevel ERROR")
        managed_block.append("")
    managed_block.append("# --- DISTROVM END ---")
    
    # Combine
    final_content = (lines[0] + "\n" + "\n".join(managed_block) + "\n" + (lines[1] if len(lines) > 1 else "")).strip()
    
    with open(SSH_CONFIG_FILE, "w") as f:
        f.write(final_content + "\n")


def start_workspace(args):
    """Launches a workspace instance as a background process and updates host-level discoverability."""
    db = load_db()
    name = args.name

    if name not in db["instances"]:
        print(f"[-] Error: Workspace '{name}' not found.", file=sys.stderr)
        sys.exit(1)

    inst = db["instances"][name]
    pid = inst.get("pid")
    
    if pid:
        try:
            os.kill(pid, 0)
            print(f"[*] Workspace '{name}' is already running (PID: {pid}).")
            return
        except OSError:
            pass

    qemu_bin = get_qemu_executable(inst["arch"])
    accel = get_acceleration_flags(inst["arch"])

    boot_cmd = [
        qemu_bin,
        "-m", str(inst["ram"]),
        "-smp", str(inst["cpus"]),
        "-drive", f"file={inst['disk_path']},if=virtio",
        "-net", "nic,model=virtio",
        "-net", f"user,hostfwd=tcp::{inst['ssh_port']}-:22",
        "-nographic"
    ]
    boot_cmd.extend(accel)

    print(f"[*] Starting VM Workspace '{name}' in background...")
    try:
        if platform.system().lower() == "windows":
            process = subprocess.Popen(boot_cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)
        else:
            process = subprocess.Popen(boot_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setpgrp, close_fds=True)
        
        inst["pid"] = process.pid
        db["instances"][name] = inst
        save_db(db)
        
        # Synchronize Host SSH Configuration file with current VM mappings
        update_ssh_config()
        
        print(f"[+] Workspace successfully booted (PID: {process.pid})!")
        print(f"[+] You can now connect to this environment from your client terminal using:")
        print(f"    >>> ssh {name}")
        
    except Exception as e:
        print(f"[-] Failed to execute VM launch: {e}", file=sys.stderr)


def stop_workspace(args):
    """Gracefully kills the VM background worker process."""
    db = load_db()
    name = args.name

    if name not in db["instances"]:
        print(f"[-] Error: Workspace '{name}' not found.", file=sys.stderr)
        sys.exit(1)

    inst = db["instances"][name]
    pid = inst.get("pid")

    if not pid:
        print(f"[*] Workspace '{name}' is already stopped.")
        return

    print(f"[*] Terminating guest process '{name}' (PID: {pid})...")
    try:
        if platform.system().lower() == "windows":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, 15)  # SIGTERM
            
        inst["pid"] = None
        db["instances"][name] = inst
        save_db(db)
        print("[+] Workspace VM stopped.")
    except OSError:
        print("[!] Guest VM process was not active. Resetting state.")
        inst["pid"] = None
        db["instances"][name] = inst
        save_db(db)


def list_vms(args):
    """Discovers templates and tracks running overlay sandbox processes."""
    db = load_db()
    
    print("\n=== BASE COMPILED TOOLCHAINS (Read-Only) ===")
    if not db["bases"]:
        print("  No compiled templates. Run 'compile-base' to create customized toolchains.")
    else:
        for name, info in db["bases"].items():
            print(f"  • {name:<18} | Arch: {info['arch']:<8} | Active Recipes: {', '.join(info['tools'])}")

    print("\n=== RUNNING DEVELOPER WORKSPACES ===")
    if not db["instances"]:
        print("  No instances defined. Create a workspace overlay utilizing 'create'.")
    else:
        # Validate runtimes
        for name, inst in db["instances"].items():
            status = "Stopped"
            pid = inst.get("pid")
            if pid:
                try:
                    os.kill(pid, 0)
                    status = f"RUNNING (PID: {pid})"
                except OSError:
                    inst["pid"] = None
                    db["instances"][name] = inst
                    save_db(db)
            
            print(f"  • {name:<18} [ {status} ]")
            print(f"    Base Link: {inst['base']} | Port Forward: localhost:{inst['ssh_port']} -> guest:22")
            print(f"    Access Key: ssh {name}")
            print("-" * 55)


def destroy_workspace(args):
    """Permanently deletes the workspace instance without touching the underlying read-only base."""
    db = load_db()
    name = args.name

    if name not in db["instances"]:
        print(f"[-] Error: Workspace '{name}' not found.", file=sys.stderr)
        sys.exit(1)

    inst = db["instances"][name]
    if inst.get("pid"):
        print(f"[-] Error: Stop the workspace VM '{name}' before attempting to destroy it.", file=sys.stderr)
        sys.exit(1)

    confirm = input(f"[?] Are you sure you want to permanently erase '{name}'? (y/N): ").strip().lower()
    if confirm == 'y':
        disk = Path(inst["disk_path"])
        if disk.exists():
            disk.unlink()
        del db["instances"][name]
        save_db(db)
        update_ssh_config()
        print(f"[+] Workspace overlay successfully destroyed.")


# --- Main Command Router ---
def main():
    parser = argparse.ArgumentParser(description="Distributed VM Orchestrator - Automated Copy-on-Write Sandbox Engine")
    subparsers = parser.add_subparsers(dest="command")

    # Command: host-setup
    subparsers.add_parser("host-setup", help="Verify and install host virtualization toolchains natively")

    # Command: list-recipes
    subparsers.add_parser("list-recipes", help="Display all supported tool installation recipes")

    # Command: compile-base
    comp_p = subparsers.add_parser("compile-base", help="Compile toolchains inside a template and freeze it as read-only")
    comp_p.add_argument("source", help="Path to clean starter OS seed image (.img/.qcow2)")
    comp_p.add_argument("-n", "--name", required=True, help="Unique name to assign to the completed template")
    comp_p.add_argument("-t", "--tools", nargs="+", help="Space separated tools to compile (e.g. rust node python uv postgresql)")
    comp_p.add_argument("-u", "--user", default="developer", help="Admin username within the seed image (default: developer)")
    comp_p.add_argument("-a", "--arch", choices=["x86_64", "aarch64"], help="Target architecture (default: Host CPU Architecture)")

    # Command: create
    create_p = subparsers.add_parser("create", help="Instantly spawn a writable workspace overlay")
    create_p.add_argument("-n", "--name", help="Name of your workspace (e.g., dev-project)")
    create_p.add_argument("-b", "--base", help="Name of the compiled template to use as base")
    create_p.add_argument("-r", "--ram", type=int, help="Memory size in MB (default: 4096)")
    create_p.add_argument("-c", "--cpus", type=int, help="Number of CPU cores (default: 4)")
    create_p.add_argument("-p", "--ssh-port", type=int, help="Custom host port mapping (default: auto-selected)")
    create_p.add_argument("-u", "--user", default="developer", help="Standard connection username (default: developer)")

    # Command: list
    subparsers.add_parser("list", help="Display templates and running instances")

    # Command: start
    start_p = subparsers.add_parser("start", help="Boot workspace in background and update host SSH aliases")
    start_p.add_argument("name", help="Workspace name")

    # Command: stop
    stop_p = subparsers.add_parser("stop", help="Shutdown a running workspace gracefully")
    stop_p.add_argument("name", help="Workspace name")

    # Command: destroy
    dest_p = subparsers.add_parser("destroy", help="Wipe out a workspace overlay disk permanently")
    dest_p.add_argument("name", help="Workspace name")

    args = parser.parse_args()

    if args.command == "host-setup":
        setup_host_environment(args)
    elif args.command == "list-recipes":
        list_recipes(args)
    elif args.command == "compile-base":
        compile_base_template(args)
    elif args.command == "create":
        create_workspace(args)
    elif args.command == "list":
        list_vms(args)
    elif args.command == "start":
        start_workspace(args)
    elif args.command == "stop":
        stop_workspace(args)
    elif args.command == "destroy":
        destroy_workspace(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
