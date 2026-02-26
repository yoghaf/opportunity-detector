import os
import sys

# Windows Unicode fix for stdout
if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

import time
import socket
import subprocess
# import psutil # Moved to function to allow auto-install
import webbrowser
from threading import Timer

PORT = 8001
RELOAD = True

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def kill_process_on_port(port):
    """Find and kill process listening on specific port"""
    import psutil # Lazy import
    print(f"🔍 Checking port {port}...")
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            # Check connections
            for conn in proc.net_connections(kind='inet'):
                if conn.laddr.port == port:
                    print(f"🛑 Killing existing process {proc.info['name']} (PID: {proc.info['pid']})...")
                    proc.kill()
                    try:
                        proc.wait(timeout=3)
                    except psutil.TimeoutExpired:
                         pass
                    return True
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False

def run_server():
    """Run uvicorn server with auto-reload"""
    # 1. Kill valid port hoggers
    if is_port_in_use(PORT):
        kill_process_on_port(PORT)
    
    # Check again
    if is_port_in_use(PORT):
         print(f"⚠️ Port {PORT} is still in use! Please verify manually.")
         # Try 8002? 
         # PORT = 8002
    
    cmd = [
        sys.executable, "-m", "uvicorn", 
        "src.api.server:app",
        "--host", "0.0.0.0",
        "--port", str(PORT),
    ]
    
    if RELOAD:
        cmd.append("--reload")
        
    print(f"🚀 Starting Server on http://localhost:{PORT}")
    print("✨ Press Ctrl+C to stop.")
    
    try:
        # Use Popen to allow proper signal handling
        proc = subprocess.Popen(cmd)
        proc.wait()
    except KeyboardInterrupt:
        print("\n👋 Stopping server...")
        if proc:
            # Force kill the process tree to ensure all threads/subprocesses die
            # /T = Tree (child processes), /F = Force
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            
        print("✅ Done.")

if __name__ == "__main__":
    # Ensure dependencies
    try:
        import uvicorn
        import psutil
    except ImportError:
        print("📦 Installing dev dependencies (psutil)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "psutil", "uvicorn"])
        
    run_server()
