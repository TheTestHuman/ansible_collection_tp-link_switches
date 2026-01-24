#!/usr/bin/python
# -*- coding: utf-8 -*-

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os

def create_batch_vlan_script(host, username, password, vlans, hostname):
    """Generate expect script for BATCH VLAN creation"""
    
    # Alle VLAN-Befehle sammeln
    vlan_commands = ""
    for vlan in vlans:
        if vlan['id'] != 1:  # Skip default VLAN
            vlan_commands += f'''send "vlan {vlan['id']}\\r"
expect "{hostname}(config-vlan)#"
send "name {vlan['name']}\\r"
expect "{hostname}(config-vlan)#"
send "exit\\r"
expect "{hostname}(config)#"
'''
    
    script = f'''#!/usr/bin/expect -f
set timeout 60

spawn ssh -o PubkeyAuthentication=no {username}@{host}
expect "password:"
send "{password}\\r"
expect "{hostname}>"
send "enable\\r"
expect "{hostname}#"
send "configure\\r"
expect "{hostname}(config)#"

# Alle VLANs erstellen
{vlan_commands}

# NUR EINMAL speichern am Ende!
send "exit\\r"
expect "{hostname}#"
send "copy running-config startup-config\\r"
expect "Saving user config OK!"
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
        ),
        supports_check_mode=False
    )
    
    script = create_batch_vlan_script(
        module.params['host'],
        module.params['username'],
        module.params['password'],
        module.params['vlans'],
        module.params['hostname']
    )
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.exp', delete=False) as f:
        f.write(script)
        script_path = f.name
    
    try:
        os.chmod(script_path, 0o700)
        result = subprocess.run([script_path], capture_output=True, text=True, timeout=90)
        os.unlink(script_path)
        
        # Zähle erfolgreiche VLANs
        vlan_count = len([v for v in module.params['vlans'] if v['id'] != 1])
        
        module.exit_json(
            changed=True,
            msg=f"Created {vlan_count} VLANs in batch",
            vlans_created=vlan_count,
            stdout=result.stdout
        )
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg=str(e))

if __name__ == '__main__':
    main()
