#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
TP-Link SG3210 Batch VLAN Configuration Module

Erstellt/verwaltet VLANs auf TP-Link SG3210 Managed Switches via expect.

Parameter:
    host: Switch IP-Adresse
    username: SSH Username
    password: SSH Passwort
    vlans: Liste von VLANs [{id: 10, name: "Management"}, ...]
    hostname: CLI Prompt Hostname (default: SG3210)
    mode: "replace" oder "add" (default: add)
        - replace: Löscht alle VLANs außer protected_vlans, dann erstellt neue
        - add: Fügt VLANs nur hinzu (keine Löschung)
    protected_vlans: Liste von VLAN-IDs die nie gelöscht werden (default: [1])

Beispiel:
    - tp_link_batch_vlan_expect:
        host: "10.0.10.1"
        username: "admin"
        password: "secret"
        vlans:
          - id: 10
            name: "Management"
          - id: 20
            name: "Clients"
        mode: "replace"
        protected_vlans: [1]
"""

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os


def create_batch_vlan_script(host, username, password, vlans, hostname, mode, protected_vlans, vlans_to_delete):
    """Generate expect script for BATCH VLAN creation with error handling"""
    
    # Delete-Befehle generieren (nur bei mode=replace)
    delete_commands = ""
    if mode == "replace" and vlans_to_delete:
        for vlan_id in vlans_to_delete:
            delete_commands += f'''send "no vlan {vlan_id}\\r"
expect "{hostname}(config)#"
'''
    
    # Create-Befehle generieren
    create_commands = ""
    for vlan in vlans:
        if vlan['id'] not in protected_vlans:
            create_commands += f'''send "vlan {vlan['id']}\\r"
expect "{hostname}(config-vlan)#"
send "name {vlan['name']}\\r"
expect "{hostname}(config-vlan)#"
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

# === DELETE PHASE ===
{delete_commands}

# === CREATE PHASE ===
{create_commands}

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
            vlans=dict(type='list', required=True, elements='dict'),
            hostname=dict(type='str', required=False, default='SG3210'),
            mode=dict(type='str', required=False, default='add', choices=['add', 'replace']),
            protected_vlans=dict(type='list', required=False, default=[1], elements='int'),
        ),
        supports_check_mode=False
    )
    
    host = module.params['host']
    username = module.params['username']
    password = module.params['password']
    vlans = module.params['vlans']
    hostname = module.params['hostname']
    mode = module.params['mode']
    protected_vlans = module.params['protected_vlans']
    
    # Ziel-VLAN-IDs extrahieren
    target_vlan_ids = [v['id'] for v in vlans]
    
    # Bei mode=replace: Berechne welche VLANs gelöscht werden sollen
    vlans_to_delete = []
    if mode == "replace":
        for vlan_id in range(2, 101):
            if vlan_id not in protected_vlans and vlan_id not in target_vlan_ids:
                vlans_to_delete.append(vlan_id)
    
    script = create_batch_vlan_script(
        host, username, password, vlans, hostname, mode, protected_vlans, vlans_to_delete
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
            timeout=180  # Gesamttimeout höher als expect-Timeouts
        )
        os.unlink(script_path)
        
        # Analysiere Output
        success, error_msg = analyze_output(result.stdout, result.stderr)
        
        if not success:
            module.fail_json(
                msg=f"VLAN-Konfiguration fehlgeschlagen: {error_msg}",
                host=host,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode
            )
        
        # Zähle Operationen
        vlans_created = len([v for v in vlans if v['id'] not in protected_vlans])
        vlans_deleted = len(vlans_to_delete) if mode == "replace" else 0
        
        module.exit_json(
            changed=True,
            msg=f"Mode '{mode}': Created {vlans_created} VLANs" + (f", deleted up to {vlans_deleted} VLANs" if mode == "replace" else ""),
            mode=mode,
            vlans_created=vlans_created,
            vlans_deleted=vlans_deleted,
            target_vlans=target_vlan_ids,
            protected_vlans=protected_vlans,
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
