#!/usr/bin/env python3
"""
Cisco Telnet Connection Handler
Basis-Klasse für alle Cisco 2900XL Module (kein SSH auf altem IOS)

Getestet mit:
  - WS-C2924C-XL-EN
  - IOS 12.0(5.2)XU
"""

# Suppress deprecation warning BEFORE importing telnetlib
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning, module='telnetlib')

import telnetlib
import time
import re


class CiscoTelnetConnection:
    """
    Telnet-Verbindung zu Cisco Catalyst 2900 XL Switches.
    
    Usage:
        with CiscoTelnetConnection(
            host="10.0.20.1",
            password="neinnein",
            enable_password="neinnein"
        ) as conn:
            conn.enable()
            print(conn.execute("show vlan"))
    """
    
    def __init__(self, host, password, enable_password=None, 
                 port=23, timeout=30):
        """
        Args:
            host: Switch IP-Adresse
            password: Telnet/VTY Password
            enable_password: Enable Secret (default: gleich wie password)
            port: Telnet Port (default: 23)
            timeout: Verbindungs-Timeout in Sekunden
        """
        self.host = host
        self.password = password
        self.enable_password = enable_password or password
        self.port = port
        self.timeout = timeout
        self.tn = None
        self.hostname = None
        self.in_enable_mode = False
        self.in_config_mode = False
    
    def connect(self):
        """Telnet-Verbindung aufbauen und einloggen"""
        self.tn = telnetlib.Telnet(self.host, self.port, self.timeout)
        
        # Warten auf Password-Prompt
        self.tn.read_until(b"Password:", timeout=self.timeout)
        
        # Password senden
        self.tn.write(self.password.encode('ascii') + b"\n")
        
        # Warten auf User-Mode Prompt (hostname>)
        output = self.tn.read_until(b">", timeout=self.timeout).decode('utf-8', errors='ignore')
        
        # Hostname extrahieren
        match = re.search(r'(\S+)>', output)
        if match:
            self.hostname = match.group(1)
        
        return True
    
    def enable(self):
        """In den privilegierten EXEC-Modus wechseln"""
        if self.in_enable_mode:
            return
        
        self.tn.write(b"enable\n")
        
        # Warten auf Password-Prompt
        self.tn.read_until(b"Password:", timeout=5)
        
        # Enable Password senden
        self.tn.write(self.enable_password.encode('ascii') + b"\n")
        
        # Warten auf Privileged Prompt (hostname#)
        self.tn.read_until(b"#", timeout=5)
        
        self.in_enable_mode = True
        
        # Terminal length auf 0 setzen (kein --More-- Paging)
        self.execute("terminal length 0")
    
    def configure(self):
        """In den Konfigurationsmodus wechseln"""
        if self.in_config_mode:
            return
        
        if not self.in_enable_mode:
            self.enable()
        
        self.tn.write(b"configure terminal\n")
        
        # IOS fragt: "Configuring from terminal, memory, or network [terminal]?"
        # Wir warten kurz und prüfen ob die Frage kommt
        time.sleep(0.5)
        output = self._read_available()
        
        if "[terminal]" in output:
            # Mit Enter bestätigen
            self.tn.write(b"\n")
            time.sleep(0.3)
            self._read_available()
        
        # Warten auf Config-Prompt
        self.tn.read_until(b"(config)#", timeout=5)
        self.in_config_mode = True
    
    def exit_configure(self):
        """Konfigurationsmodus verlassen"""
        if not self.in_config_mode:
            return
        
        self.tn.write(b"end\n")
        self.tn.read_until(b"#", timeout=5)
        self.in_config_mode = False
    
    def save_config(self):
        """Konfiguration in NVRAM speichern"""
        if self.in_config_mode:
            self.exit_configure()
        
        self.tn.write(b"write memory\n")
        
        # Warten auf "Building configuration..." und dann Prompt
        time.sleep(2)
        output = self.tn.read_until(b"#", timeout=30).decode('utf-8', errors='ignore')
        
        return "Building" in output or "[OK]" in output
    
    def execute(self, command, wait=0.5):
        """
        Befehl ausführen und Output zurückgeben.
        
        Args:
            command: IOS-Befehl
            wait: Wartezeit nach Befehl in Sekunden
            
        Returns:
            Command output as string
        """
        self.tn.write(command.encode('ascii') + b"\n")
        time.sleep(wait)
        
        # Auf Prompt warten (# oder (config)# etc.)
        if self.in_config_mode:
            output = self.tn.read_until(b"#", timeout=10)
        else:
            output = self.tn.read_until(b"#", timeout=10)
        
        return output.decode('utf-8', errors='ignore')
    
    def execute_config_commands(self, commands):
        """
        Mehrere Konfigurations-Befehle ausführen.
        
        Args:
            commands: Liste von IOS-Befehlen
            
        Returns:
            Combined output
        """
        output = ""
        self.configure()
        
        for cmd in commands:
            output += self.execute(cmd)
        
        self.exit_configure()
        return output
    
    def _read_available(self):
        """Alle verfügbaren Daten lesen ohne zu blockieren"""
        output = b""
        try:
            while True:
                chunk = self.tn.read_very_eager()
                if not chunk:
                    break
                output += chunk
        except:
            pass
        return output.decode('utf-8', errors='ignore')
    
    def get_running_config(self):
        """Running-Config auslesen"""
        return self.execute("show running-config", wait=2)
    
    def get_vlans(self):
        """
        VLANs auslesen und als Dictionary zurückgeben.
        
        Returns:
            {vlan_id: {"name": name, "status": status, "ports": [...]}}
        """
        output = self.execute("show vlan", wait=1)
        vlans = {}
        
        current_vlan = None
        
        for line in output.split('\n'):
            # Match VLAN-Zeilen: "1    default                          active    Fa0/1, Fa0/2"
            match = re.match(r'^(\d+)\s+(\S+)\s+(active|suspend|act/unsup)\s*(.*)', line)
            if match:
                vlan_id = int(match.group(1))
                vlan_name = match.group(2)
                vlan_status = match.group(3)
                ports_part = match.group(4).strip()
                
                ports = [p.strip() for p in ports_part.split(',') if p.strip()]
                
                vlans[vlan_id] = {
                    "name": vlan_name,
                    "status": vlan_status,
                    "ports": ports
                }
                current_vlan = vlan_id
            
            # Fortsetzungszeilen für Ports (eingerückt)
            elif current_vlan and line.startswith(' ' * 40):
                ports_part = line.strip()
                if ports_part and not ports_part.startswith('VLAN'):
                    ports = [p.strip() for p in ports_part.split(',') if p.strip()]
                    vlans[current_vlan]["ports"].extend(ports)
        
        return vlans
    
    def get_interfaces_status(self):
        """
        Interface-Status auslesen.
        
        Returns:
            {"Fa0/1": {"status": "connected", "vlan": "1", ...}}
        """
        output = self.execute("show interfaces status", wait=1)
        interfaces = {}
        
        for line in output.split('\n'):
            # Format: Port    Name         Status       Vlan  Duplex Speed Type
            match = re.match(
                r'^(Fa\d+/\d+)\s+(\S*)\s+(connected|notconnect|disabled)\s+'
                r'(\d+|trunk)\s+(\S+)\s+(\S+)',
                line
            )
            if match:
                port = match.group(1)
                interfaces[port] = {
                    "name": match.group(2) or "",
                    "status": match.group(3),
                    "vlan": match.group(4),
                    "duplex": match.group(5),
                    "speed": match.group(6)
                }
        
        return interfaces
    
    def disconnect(self):
        """Verbindung trennen"""
        if self.tn:
            try:
                self.tn.write(b"exit\n")
                time.sleep(0.3)
            except:
                pass
            finally:
                self.tn.close()
                self.tn = None
    
    @staticmethod
    def port_to_interface(port_num):
        """
        Konvertiert Port-Nummer zu Cisco Interface-Namen.
        
        Args:
            port_num: Port-Nummer (1-24) oder bereits Interface-Name
            
        Returns:
            Interface-Name (z.B. "FastEthernet0/1")
        """
        # Falls bereits ein Interface-Name
        if isinstance(port_num, str) and port_num.startswith(('Fa', 'Gi', 'VLAN')):
            return port_num
        
        # Port-Nummer zu Interface
        port = int(port_num)
        if 1 <= port <= 24:
            return f"FastEthernet0/{port}"
        else:
            raise ValueError(f"Invalid port number: {port}. Must be 1-24.")
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()


# =============================================================================
# Standalone Test
# =============================================================================
if __name__ == "__main__":
    import sys
    
    # Test mit Kommandozeilen-Argumenten oder Defaults
    host = sys.argv[1] if len(sys.argv) > 1 else "10.0.20.1"
    password = sys.argv[2] if len(sys.argv) > 2 else "neinnein"
    
    print(f"Connecting to {host}...")
    sys.stdout.flush()
    
    conn = None
    try:
        conn = CiscoTelnetConnection(host, password)
        print("1. Created connection object")
        sys.stdout.flush()
        
        conn.connect()
        print(f"2. Connected to {conn.hostname}")
        sys.stdout.flush()
        
        conn.enable()
        print("3. Enabled")
        sys.stdout.flush()
        
        print("\n--- VLANs ---")
        vlans = conn.get_vlans()
        for vid, vdata in sorted(vlans.items()):
            if vid < 1002:  # Skip system VLANs
                print(f"  VLAN {vid}: {vdata['name']} ({vdata['status']})")
                if vdata['ports']:
                    print(f"    Ports: {', '.join(vdata['ports'][:5])}...")
        
        print("\n--- Interface Status (first 5) ---")
        interfaces = conn.get_interfaces_status()
        for port, data in list(interfaces.items())[:5]:
            print(f"  {port}: {data['status']} VLAN={data['vlan']}")
        
        print("\n✓ Test completed successfully!")
        
    except Exception as e:
        print(f"✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if conn:
            conn.disconnect()
