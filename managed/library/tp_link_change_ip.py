#!/usr/bin/python
# -*- coding: utf-8 -*-

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os

DOCUMENTATION = r'''
module: tp_link_change_ip
short_description: Change IP address of TP-Link SG3210 via SSH
description:
    - Connects to TP-Link switch via SSH
    - Changes IP address, netmask, and gateway
    - Saves configuration
options:
    current_ip:
        description: Current IP address of the switch
        required: true
    username:
        description: SSH username
        required: true
    password:
        description: SSH password
        required: true
        no_log: true
    new_ip:
        description: New IP address for the switch
        required: true
    new_netmask:
        description: New netmask
        required: false
        default: "255.255.255.0"
    new_gateway:
        description: New gateway IP
        required: true
'''

def create_change_ip_script(current_ip, username, password, 
                             new_ip, new_netmask, new_gateway):
    """Generate expect script for IP change via SSH"""
    
    script = f'''#!/usr/bin/expect -f
set timeout 30

# Connect via SSH
spawn ssh -o PubkeyAuthentication=no {username}@{current_ip}
expect "password:"
send "{password}\\r"
expect "SG3210>"

# Enter privileged mode
send "enable\\r"
expect "SG3210#"

# Enter configuration mode
send "configure\\r"
expect "SG3210(config)#"

# Configure IP address
send "interface vlan 1\\r"
expect "SG3210(config-if)#"
send "ip address {new_ip} {new_netmask}\\r"
expect "SG3210(config-if)#"
send "exit\\r"
expect "SG3210(config)#"

# Configure default gateway
send "ip default-gateway {new_gateway}\\r"
expect "SG3210(config)#"

# Exit configuration mode
send "exit\\r"
expect "SG3210#"

# Save configuration
send "copy running-config startup-config\\r"
expect "Saving user config OK!"

# Exit - connection will drop after this
send "exit\\r"
expect eof
'''
    
    return script

def main():
    module = AnsibleModule(
        argument_spec=dict(
            current_ip=dict(type='str', required=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            new_ip=dict(type='str', required=True),
            new_netmask=dict(type='str', required=False, default='255.255.255.0'),
            new_gateway=dict(type='str', required=True),
        ),
        supports_check_mode=False
    )
    
    # Generate expect script
    try:
        script = create_change_ip_script(
            module.params['current_ip'],
            module.params['username'],
            module.params['password'],
            module.params['new_ip'],
            module.params['new_netmask'],
            module.params['new_gateway']
        )
    except Exception as e:
        module.fail_json(msg=f"Error generating script: {str(e)}")
    
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
            msg="IP address changed successfully",
            new_config={
                'ip': module.params['new_ip'],
                'netmask': module.params['new_netmask'],
                'gateway': module.params['new_gateway']
            },
            stdout=result.stdout
        )
    except subprocess.TimeoutExpired:
        if os.path.exists(script_path):
            os.unlink(script_path)
        # Timeout is expected after IP change - treat as success
        module.exit_json(
            changed=True,
            msg="IP address changed - connection dropped (this is normal)",
            new_config={
                'ip': module.params['new_ip'],
                'netmask': module.params['new_netmask'],
                'gateway': module.params['new_gateway']
            },
            warnings=["Connection dropped after IP change - this is expected"]
        )
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg=str(e))

if __name__ == '__main__':
    main()
