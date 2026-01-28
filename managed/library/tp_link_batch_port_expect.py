#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
TP-Link SG3210 Batch Port Configuration Module

Konfiguriert Ports auf TP-Link SG3210 Managed Switches via expect.

Parameter:
    host: Switch IP-Adresse
    username: SSH Username
    password: SSH Passwort
    hostname: CLI Prompt Hostname (default: SG3210)
    mode: "replace" oder "add" (default: add)
        - replace: Entfernt alle VLANs vom Port, dann konfiguriert neu
        - add: Fügt VLANs nur hinzu (keine Löschung)
    trunk_ports: Liste von Trunk-Port-Konfigurationen
        - port: Port-Nummer (1-10)
        - vlans: Liste von VLAN-IDs (alle tagged)
    access_ports: Liste von Access-Port-Konfigurationen
        - port: Port-Nummer (1-10)
        - vlan: VLAN-ID (untagged + PVID)

Beispiel:
    - tp_link_batch_port_expect:
        host: "10.0.10.1"
        username: "admin"
        password: "secret"
        mode: "replace"
        trunk_ports:
          - port: 1
            vlans: [1, 10, 20, 30, 40]
        access_ports:
          - port: 2
            vlan: 10
          - port: 3
            vlan: 20
"""

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os


def create_batch_port_script(host, username, password, hostname, mode, trunk_ports, access_ports):
    """Generate expect script for BATCH port configuration"""
    
    port_commands = ""
    
    # Trunk Ports konfigurieren
    for trunk in trunk_ports:
        port_num = trunk['port']
        vlans = trunk.get('vlans', [])
        
        port_commands += f'''
# === TRUNK PORT {port_num} ===
send "interface gigabitEthernet 1/0/{port_num}\\r"
expect "{hostname}(config-if)#"
'''
        
        # Bei replace: Erst alle VLANs entfernen
        if mode == "replace":
            port_commands += f'''send "no switchport general allowed vlan all\\r"
expect "{hostname}(config-if)#"
'''
        
        # VLANs als tagged hinzufügen
        for vlan_id in vlans:
            port_commands += f'''send "switchport general allowed vlan {vlan_id} tagged\\r"
expect "{hostname}(config-if)#"
'''
        
        # PVID auf VLAN 1 setzen (Standard für Trunk)
        port_commands += f'''send "switchport pvid 1\\r"
expect "{hostname}(config-if)#"
send "exit\\r"
expect "{hostname}(config)#"
'''
    
    # Access Ports konfigurieren
    for access in access_ports:
        port_num = access['port']
        vlan_id = access.get('vlan', 1)
        
        port_commands += f'''
# === ACCESS PORT {port_num} (VLAN {vlan_id}) ===
send "interface gigabitEthernet 1/0/{port_num}\\r"
expect "{hostname}(config-if)#"
'''
        
        # Bei replace: Erst alle VLANs entfernen
        if mode == "replace":
            port_commands += f'''send "no switchport general allowed vlan all\\r"
expect "{hostname}(config-if)#"
'''
        
        # VLAN als untagged hinzufügen + PVID setzen
        port_commands += f'''send "switchport general allowed vlan {vlan_id} untagged\\r"
expect "{hostname}(config-if)#"
send "switchport pvid {vlan_id}\\r"
expect "{hostname}(config-if)#"
send "exit\\r"
expect "{hostname}(config)#"
'''
    
    script = f'''#!/usr/bin/expect -f
set timeout 60
log_user 1

spawn ssh -o StrictHostKeyChecking=no -o PubkeyAuthentication=no {username}@{host}

expect "password:"
send "{password}\\r"

expect "{hostname}>"
send "enable\\r"

expect "{hostname}#"
send "configure\\r"

expect "{hostname}(config)#"

# === PORT CONFIGURATION ===
{port_commands}

# === SAVE CONFIG ===
send "exit\\r"
expect "{hostname}#"
send "copy running-config startup-config\\r"

expect {{
    "Saving user config OK!" {{}}
    "Succeed" {{}}
    timeout {{
        puts "TIMEOUT_SAVE"
    }}
}}

send "exit\\r"
expect "{hostname}>"
send "exit\\r"
expect eof
'''
    return script


def main():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type='str', required=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            hostname=dict(type='str', required=False, default='SG3210'),
            mode=dict(type='str', required=False, default='add', choices=['add', 'replace']),
            trunk_ports=dict(type='list', required=False, default=[], elements='dict'),
            access_ports=dict(type='list', required=False, default=[], elements='dict'),
        ),
        supports_check_mode=False
    )
    
    host = module.params['host']
    username = module.params['username']
    password = module.params['password']
    hostname = module.params['hostname']
    mode = module.params['mode']
    trunk_ports = module.params['trunk_ports']
    access_ports = module.params['access_ports']
    
    # Validierung
    if not trunk_ports and not access_ports:
        module.fail_json(msg="At least one of trunk_ports or access_ports must be specified")
    
    script = create_batch_port_script(
        host, username, password, hostname, mode, trunk_ports, access_ports
    )
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.exp', delete=False) as f:
        f.write(script)
        script_path = f.name
    
    try:
        os.chmod(script_path, 0o700)
        result = subprocess.run([script_path], capture_output=True, text=True, timeout=180)
        os.unlink(script_path)
        
        # Zähle Operationen
        trunk_count = len(trunk_ports)
        access_count = len(access_ports)
        
        # Prüfe auf Fehler im Output
        if "TIMEOUT" in result.stdout:
            module.fail_json(
                msg="Timeout während der Port-Konfiguration",
                stdout=result.stdout,
                stderr=result.stderr
            )
        
        module.exit_json(
            changed=True,
            msg=f"Mode '{mode}': Configured {trunk_count} trunk ports, {access_count} access ports",
            mode=mode,
            trunk_ports_configured=trunk_count,
            access_ports_configured=access_count,
            stdout=result.stdout
        )
        
    except subprocess.TimeoutExpired:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg="Command timed out after 180 seconds")
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg=str(e))


if __name__ == '__main__':
    main()
