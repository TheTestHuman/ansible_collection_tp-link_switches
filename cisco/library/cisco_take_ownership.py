#!/usr/bin/env python3
"""
Cisco Take-Ownership (Combined Module)
- Prüft Telnet-Erreichbarkeit
- Informiert über Konsolen-Pflicht falls nicht erreichbar
- Liest Hardware-Infos aus
- Registriert Switch im Inventory

Getestet mit:
  - WS-C2924C-XL-EN
  - IOS 12.0(5.2)XU
"""

import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)

import telnetlib
import socket
import time
import re

from ansible.module_utils.basic import AnsibleModule


# =============================================================================
# EINGEBETTETE TELNET-KLASSE
# =============================================================================

class CiscoTelnetConnection:
    """Telnet-Verbindung zu Cisco Catalyst C2924 Switches."""
    
    def __init__(self, host, password, enable_password=None, port=23, timeout=30):
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
        self.tn.read_until(b"Password:", timeout=self.timeout)
        self.tn.write(self.password.encode('ascii') + b"\n")
        output = self.tn.read_until(b">", timeout=self.timeout).decode('utf-8', errors='ignore')
        match = re.search(r'(\S+)>', output)
        if match:
            self.hostname = match.group(1)
        return True
    
    def enable(self):
        """In den privilegierten EXEC-Modus wechseln"""
        if self.in_enable_mode:
            return
        self.tn.write(b"enable\n")
        self.tn.read_until(b"Password:", timeout=5)
        self.tn.write(self.enable_password.encode('ascii') + b"\n")
        self.tn.read_until(b"#", timeout=5)
        self.in_enable_mode = True
        self.execute("terminal length 0")
    
    def execute(self, command, wait=0.5):
        """Befehl ausführen und Output zurückgeben"""
        self.tn.write(command.encode('ascii') + b"\n")
        time.sleep(wait)
        output = self.tn.read_until(b"#", timeout=10)
        return output.decode('utf-8', errors='ignore')
    
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
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()


# =============================================================================
# MODUL-DOKUMENTATION
# =============================================================================

DOCUMENTATION = '''
---
module: cisco_take_ownership
short_description: Take ownership of Cisco Catalyst C2924
description:
    - Checks if switch is reachable via Telnet
    - Informs user if console setup is required
    - Reads hardware info from switch
    - Registers switch in inventory
options:
    host:
        description: Switch IP address
        required: true
    password:
        description: Telnet/VTY password
        required: true
    enable_password:
        description: Enable secret (defaults to password)
        required: false
    switch_suffix:
        description: Suffix for inventory name (e.g. lab, office)
        required: true
    switch_location:
        description: Physical location of the switch
        required: false
        default: "Unknown"
'''

EXAMPLES = '''
- name: Take ownership of Cisco switch
  cisco_take_ownership:
    host: 10.0.20.1
    password: "{{ vault_cisco_password }}"
    switch_suffix: "lab"
    switch_location: "Server Room"
'''

CONSOLE_SETUP_MSG = '''
================================================================================
KONSOLEN-KONFIGURATION ERFORDERLICH!
================================================================================

Der Cisco C2924 Switch ist unter {host} nicht per Telnet erreichbar.

Im Gegensatz zu TP-Link Switches hat der Cisco C2924 im Werkszustand
KEINE IP-Adresse und ist nur über die serielle Konsole erreichbar.

Bitte führe folgende Schritte manuell über Konsole durch:

1. Konsolenkabel anschließen (RJ45-to-DB9 oder USB-Adapter)
2. Terminal öffnen (PuTTY/minicom, 9600 8N1)
3. Folgende Befehle eingeben:

   enable
   configure terminal
   hostname {hostname}
   enable secret YOUR_PASSWORD
   line vty 0 4
    password YOUR_PASSWORD
    login
    exit
   interface vlan 1
    ip address {host} 255.255.255.0
    no shutdown
    exit
   end
   write memory

4. Danach dieses Playbook erneut ausführen.

================================================================================
'''


# =============================================================================
# HILFSFUNKTIONEN
# =============================================================================

def check_telnet_reachable(host, port=23, timeout=5):
    """Prüft ob Telnet-Port erreichbar ist"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except socket.error:
        return False


def parse_show_version(output):
    """Extrahiert Hardware-Infos aus 'show version' Output"""
    info = {
        'ios_version': None,
        'ios_image': None,
        'model': None,
        'serial_number': None,
        'mac_address': None,
        'uptime': None,
        'ram_kb': None,
    }
    
    match = re.search(r'Version (\S+),', output)
    if match:
        info['ios_version'] = match.group(1)
    
    match = re.search(r'System image file is "flash:(\S+)"', output)
    if match:
        info['ios_image'] = match.group(1)
    
    match = re.search(r'Model number:\s+(\S+)', output)
    if match:
        info['model'] = match.group(1)
    
    match = re.search(r'System serial number:\s+(\S+)', output)
    if match:
        info['serial_number'] = match.group(1)
    
    match = re.search(r'Base ethernet MAC Address:\s+(\S+)', output)
    if match:
        info['mac_address'] = match.group(1)
    
    match = re.search(r'uptime is (.+)', output)
    if match:
        info['uptime'] = match.group(1).strip()
    
    match = re.search(r'with (\d+)K/(\d+)K bytes', output)
    if match:
        info['ram_kb'] = int(match.group(1)) + int(match.group(2))
    
    return info


# =============================================================================
# HAUPTMODUL
# =============================================================================

def run_module():
    module_args = dict(
        host=dict(type='str', required=True),
        password=dict(type='str', required=True, no_log=True),
        enable_password=dict(type='str', required=False, no_log=True),
        switch_suffix=dict(type='str', required=True),
        switch_location=dict(type='str', required=False, default='Unknown'),
    )
    
    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)
    
    host = module.params['host']
    password = module.params['password']
    enable_password = module.params.get('enable_password') or password
    switch_suffix = module.params['switch_suffix']
    switch_location = module.params['switch_location']
    
    result = dict(
        changed=False,
        reachable=False,
        hardware_info={},
        inventory_name=f"c2924-{switch_suffix}",
        switch_location=switch_location,
        message='',
        console_setup_required=False,
    )
    
    # Schritt 1: Telnet-Erreichbarkeit prüfen
    if not check_telnet_reachable(host):
        result['console_setup_required'] = True
        result['message'] = CONSOLE_SETUP_MSG.format(
            host=host,
            hostname=f"CISCO-{switch_suffix.upper()}"
        )
        module.fail_json(
            msg=f"ERROR_CONSOLE_SETUP_REQUIRED: Switch {host} nicht per Telnet erreichbar. "
                f"Bitte zuerst Konsolen-Konfiguration durchführen.",
            **result
        )
    
    result['reachable'] = True
    
    # Schritt 2: Verbinden und Hardware-Infos auslesen
    try:
        with CiscoTelnetConnection(
            host=host,
            password=password,
            enable_password=enable_password
        ) as conn:
            conn.enable()
            
            # Show version auslesen
            version_output = conn.execute("show version", wait=2)
            result['hardware_info'] = parse_show_version(version_output)
            
            # Hostname speichern
            if conn.hostname:
                result['hardware_info']['hostname'] = conn.hostname
            
            result['changed'] = True
            result['message'] = 'SUCCESS_TAKE_OWNERSHIP_COMPLETE'
            
    except Exception as e:
        error_msg = str(e)
        
        if "Password" in error_msg or "Authentication" in error_msg or "Login" in error_msg:
            module.fail_json(
                msg=f"ERROR_AUTHENTICATION_FAILED: Falsches Passwort für {host}",
                **result
            )
        else:
            module.fail_json(
                msg=f"ERROR_CONNECTION_FAILED: {error_msg}",
                **result
            )
    
    module.exit_json(**result)


if __name__ == '__main__':
    run_module()
