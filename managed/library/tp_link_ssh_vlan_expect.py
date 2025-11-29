#!/usr/bin/python
# -*- coding: utf-8 -*-

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os

DOCUMENTATION = r'''
module: tp_link_ssh_vlan_expect
short_description: Manage VLANs on TP-Link SG3210 via SSH using expect
'''

def create_vlan_expect_script(host, username, password, vlan_id, vlan_name):
    """Generate expect script"""
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
send "vlan {vlan_id}\\r"
expect "SG3210(config-vlan)#"
send "name {vlan_name}\\r"
expect "SG3210(config-vlan)#"
send "exit\\r"
expect "SG3210(config)#"
send "exit\\r"
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
            vlan_id=dict(type='int', required=True),
            vlan_name=dict(type='str', required=True),
        ),
        supports_check_mode=False
    )
    
    # Generate expect script
    script = create_vlan_expect_script(
        module.params['host'],
        module.params['username'],
        module.params['password'],
        module.params['vlan_id'],
        module.params['vlan_name']
    )
    
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
            vlan={'vlan_id': module.params['vlan_id'], 'vlan_name': module.params['vlan_name']},
            stdout=result.stdout
        )
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg=str(e))

if __name__ == '__main__':
    main()
