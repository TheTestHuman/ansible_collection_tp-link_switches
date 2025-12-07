#!/usr/bin/python
# -*- coding: utf-8 -*-

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os

DOCUMENTATION = r'''
module: tp_link_take_ownership
short_description: Initial configuration of factory-reset TP-Link SG3210 via Telnet
description:
    - Connects to a factory-reset TP-Link switch via Telnet
    - Sets the admin password
    - Configures IP address, netmask, and gateway
    - Enables SSH server
    - Saves configuration
options:
    default_ip:
        description: Default IP address of factory-reset switch
        required: false
        default: "192.168.0.1"
    default_user:
        description: Default username
        required: false
        default: "admin"
    default_password:
        description: Default password
        required: false
        default: "admin"
    new_password:
        description: New admin password to set
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
    enable_ssh:
        description: Enable SSH server
        required: false
        default: true
        type: bool
'''

def create_take_ownership_script(default_ip, default_user, default_password, 
                                  new_password, new_ip, new_netmask, new_gateway, 
                                  enable_ssh):
    """Generate expect script for initial switch configuration via Telnet"""
    
    script = f'''#!/usr/bin/expect -f
set timeout 30

# Connect via Telnet
spawn telnet {default_ip}
expect "User:"
send "{default_user}\\r"
expect "Password:"
send "{default_password}\\r"

# Handle password change prompt
expect "Change now? \\[Y/N\\]:"
send "Y\\r"
expect "Please enter the new password:"
send "{new_password}\\r"
expect "Please confirm new password again:"
send "{new_password}\\r"

# Wait for confirmation message and press ENTER
expect "Please Press ENTER."
send "\\r"

# Wait for prompt after password change
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
'''

    # Enable SSH if requested
    if enable_ssh:
        script += '''
# Enable SSH server
send "ip ssh server\\r"
expect "SG3210(config)#"
'''

    # Save configuration and exit
    script += '''
# Exit configuration mode
send "exit\\r"
expect "SG3210#"

# Save configuration
send "copy running-config startup-config\\r"
expect "OK!"

# Exit
send "exit\\r"
expect eof
'''
    
    return script

def main():
    module = AnsibleModule(
        argument_spec=dict(
            default_ip=dict(type='str', required=False, default='192.168.0.1'),
            default_user=dict(type='str', required=False, default='admin'),
            default_password=dict(type='str', required=False, default='admin', no_log=True),
            new_password=dict(type='str', required=True, no_log=True),
            new_ip=dict(type='str', required=True),
            new_netmask=dict(type='str', required=False, default='255.255.255.0'),
            new_gateway=dict(type='str', required=True),
            enable_ssh=dict(type='bool', required=False, default=True),
        ),
        supports_check_mode=False
    )
    
    # Generate expect script
    try:
        script = create_take_ownership_script(
            module.params['default_ip'],
            module.params['default_user'],
            module.params['default_password'],
            module.params['new_password'],
            module.params['new_ip'],
            module.params['new_netmask'],
            module.params['new_gateway'],
            module.params['enable_ssh']
        )
    except Exception as e:
        module.fail_json(msg=f"Error generating script: {str(e)}")
    
    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.exp', delete=False) as f:
        f.write(script)
        script_path = f.name
    
    try:
        os.chmod(script_path, 0o700)
        result = subprocess.run([script_path], capture_output=True, text=True, timeout=90)
        
        os.unlink(script_path)
        
        module.exit_json(
            changed=True,
            msg="Switch configured successfully",
            new_config={
                'ip': module.params['new_ip'],
                'netmask': module.params['new_netmask'],
                'gateway': module.params['new_gateway'],
                'ssh_enabled': module.params['enable_ssh']
            },
            stdout=result.stdout
        )
    except subprocess.TimeoutExpired:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg="Timeout during configuration - switch may have rebooted or IP changed")
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg=str(e))

if __name__ == '__main__':
    main()
