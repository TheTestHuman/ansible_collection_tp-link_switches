#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
TP-Link SG3210 LAG (Link Aggregation) Configuration Module

Konfiguriert Link Aggregation Groups auf TP-Link SG3210 Managed Switches via expect.

Parameter:
    host: Switch IP-Adresse
    username: SSH Username
    password: SSH Passwort
    hostname: CLI Prompt Hostname (default: SG3210)
    lag_id: LAG/Port-Channel ID (1-8)
    ports: Liste von Ports für LAG
    lacp_mode: LACP Modus - active, passive, on (default: active)
    state: present oder absent (default: present)

Beispiel:
    - tp_link_lag_expect:
        host: "10.0.10.1"
        username: "admin"
        password: "secret"
        lag_id: 1
        ports: [9, 10]
        lacp_mode: "active"
        state: "present"
"""

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os


def create_lag_script(host, username, password, hostname, lag_id, ports, lacp_mode, state):
    """Generate expect script for LAG configuration with error handling"""
    
    port_commands = ""
    
    if state == 'present':
        # Ports zum LAG hinzufügen
        for port in ports:
            port_commands += f'''
# === PORT {port} zu LAG {lag_id} hinzufügen ===
send "interface gigabitEthernet 1/0/{port}\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    timeout {{
        puts "ERROR_PORT_TIMEOUT: Timeout entering interface config for port {port}"
        exit 1
    }}
}}
send "channel-group {lag_id} mode {lacp_mode}\\r"
expect "{hostname}(config-if)#"
send "exit\\r"
expect "{hostname}(config)#"
'''
    elif state == 'absent':
        # Ports aus LAG entfernen
        for port in ports:
            port_commands += f'''
# === PORT {port} aus LAG entfernen ===
send "interface gigabitEthernet 1/0/{port}\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    timeout {{
        puts "ERROR_PORT_TIMEOUT: Timeout entering interface config for port {port}"
        exit 1
    }}
}}
send "no channel-group\\r"
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

# === LAG CONFIGURATION ===
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
        "ERROR_LAG_FAILED": "LAG-Konfiguration fehlgeschlagen",
    }
    
    ssh_errors = {
        "No route to host": "Verbindung fehlgeschlagen: Keine Route zum Host",
        "Connection refused": "Verbindung abgelehnt: SSH-Dienst nicht erreichbar",
        "Connection timed out": "Verbindungs-Timeout: Host antwortet nicht",
        "Host is unreachable": "Host nicht erreichbar",
        "Permission denied": "Authentifizierung fehlgeschlagen: Falscher Benutzername oder Passwort",
    }
    
    combined = stdout + stderr
    
    for error_key, error_msg in error_patterns.items():
        if error_key in combined:
            return False, error_msg
    
    for ssh_error, error_msg in ssh_errors.items():
        if ssh_error in combined:
            return False, error_msg
    
    if "SUCCESS_COMPLETE" in combined or "SUCCESS_CONFIG_SAVED" in combined:
        return True, None
    
    if "TIMEOUT" in combined:
        return False, "Timeout während der Konfiguration"
    
    if "Saving user config OK!" in combined:
        return True, None
    
    return False, "Unbekannter Fehler - bitte stdout prüfen"


def main():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type='str', required=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            hostname=dict(type='str', required=False, default='SG3210'),
            lag_id=dict(type='int', required=True),
            ports=dict(type='list', required=True, elements='int'),
            lacp_mode=dict(type='str', required=False, default='active',
                          choices=['active', 'passive', 'on']),
            state=dict(type='str', required=False, default='present',
                      choices=['present', 'absent']),
        ),
        supports_check_mode=False
    )
    
    host = module.params['host']
    username = module.params['username']
    password = module.params['password']
    hostname = module.params['hostname']
    lag_id = module.params['lag_id']
    ports = module.params['ports']
    lacp_mode = module.params['lacp_mode']
    state = module.params['state']
    
    # Validierung
    if not 1 <= lag_id <= 8:
        module.fail_json(msg="LAG ID muss zwischen 1 und 8 liegen")
    
    for port in ports:
        if not 1 <= port <= 10:
            module.fail_json(msg=f"Port {port} ungültig. Muss zwischen 1 und 10 liegen")
    
    if len(ports) < 2:
        module.fail_json(msg="Mindestens 2 Ports für LAG erforderlich")
    
    script = create_lag_script(
        host, username, password, hostname, lag_id, ports, lacp_mode, state
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
            timeout=120
        )
        os.unlink(script_path)
        
        success, error_msg = analyze_output(result.stdout, result.stderr)
        
        if not success:
            module.fail_json(
                msg=f"LAG-Konfiguration fehlgeschlagen: {error_msg}",
                host=host,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode
            )
        
        action = "erstellt" if state == 'present' else "entfernt"
        
        module.exit_json(
            changed=True,
            msg=f"LAG {lag_id} {action} mit Ports {ports} (Modus: {lacp_mode})",
            lag_id=lag_id,
            ports=ports,
            lacp_mode=lacp_mode,
            state=state,
            stdout=result.stdout
        )
        
    except subprocess.TimeoutExpired:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(
            msg="Gesamttimeout überschritten (120s) - Switch antwortet nicht",
            host=host
        )
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg=f"Unerwarteter Fehler: {str(e)}", host=host)


if __name__ == '__main__':
    main()
