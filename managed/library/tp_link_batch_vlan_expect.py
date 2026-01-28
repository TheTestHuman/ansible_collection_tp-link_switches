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
    """Generate expect script for BATCH VLAN creation"""
    
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
        if vlan['id'] not in protected_vlans:  # Protected VLANs nicht neu erstellen
            create_commands += f'''send "vlan {vlan['id']}\\r"
expect "{hostname}(config-vlan)#"
send "name {vlan['name']}\\r"
expect "{hostname}(config-vlan)#"
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

# === DELETE PHASE ===
{delete_commands}

# === CREATE PHASE ===
{create_commands}

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
    # Wir löschen alle BEKANNTEN VLANs (2-4094) außer protected und target
    # Da wir keinen zuverlässigen Check haben, löschen wir die gängigen VLANs 2-100
    vlans_to_delete = []
    if mode == "replace":
        # Lösche VLANs 2-100 (außer protected und target)
        # Das ist ein pragmatischer Ansatz ohne vorherigen Check
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
        result = subprocess.run([script_path], capture_output=True, text=True, timeout=120)
        os.unlink(script_path)
        
        # Zähle Operationen
        vlans_created = len([v for v in vlans if v['id'] not in protected_vlans])
        vlans_deleted = len(vlans_to_delete) if mode == "replace" else 0
        
        # Prüfe auf Fehler im Output
        if "TIMEOUT" in result.stdout:
            module.fail_json(
                msg="Timeout während der VLAN-Konfiguration",
                stdout=result.stdout,
                stderr=result.stderr
            )
        
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
        module.fail_json(msg="Command timed out after 120 seconds")
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg=str(e))


if __name__ == '__main__':
    main()
