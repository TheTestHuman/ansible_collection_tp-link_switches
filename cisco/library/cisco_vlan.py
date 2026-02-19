#!/usr/bin/env python3
"""
Cisco VLAN Configuration Module (Combined)
- VLAN erstellen/löschen
- VLAN-Name setzen
- Ports zu VLANs zuweisen (Access/Trunk)

Getestet mit:
  - WS-C2924C-XL-EN
  - IOS 12.0(5.2)XU
"""

import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)

import telnetlib
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
        self.in_vlan_mode = False
        self.in_interface_mode = False
    
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
    
    def vlan_database(self):
        """In den VLAN-Datenbank-Modus wechseln (für alte IOS-Versionen)"""
        if not self.in_enable_mode:
            self.enable()
        if self.in_config_mode:
            self.exit_configure()
        self.tn.write(b"vlan database\n")
        time.sleep(1)
        self.tn.read_until(b"(vlan)#", timeout=10)
        self.in_vlan_mode = True
    
    def exit_vlan_database(self):
        """VLAN-Datenbank-Modus verlassen (wendet Änderungen automatisch an)"""
        if hasattr(self, 'in_vlan_mode') and self.in_vlan_mode:
            self.tn.write(b"exit\n")
            time.sleep(2)  # "APPLY completed" abwarten
            self.tn.read_until(b"#", timeout=10)
            self.in_vlan_mode = False
    
    def create_vlan(self, vlan_id, vlan_name=None):
        """VLAN erstellen im vlan database Modus"""
        if vlan_name:
            cmd = f"vlan {vlan_id} name {vlan_name}\n"
        else:
            cmd = f"vlan {vlan_id}\n"
        self.tn.write(cmd.encode('ascii'))
        time.sleep(1)
        output = self.tn.read_until(b"(vlan)#", timeout=10)
        return output.decode('utf-8', errors='ignore')
    
    def delete_vlan(self, vlan_id):
        """VLAN löschen im vlan database Modus"""
        cmd = f"no vlan {vlan_id}\n"
        self.tn.write(cmd.encode('ascii'))
        time.sleep(1)
        output = self.tn.read_until(b"(vlan)#", timeout=10)
        return output.decode('utf-8', errors='ignore')

    def configure(self):
        """In den Konfigurationsmodus wechseln"""
        if self.in_config_mode:
            return
        if self.in_vlan_mode:
            self.exit_vlan_database()
        if not self.in_enable_mode:
            self.enable()
        self.tn.write(b"configure terminal\n")
        time.sleep(1)
        output = self._read_available()
        if "[terminal]" in output:
            self.tn.write(b"\n")
            time.sleep(0.5)
        self.tn.read_until(b"#", timeout=10)
        self.in_config_mode = True
    
    def exit_configure(self):
        """Konfigurationsmodus verlassen"""
        if self.in_interface_mode:
            self.exit_interface()
        if not self.in_config_mode:
            return
        self.tn.write(b"end\n")
        time.sleep(1)
        self.tn.read_until(b"#", timeout=10)
        self.in_config_mode = False
    
    def interface(self, port_number):
        """In Interface-Konfigurationsmodus wechseln"""
        if not self.in_config_mode:
            self.configure()
        # Cisco C2924 verwendet FastEthernet 0/X
        cmd = f"interface FastEthernet 0/{port_number}\n"
        self.tn.write(cmd.encode('ascii'))
        time.sleep(0.5)
        self.tn.read_until(b"(config-if)#", timeout=10)
        self.in_interface_mode = True
    
    def exit_interface(self):
        """Interface-Modus verlassen"""
        if not self.in_interface_mode:
            return
        self.tn.write(b"exit\n")
        time.sleep(0.5)
        self.tn.read_until(b"(config)#", timeout=10)
        self.in_interface_mode = False
    
    def set_access_port(self, port_number, vlan_id):
        """Port als Access-Port konfigurieren"""
        self.interface(port_number)
        # Access Mode setzen
        self.tn.write(b"switchport mode access\n")
        time.sleep(0.3)
        self.tn.read_until(b"#", timeout=5)
        # VLAN zuweisen
        self.tn.write(f"switchport access vlan {vlan_id}\n".encode('ascii'))
        time.sleep(0.3)
        self.tn.read_until(b"#", timeout=5)
        self.exit_interface()
    
    def set_trunk_port(self, port_number, allowed_vlans=None, native_vlan=1):
        """Port als Trunk-Port konfigurieren"""
        self.interface(port_number)
        # Trunk Mode setzen
        self.tn.write(b"switchport mode trunk\n")
        time.sleep(0.3)
        self.tn.read_until(b"#", timeout=5)
        # Native VLAN setzen
        self.tn.write(f"switchport trunk native vlan {native_vlan}\n".encode('ascii'))
        time.sleep(0.3)
        self.tn.read_until(b"#", timeout=5)
        # Allowed VLANs setzen (falls angegeben)
        if allowed_vlans:
            vlan_list = ','.join(str(v) for v in allowed_vlans)
            self.tn.write(f"switchport trunk allowed vlan {vlan_list}\n".encode('ascii'))
            time.sleep(0.3)
            self.tn.read_until(b"#", timeout=5)
        self.exit_interface()
    
    def save_config(self):
        """Konfiguration in NVRAM speichern"""
        if self.in_interface_mode:
            self.exit_interface()
        if self.in_config_mode:
            self.exit_configure()
        self.tn.write(b"write memory\n")
        time.sleep(3)
        try:
            output = self.tn.read_until(b"#", timeout=60).decode('utf-8', errors='ignore')
            return "Building" in output or "[OK]" in output
        except:
            return True
    
    def execute(self, command, wait=1.0):
        """Befehl ausführen und Output zurückgeben"""
        self.tn.write(command.encode('ascii') + b"\n")
        time.sleep(wait)
        try:
            output = self.tn.read_until(b"#", timeout=15)
            return output.decode('utf-8', errors='ignore')
        except:
            return ""
    
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
    
    def get_vlans(self):
        """VLANs auslesen und als Dictionary zurückgeben"""
        if self.in_config_mode:
            self.exit_configure()
        output = self.execute("show vlan", wait=1)
        vlans = {}
        current_vlan = None
        
        for line in output.split('\n'):
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
            elif current_vlan and line.startswith(' ' * 40):
                ports_part = line.strip()
                if ports_part and not ports_part.startswith('VLAN'):
                    ports = [p.strip() for p in ports_part.split(',') if p.strip()]
                    vlans[current_vlan]["ports"].extend(ports)
        
        return vlans
    
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
module: cisco_vlan
short_description: Manage VLANs on Cisco Catalyst C2924
description:
    - Create, delete, and configure VLANs
    - Set VLAN names
    - Assign ports to VLANs (access/trunk)
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
    vlans:
        description: List of VLANs to configure
        required: true
        type: list
        suboptions:
            vlan_id:
                description: VLAN ID (1-1001)
                required: true
            name:
                description: VLAN name
                required: true
            tagged_ports:
                description: Ports as trunk (tagged)
                type: list
            untagged_ports:
                description: Ports as access (untagged)
                type: list
    state:
        description: Desired state
        choices: ['present', 'absent']
        default: present
'''

EXAMPLES = '''
- name: Create VLANs with port assignments
  cisco_vlan:
    host: 10.0.20.1
    password: "{{ vault_password }}"
    vlans:
      - vlan_id: 10
        name: Management
        tagged_ports: [1]
        untagged_ports: [2]
      - vlan_id: 20
        name: Clients
        tagged_ports: [1]
        untagged_ports: [3, 4, 5, 6, 7, 8]
    state: present
'''


# =============================================================================
# HILFSFUNKTIONEN
# =============================================================================

def get_existing_vlans(conn):
    """Aktuelle VLANs vom Switch auslesen"""
    vlans = conn.get_vlans()
    return {vid: vdata['name'] for vid, vdata in vlans.items()}


# =============================================================================
# HAUPTMODUL
# =============================================================================

def run_module():
    module_args = dict(
        host=dict(type='str', required=True),
        password=dict(type='str', required=True, no_log=True),
        enable_password=dict(type='str', required=False, no_log=True),
        vlans=dict(type='list', required=True, elements='dict'),
        state=dict(type='str', default='present', choices=['present', 'absent']),
    )
    
    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)
    
    result = dict(
        changed=False,
        message='',
        vlans_created=[],
        vlans_deleted=[],
        vlans_updated=[],
        vlans_existing=[],
        ports_configured=[],
    )
    
    host = module.params['host']
    password = module.params['password']
    enable_password = module.params.get('enable_password') or password
    vlans = module.params['vlans']
    state = module.params['state']
    
    try:
        with CiscoTelnetConnection(
            host=host,
            password=password,
            enable_password=enable_password
        ) as conn:
            conn.enable()
            
            # Aktuelle VLANs auslesen
            existing = get_existing_vlans(conn)
            result['vlans_existing'] = list(existing.keys())
            
            # Check mode - nur prüfen, nicht ändern
            if module.check_mode:
                for vlan in vlans:
                    vlan_id = int(vlan.get('vlan_id', vlan.get('id', 0)))
                    if state == 'present' and vlan_id not in existing:
                        result['vlans_created'].append(vlan_id)
                        result['changed'] = True
                    elif state == 'absent' and vlan_id in existing:
                        result['vlans_deleted'].append(vlan_id)
                        result['changed'] = True
                module.exit_json(**result)
            
            # ===== PHASE 1: VLANs erstellen/löschen =====
            # In VLAN Database Modus wechseln (für alte IOS-Versionen!)
            conn.vlan_database()
            
            for vlan in vlans:
                # Unterstütze beide Formate: vlan_id (TP-Link Style) und id (alt)
                vlan_id = int(vlan.get('vlan_id', vlan.get('id', 0)))
                vlan_name = vlan.get('name', f'VLAN{vlan_id:04d}')
                
                # Validierung
                if vlan_id < 1 or vlan_id > 1001:
                    conn.exit_vlan_database()
                    module.fail_json(
                        msg=f"ERROR_INVALID_VLAN_ID: {vlan_id} (must be 1-1001)",
                        **result
                    )
                
                if state == 'present':
                    if vlan_id not in existing:
                        # VLAN erstellen
                        conn.create_vlan(vlan_id, vlan_name)
                        result['vlans_created'].append(vlan_id)
                        result['changed'] = True
                    elif existing.get(vlan_id) != vlan_name:
                        # VLAN existiert, aber Name ist anders - aktualisieren
                        conn.create_vlan(vlan_id, vlan_name)
                        result['vlans_updated'].append(vlan_id)
                        result['changed'] = True
                        
                elif state == 'absent':
                    if vlan_id in existing:
                        if vlan_id == 1:
                            conn.exit_vlan_database()
                            module.fail_json(
                                msg="ERROR_CANNOT_DELETE_VLAN1: Default VLAN 1 cannot be deleted",
                                **result
                            )
                        conn.delete_vlan(vlan_id)
                        result['vlans_deleted'].append(vlan_id)
                        result['changed'] = True
            
            # VLAN Database Modus verlassen
            conn.exit_vlan_database()
            
            # ===== PHASE 2: Ports zu VLANs zuweisen =====
            if state == 'present':
                # Sammle alle Trunk-Ports und ihre VLANs
                trunk_ports = {}  # {port: [vlan_ids]}
                
                for vlan in vlans:
                    vlan_id = int(vlan.get('vlan_id', vlan.get('id', 0)))
                    tagged_ports = vlan.get('tagged_ports', []) or []
                    untagged_ports = vlan.get('untagged_ports', []) or []
                    
                    # Tagged Ports = Trunk Ports
                    for port in tagged_ports:
                        if port not in trunk_ports:
                            trunk_ports[port] = []
                        trunk_ports[port].append(vlan_id)
                    
                    # Untagged Ports = Access Ports
                    for port in untagged_ports:
                        conn.set_access_port(port, vlan_id)
                        result['ports_configured'].append(f"Fa0/{port} -> VLAN {vlan_id} (access)")
                        result['changed'] = True
                
                # Trunk Ports konfigurieren
                for port, vlan_list in trunk_ports.items():
                    # Native VLAN = 1, allowed VLANs = alle gesammelten
                    all_vlans = sorted(set([1] + vlan_list))
                    conn.set_trunk_port(port, allowed_vlans=all_vlans, native_vlan=1)
                    result['ports_configured'].append(f"Fa0/{port} -> Trunk (VLANs: {','.join(map(str, all_vlans))})")
                    result['changed'] = True
            
            # Konfiguration speichern
            if result['changed']:
                conn.save_config()
            
            result['message'] = 'SUCCESS_VLAN_CONFIGURED'
            
    except Exception as e:
        module.fail_json(msg=f'ERROR_VLAN_FAILED: {str(e)}', **result)
    
    module.exit_json(**result)


if __name__ == '__main__':
    run_module()
