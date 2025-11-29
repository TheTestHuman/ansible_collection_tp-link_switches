#!/usr/bin/env python3
import telnetlib
import time

host = "192.168.0.1"
username = "admin"
password = "neinnein"

try:
    print(f"Connecting to {host}...")
    tn = telnetlib.Telnet(host, timeout=10)
    
    print("Waiting for username prompt...")
    tn.read_until(b"User:", timeout=5)
    print("✓ Got username prompt")
    
    print("Sending username...")
    tn.write(username.encode('ascii') + b"\n")
    
    print("Waiting for password prompt...")
    tn.read_until(b"Password:", timeout=5)
    print("✓ Got password prompt")
    
    print("Sending password...")
    tn.write(password.encode('ascii') + b"\n")
    
    print("Waiting for prompt...")
    tn.read_until(b">", timeout=5)
    print("✓ Got prompt!")
    
    # Jetzt nochmal alles lesen
    time.sleep(0.5)
    output = tn.read_very_eager().decode('ascii')
    print(f"Prompt check: {repr(output)}")
    
    print("\n✓ LOGIN SUCCESSFUL!")
    
    # Test enable
    print("\nSending 'enable'...")
    tn.write(b"enable\n")
    time.sleep(1)
    output = tn.read_very_eager().decode('ascii')
    print(f"After enable:\n{output}")
    
    tn.close()
    
except Exception as e:
    print(f"\n✗ ERROR: {e}")
