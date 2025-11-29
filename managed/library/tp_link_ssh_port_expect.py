#!/usr/bin/python
# -*- coding: utf-8 -*-

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os

DOCUMENTATION = r'''
module: tp_link_ssh_port_expect
short_description: Configure ports on TP-Link SG3210 via SSH using expect
options:
    host:
        description: Switch IP address
        required: true
    username:
        description: SSH username
        required: true
    password:
        description: SSH password
        required: true
        no_log: true
    port:
        description: Port number (1-10)
        required: true
        type: int
    mode:
        description: Port mode (access or trunk)
        required: true
        choices: ['access', 'trunk']
    access_vlan:
        description: Access VLAN ID (for access mode)
        required: false
        type: int
    trunk_vlans:
        description: Allowed VLANs for trunk (comma-separated, e.g. "10,20,30")
        required: false
        type: str
'''

def create_port_expect_script(host, username, password, port, mode, access_vlan=None, trunk_vlans=None):
    """Generate expect script for port configuration"""
    
    # Build configuration commands
    commands = []
    
    if mode == 'access':
        if not access_vlan:
            raise ValueError("access_vlan required for access mode")
        commands = [
            f"interface gigabitEthernet 1/0/{port}",
            "switchport mode access",
            f"switchport access vlan {access_vlan}",
            "exit"
        ]
    elif mode == 'trunk':
        if not trunk_vlans:
            raise ValueError("trunk_vlans required for trunk mode")
        commands = [
            f"interface gigabitEthernet 1/0/{port}",
            "switchport mode trunk",
            f"switchport trunk allowed vlan add {trunk_vlans}",
            "exit"
        ]
    
    # Build expect script
    script = f'''#!/usr/bin/expect -f
set timeout 30
spawn ssh -o PubkeyAuthentication=no {username}@{host}
expect "password:"
send "{password}\\r"
expect "SG3210>"
send "enable\\r"
expect "SG3210#"
send "configure\\r"
expect "SG3210(config)#"
'''
    
    for cmd in commands:
        script += f'send "{cmd}\\r"\n'
        if "exit" in cmd:
            script += 'expect "SG3210(config)#"\n'
        else:
            script += 'expect -re "SG3210\\\\(.*\\\\)#"\n'
    
    script += '''send "exit\\r"
expect "SG3210#"
send "copy running-config startup-config\\r"
expect "OK!"
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
            port=dict(type='int', required=True),
            mode=dict(type='str', required=True, choices=['access', 'trunk']),
            access_vlan=dict(type='int', required=False),
            trunk_vlans=dict(type='str', required=False),
        ),
        supports_check_mode=False
    )
    
    # Validate parameters
    if module.params['mode'] == 'access' and not module.params['access_vlan']:
        module.fail_json(msg="access_vlan required for access mode")
    if module.params['mode'] == 'trunk' and not module.params['trunk_vlans']:
        module.fail_json(msg="trunk_vlans required for trunk mode")
    
    # Generate expect script
    try:
        script = create_port_expect_script(
            module.params['host'],
            module.params['username'],
            module.params['password'],
            module.params['port'],
            module.params['mode'],
            module.params.get('access_vlan'),
            module.params.get('trunk_vlans')
        )
    except ValueError as e:
        module.fail_json(msg=str(e))
    
    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.exp', delete=False) as f:
        f.write(script)
        script_path = f.name
    
    try:
        os.chmod(script_path, 0o700)
        result = subprocess.run([script_path], capture_output=True, text=True, timeout=60)
        
        os.unlink(script_path)
        
        module.exit_json(
            changed=True,
            port={
                'port': module.params['port'],
                'mode': module.params['mode'],
                'access_vlan': module.params.get('access_vlan'),
                'trunk_vlans': module.params.get('trunk_vlans')
            },
            stdout=result.stdout
        )
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg=str(e))

if __name__ == '__main__':
    main()
