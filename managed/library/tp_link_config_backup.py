#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
TP-Link SG3210 Configuration Backup/Restore Module

Sichert und stellt Switch-Konfigurationen wieder her.

Aktionen:
    backup_switch: Speichert running-config in backup-config auf dem Switch
    backup_local: Lädt running-config herunter und speichert als Datei
    restore_switch: Stellt backup-config auf dem Switch wieder her
    restore_local: Lädt Config-Datei hoch und wendet sie an

Parameter:
    host: Switch IP-Adresse
    username: SSH Username
    password: SSH Passwort
    hostname: CLI Prompt Hostname (default: SG3210)
    action: backup_switch, backup_local, restore_switch, restore_local
    backup_dir: Verzeichnis für lokale Backups (default: ./backups)
    backup_file: Dateiname für Backup (default: {hostname}_{datum}.cfg)
    config_file: Pfad zur Config-Datei für restore_local

Beispiele:
    # Backup auf Switch
    - tp_link_config_backup:
        host: "10.0.10.1"
        action: backup_switch

    # Backup lokal speichern
    - tp_link_config_backup:
        host: "10.0.10.1"
        action: backup_local
        backup_dir: "/home/user/backups"

    # Von Switch-Backup wiederherstellen
    - tp_link_config_backup:
        host: "10.0.10.1"
        action: restore_switch

    # Von lokaler Datei wiederherstellen
    - tp_link_config_backup:
        host: "10.0.10.1"
        action: restore_local
        config_file: "/home/user/backups/switch_2024-01-30.cfg"
"""

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os
import re
from datetime import datetime


def create_backup_switch_script(host, username, password, hostname):
    """Backup running-config to backup-config on switch"""
    
    script = f'''#!/usr/bin/expect -f
set timeout 30
log_user 1

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
    "password:" {{
        send "{password}\\r"
    }}
    timeout {{
        puts "ERROR_CONNECTION_TIMEOUT: Timeout connecting to {host}"
        exit 1
    }}
}}

expect {{
    "Permission denied" {{
        puts "ERROR_AUTH_FAILED: Authentication failed"
        exit 1
    }}
    "{hostname}>" {{}}
    timeout {{
        puts "ERROR_AUTH_FAILED: Login timeout"
        exit 1
    }}
}}

send "enable\\r"
expect "{hostname}#"

send "copy running-config backup-config\\r"
expect {{
    "Saving user config OK!" {{
        puts "SUCCESS_BACKUP_COMPLETE"
    }}
    "Succeed" {{
        puts "SUCCESS_BACKUP_COMPLETE"
    }}
    timeout {{
        puts "ERROR_BACKUP_TIMEOUT: Timeout during backup"
        exit 1
    }}
}}

expect "{hostname}#"
send "exit\\r"
expect "{hostname}>"
send "exit\\r"
expect eof
'''
    return script


def create_show_config_script(host, username, password, hostname):
    """Get running-config for local backup"""
    
    script = f'''#!/usr/bin/expect -f
set timeout 60
log_user 1

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
    "password:" {{
        send "{password}\\r"
    }}
    timeout {{
        puts "ERROR_CONNECTION_TIMEOUT: Timeout connecting to {host}"
        exit 1
    }}
}}

expect {{
    "Permission denied" {{
        puts "ERROR_AUTH_FAILED: Authentication failed"
        exit 1
    }}
    "{hostname}>" {{}}
    timeout {{
        puts "ERROR_AUTH_FAILED: Login timeout"
        exit 1
    }}
}}

send "enable\\r"
expect "{hostname}#"

send "terminal length 0\\r"
expect "{hostname}#"

puts "CONFIG_START_MARKER"
send "show running-config\\r"
expect "{hostname}#"
puts "CONFIG_END_MARKER"

send "exit\\r"
expect "{hostname}>"
send "exit\\r"
expect eof

puts "SUCCESS_CONFIG_RETRIEVED"
'''
    return script


def create_restore_switch_script(host, username, password, hostname):
    """Restore backup-config to running-config and save"""
    
    script = f'''#!/usr/bin/expect -f
set timeout 30
log_user 1

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
    "password:" {{
        send "{password}\\r"
    }}
    timeout {{
        puts "ERROR_CONNECTION_TIMEOUT: Timeout connecting to {host}"
        exit 1
    }}
}}

expect {{
    "Permission denied" {{
        puts "ERROR_AUTH_FAILED: Authentication failed"
        exit 1
    }}
    "{hostname}>" {{}}
    timeout {{
        puts "ERROR_AUTH_FAILED: Login timeout"
        exit 1
    }}
}}

send "enable\\r"
expect "{hostname}#"

send "copy backup-config startup-config\\r"
expect {{
    "Saving user config OK!" {{
        puts "SUCCESS_RESTORE_COMPLETE"
    }}
    "Succeed" {{
        puts "SUCCESS_RESTORE_COMPLETE"
    }}
    "No backup configuration" {{
        puts "ERROR_NO_BACKUP: No backup configuration exists on switch"
        exit 1
    }}
    timeout {{
        puts "ERROR_RESTORE_TIMEOUT: Timeout during restore"
        exit 1
    }}
}}

expect "{hostname}#"
send "exit\\r"
expect "{hostname}>"
send "exit\\r"
expect eof
'''
    return script


def create_restore_local_script(host, username, password, hostname, config_commands):
    """Apply configuration commands from local file with intelligent mode handling"""
    
    # Build command sequence with mode awareness
    command_section = ""
    current_mode = "config"  # Start in (config)# mode
    
    for cmd in config_commands:
        cmd = cmd.strip()
        if not cmd or cmd.startswith('!') or cmd.startswith('#'):
            continue
        
        # Skip problematic commands
        skip_patterns = [
            'user name',      # Don't overwrite user credentials
            'secret ',        # Password hashes
            'end',            # We handle this ourselves
        ]
        if any(pattern in cmd.lower() for pattern in skip_patterns):
            continue
        
        # Escape special characters for expect
        cmd_escaped = cmd.replace('"', '\\"').replace("'", "\\'")
        
        # Determine what mode this command needs
        if cmd.startswith('vlan ') and not cmd.startswith('vlan-'):
            # VLAN command - need to be in config mode, will enter config-vlan
            if current_mode != "config":
                command_section += f'''send "exit\\r"
expect "{hostname}(config)#"
'''
            command_section += f'''send "{cmd_escaped}\\r"
expect "{hostname}(config-vlan)#"
'''
            current_mode = "config-vlan"
            
        elif cmd.startswith('name '):
            # VLAN name - must be in config-vlan mode
            command_section += f'''send "{cmd_escaped}\\r"
expect "{hostname}(config-vlan)#"
'''
            
        elif cmd.startswith('interface '):
            # Interface command - need to exit to config first, then enter interface
            if current_mode == "config-vlan":
                command_section += f'''send "exit\\r"
expect "{hostname}(config)#"
'''
            elif current_mode == "config-if":
                command_section += f'''send "exit\\r"
expect "{hostname}(config)#"
'''
            command_section += f'''send "{cmd_escaped}\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    "{hostname}(config)#" {{}}
}}
'''
            current_mode = "config-if"
            
        elif cmd.startswith('switchport ') or cmd.startswith('mac address-table max-mac-count'):
            # Interface sub-command - must be in config-if mode
            if current_mode == "config-if":
                command_section += f'''send "{cmd_escaped}\\r"
expect "{hostname}(config-if)#"
'''
            # Skip if not in interface mode
            
        else:
            # Global config command - must be in (config)# mode
            if current_mode == "config-vlan":
                command_section += f'''send "exit\\r"
expect "{hostname}(config)#"
'''
                current_mode = "config"
            elif current_mode == "config-if":
                command_section += f'''send "exit\\r"
expect "{hostname}(config)#"
'''
                current_mode = "config"
            
            command_section += f'''send "{cmd_escaped}\\r"
expect {{
    "{hostname}(config)#" {{}}
    "{hostname}#" {{}}
    timeout {{ puts "WARNING: Timeout after: {cmd_escaped}" }}
}}
'''
    
    script = f'''#!/usr/bin/expect -f
set timeout 15
log_user 1

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
    "password:" {{
        send "{password}\\r"
    }}
    timeout {{
        puts "ERROR_CONNECTION_TIMEOUT: Timeout connecting to {host}"
        exit 1
    }}
}}

expect {{
    "Permission denied" {{
        puts "ERROR_AUTH_FAILED: Authentication failed"
        exit 1
    }}
    "{hostname}>" {{}}
    timeout {{
        puts "ERROR_AUTH_FAILED: Login timeout"
        exit 1
    }}
}}

send "enable\\r"
expect "{hostname}#"

send "configure\\r"
expect "{hostname}(config)#"

# === APPLY CONFIG COMMANDS ===
{command_section}

# Exit all config modes back to enable
send "end\\r"
expect "{hostname}#"

send "copy running-config startup-config\\r"
expect {{
    "Saving user config OK!" {{
        puts "SUCCESS_RESTORE_COMPLETE"
    }}
    "Succeed" {{
        puts "SUCCESS_RESTORE_COMPLETE"
    }}
    timeout {{
        puts "ERROR_SAVE_TIMEOUT: Timeout saving configuration"
        exit 1
    }}
}}

expect "{hostname}#"
send "exit\\r"
expect "{hostname}>"
send "exit\\r"
expect eof
'''
    return script


def parse_config_from_output(output):
    """Extract configuration from show running-config output"""
    
    # Find config between markers
    start_marker = "CONFIG_START_MARKER"
    end_marker = "CONFIG_END_MARKER"
    
    if start_marker in output and end_marker in output:
        start = output.index(start_marker) + len(start_marker)
        end = output.index(end_marker)
        config_section = output[start:end]
    else:
        # Fallback: try to find config by patterns
        config_section = output
    
    # Clean up the config
    lines = config_section.split('\n')
    config_lines = []
    in_config = False
    
    for line in lines:
        # Skip empty lines and prompts
        if not line.strip():
            continue
        if line.strip().startswith('SG3210'):
            continue
        if 'show running-config' in line:
            in_config = True
            continue
        if 'terminal length' in line:
            continue
            
        if in_config:
            # Stop at end of config
            if line.strip().startswith('SG3210'):
                break
            config_lines.append(line.rstrip())
    
    return '\n'.join(config_lines)


def analyze_output(stdout, stderr):
    """Analyze expect output for errors"""
    
    error_patterns = {
        "ERROR_CONNECTION_FAILED": "Verbindung fehlgeschlagen: Host nicht erreichbar",
        "ERROR_CONNECTION_REFUSED": "Verbindung abgelehnt: SSH-Port nicht offen",
        "ERROR_CONNECTION_TIMEOUT": "Verbindungs-Timeout: Host antwortet nicht",
        "ERROR_AUTH_FAILED": "Authentifizierung fehlgeschlagen",
        "ERROR_BACKUP_TIMEOUT": "Timeout beim Backup",
        "ERROR_RESTORE_TIMEOUT": "Timeout beim Restore",
        "ERROR_SAVE_TIMEOUT": "Timeout beim Speichern",
        "ERROR_NO_BACKUP": "Kein Backup auf dem Switch vorhanden",
    }
    
    ssh_errors = {
        "No route to host": "Verbindung fehlgeschlagen: Keine Route zum Host",
        "Connection refused": "Verbindung abgelehnt",
        "Permission denied": "Authentifizierung fehlgeschlagen",
    }
    
    combined = stdout + stderr
    
    for error_key, error_msg in error_patterns.items():
        if error_key in combined:
            return False, error_msg
    
    for ssh_error, error_msg in ssh_errors.items():
        if ssh_error in combined:
            return False, error_msg
    
    success_markers = ["SUCCESS_BACKUP_COMPLETE", "SUCCESS_RESTORE_COMPLETE", "SUCCESS_CONFIG_RETRIEVED"]
    for marker in success_markers:
        if marker in combined:
            return True, None
    
    return False, "Unbekannter Fehler - bitte stdout prüfen"


def run_expect_script(script_content, timeout=120):
    """Run an expect script and return the result"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.exp', delete=False) as f:
        f.write(script_content)
        script_path = f.name
    
    try:
        os.chmod(script_path, 0o700)
        result = subprocess.run(
            [script_path],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.stdout, result.stderr, result.returncode
    finally:
        if os.path.exists(script_path):
            os.unlink(script_path)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type='str', required=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            hostname=dict(type='str', required=False, default='SG3210'),
            action=dict(type='str', required=True, 
                       choices=['backup_switch', 'backup_local', 'restore_switch', 'restore_local']),
            backup_dir=dict(type='str', required=False, default='./backups'),
            backup_file=dict(type='str', required=False),
            config_file=dict(type='str', required=False),
        ),
        supports_check_mode=False
    )
    
    host = module.params['host']
    username = module.params['username']
    password = module.params['password']
    hostname = module.params['hostname']
    action = module.params['action']
    backup_dir = module.params['backup_dir']
    backup_file = module.params['backup_file']
    config_file = module.params['config_file']
    
    # === ACTION: backup_switch ===
    if action == 'backup_switch':
        script = create_backup_switch_script(host, username, password, hostname)
        
        try:
            stdout, stderr, rc = run_expect_script(script)
        except subprocess.TimeoutExpired:
            module.fail_json(msg="Timeout beim Backup auf Switch", host=host)
        
        success, error_msg = analyze_output(stdout, stderr)
        if not success:
            module.fail_json(msg=f"Backup fehlgeschlagen: {error_msg}", host=host, stdout=stdout)
        
        module.exit_json(
            changed=True,
            msg="Backup auf Switch erstellt (running-config -> backup-config)",
            action=action,
            host=host,
            stdout=stdout
        )
    
    # === ACTION: backup_local ===
    elif action == 'backup_local':
        # Create backup directory if needed
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        # Generate filename
        if not backup_file:
            timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
            backup_file = f"{hostname}_{host.replace('.', '-')}_{timestamp}.cfg"
        
        backup_path = os.path.join(backup_dir, backup_file)
        
        # Get running-config
        script = create_show_config_script(host, username, password, hostname)
        
        try:
            stdout, stderr, rc = run_expect_script(script, timeout=120)
        except subprocess.TimeoutExpired:
            module.fail_json(msg="Timeout beim Abrufen der Konfiguration", host=host)
        
        success, error_msg = analyze_output(stdout, stderr)
        if not success:
            module.fail_json(msg=f"Backup fehlgeschlagen: {error_msg}", host=host, stdout=stdout)
        
        # Parse and save config
        config = parse_config_from_output(stdout)
        
        if not config or len(config) < 50:
            module.fail_json(
                msg="Konfiguration konnte nicht extrahiert werden",
                host=host,
                stdout=stdout
            )
        
        with open(backup_path, 'w') as f:
            f.write(f"! Backup von {host} ({hostname})\n")
            f.write(f"! Erstellt: {datetime.now().isoformat()}\n")
            f.write("!\n")
            f.write(config)
        
        module.exit_json(
            changed=True,
            msg=f"Backup lokal gespeichert: {backup_path}",
            action=action,
            host=host,
            backup_path=backup_path,
            backup_size=len(config),
            stdout=stdout
        )
    
    # === ACTION: restore_switch ===
    elif action == 'restore_switch':
        script = create_restore_switch_script(host, username, password, hostname)
        
        try:
            stdout, stderr, rc = run_expect_script(script)
        except subprocess.TimeoutExpired:
            module.fail_json(msg="Timeout beim Restore", host=host)
        
        success, error_msg = analyze_output(stdout, stderr)
        if not success:
            module.fail_json(msg=f"Restore fehlgeschlagen: {error_msg}", host=host, stdout=stdout)
        
        module.exit_json(
            changed=True,
            msg="Backup vom Switch wiederhergestellt (backup-config -> startup-config)",
            action=action,
            host=host,
            stdout=stdout
        )
    
    # === ACTION: restore_local ===
    elif action == 'restore_local':
        if not config_file:
            module.fail_json(msg="config_file ist erforderlich für restore_local")
        
        if not os.path.exists(config_file):
            module.fail_json(msg=f"Config-Datei nicht gefunden: {config_file}")
        
        # Read config file
        with open(config_file, 'r') as f:
            config_content = f.read()
        
        # Parse commands (skip comments and empty lines)
        config_commands = []
        for line in config_content.split('\n'):
            line = line.strip()
            if line and not line.startswith('!') and not line.startswith('#'):
                config_commands.append(line)
        
        if not config_commands:
            module.fail_json(msg="Keine Konfigurationsbefehle in der Datei gefunden")
        
        script = create_restore_local_script(host, username, password, hostname, config_commands)
        
        try:
            stdout, stderr, rc = run_expect_script(script, timeout=180)
        except subprocess.TimeoutExpired:
            module.fail_json(msg="Timeout beim Restore von lokaler Datei", host=host)
        
        success, error_msg = analyze_output(stdout, stderr)
        if not success:
            module.fail_json(msg=f"Restore fehlgeschlagen: {error_msg}", host=host, stdout=stdout)
        
        module.exit_json(
            changed=True,
            msg=f"Konfiguration von {config_file} wiederhergestellt",
            action=action,
            host=host,
            config_file=config_file,
            commands_applied=len(config_commands),
            stdout=stdout
        )


if __name__ == '__main__':
    main()
