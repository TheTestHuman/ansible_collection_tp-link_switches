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
    """Generate expect script for BATCH port configuration with error handling"""
    
    port_commands = ""
    
    # Trunk Ports konfigurieren
    for trunk in trunk_ports:
        port_num = trunk['port']
        vlans = trunk.get('vlans', [])
        
        port_commands += f'''
# === TRUNK PORT {port_num} ===
send "interface gigabitEthernet 1/0/{port_num}\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    timeout {{
        puts "ERROR_PORT_TIMEOUT: Timeout entering interface config for port {port_num}"
        exit 1
    }}
}}
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
expect {{
    "{hostname}(config-if)#" {{}}
    timeout {{
        puts "ERROR_PORT_TIMEOUT: Timeout entering interface config for port {port_num}"
        exit 1
    }}
}}
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
set timeout 30
log_user 1

# === CONNECTION PHASE ===
spawn ssh -o StrictHostKeyChecking=no -o PubkeyAuthentication=no -o ConnectTimeout=10 {username}@{host}

expect {{
    "No route to host" {{
        puts "ERROR_CONNECTION_FAILED: No route to host {host}"
        exit 1
    }}
    "Connection refused" {{
        puts "ERROR_CONNECTION_REFUSED: Connection refused by {host}"
        exit 1
    }}
    "Connection timed out" {{
        puts "ERROR_CONNECTION_TIMEOUT: Connection to {host} timed out"
        exit 1
    }}
    "Host is unreachable" {{
        puts "ERROR_HOST_UNREACHABLE: Host {host} is unreachable"
        exit 1
    }}
    "Name or service not known" {{
        puts "ERROR_DNS_FAILED: Could not resolve hostname {host}"
        exit 1
    }}
    "password:" {{
        send "{password}\\r"
    }}
    timeout {{
        puts "ERROR_CONNECTION_TIMEOUT: Timeout connecting to {host}"
        exit 1
    }}
}}

# === LOGIN PHASE ===
expect {{
    "Permission denied" {{
        puts "ERROR_AUTH_FAILED: Authentication failed - wrong username or password"
        exit 1
    }}
    "Access denied" {{
        puts "ERROR_AUTH_FAILED: Access denied - wrong username or password"
        exit 1
    }}
    "{hostname}>" {{
        # Login successful
    }}
    timeout {{
        puts "ERROR_AUTH_FAILED: Login timeout - check username/password"
        exit 1
    }}
}}

# === ENABLE MODE ===
send "enable\\r"
expect {{
    "{hostname}#" {{}}
    "Password:" {{
        puts "ERROR_ENABLE_PASSWORD: Enable password required but not provided"
        exit 1
    }}
    timeout {{
        puts "ERROR_ENABLE_TIMEOUT: Timeout entering enable mode"
        exit 1
    }}
}}

# === CONFIGURE MODE ===
send "configure\\r"
expect {{
    "{hostname}(config)#" {{}}
    timeout {{
        puts "ERROR_CONFIG_TIMEOUT: Timeout entering config mode"
        exit 1
    }}
}}

# === PORT CONFIGURATION ===
{port_commands}

# === SAVE CONFIG ===
send "exit\\r"
expect "{hostname}#"
send "copy running-config startup-config\\r"

expect {{
    "Saving user config OK!" {{
        puts "SUCCESS_CONFIG_SAVED"
    }}
    "Succeed" {{
        puts "SUCCESS_CONFIG_SAVED"
    }}
    timeout {{
        puts "ERROR_SAVE_TIMEOUT: Timeout saving configuration"
        exit 1
    }}
}}

# === LOGOUT ===
send "exit\\r"
expect "{hostname}>"
send "exit\\r"
expect eof

puts "SUCCESS_COMPLETE"
'''
    return script


def analyze_output(stdout, stderr):
    """Analyze expect output for errors and return appropriate message"""
    
    # Check for specific error patterns
    error_patterns = {
        "ERROR_CONNECTION_FAILED": "Verbindung fehlgeschlagen: Host nicht erreichbar",
        "ERROR_CONNECTION_REFUSED": "Verbindung abgelehnt: SSH-Port nicht offen",
        "ERROR_CONNECTION_TIMEOUT": "Verbindungs-Timeout: Host antwortet nicht",
        "ERROR_HOST_UNREACHABLE": "Host nicht erreichbar: Netzwerkproblem",
        "ERROR_DNS_FAILED": "DNS-Auflösung fehlgeschlagen",
        "ERROR_AUTH_FAILED": "Authentifizierung fehlgeschlagen: Falscher Benutzername oder Passwort",
        "ERROR_ENABLE_PASSWORD": "Enable-Passwort erforderlich",
        "ERROR_ENABLE_TIMEOUT": "Timeout beim Wechsel in Enable-Modus",
        "ERROR_CONFIG_TIMEOUT": "Timeout beim Wechsel in Config-Modus",
        "ERROR_SAVE_TIMEOUT": "Timeout beim Speichern der Konfiguration",
        "ERROR_PORT_TIMEOUT": "Timeout bei der Port-Konfiguration",
    }
    
    # Also check raw SSH errors in output
    ssh_errors = {
        "No route to host": "Verbindung fehlgeschlagen: Keine Route zum Host",
        "Connection refused": "Verbindung abgelehnt: SSH-Dienst nicht erreichbar",
        "Connection timed out": "Verbindungs-Timeout: Host antwortet nicht",
        "Host is unreachable": "Host nicht erreichbar",
        "Permission denied": "Authentifizierung fehlgeschlagen: Falscher Benutzername oder Passwort",
    }
    
    combined = stdout + stderr
    
    # Check for our custom error markers first
    for error_key, error_msg in error_patterns.items():
        if error_key in combined:
            return False, error_msg
    
    # Check for raw SSH errors
    for ssh_error, error_msg in ssh_errors.items():
        if ssh_error in combined:
            return False, error_msg
    
    # Check for success
    if "SUCCESS_COMPLETE" in combined or "SUCCESS_CONFIG_SAVED" in combined:
        return True, None
    
    # Check for timeout markers
    if "TIMEOUT" in combined:
        return False, "Timeout während der Konfiguration"
    
    # If we got here without clear success, be cautious
    if "Saving user config OK!" in combined or "copy running-config startup-config" in combined:
        return True, None
    
    return False, "Unbekannter Fehler - bitte stdout prüfen"


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
        module.fail_json(msg="Mindestens trunk_ports oder access_ports muss angegeben werden")
    
    script = create_batch_port_script(
        host, username, password, hostname, mode, trunk_ports, access_ports
    )
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.exp', delete=False) as f:
        f.write(script)
        script_path = f.name
    
    try:
        os.chmod(script_path, 0o700)
        result = subprocess.run(
            [script_path], 
            capture_output=True, 
            text=True, 
            timeout=180
        )
        os.unlink(script_path)
        
        # Analysiere Output
        success, error_msg = analyze_output(result.stdout, result.stderr)
        
        if not success:
            module.fail_json(
                msg=f"Port-Konfiguration fehlgeschlagen: {error_msg}",
                host=host,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode
            )
        
        # Zähle Operationen
        trunk_count = len(trunk_ports)
        access_count = len(access_ports)
        
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
        module.fail_json(
            msg="Gesamttimeout überschritten (180s) - Switch antwortet nicht oder Netzwerkproblem",
            host=host
        )
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg=f"Unerwarteter Fehler: {str(e)}", host=host)


if __name__ == '__main__':
    main()
