#!/usr/bin/python
# -*- coding: utf-8 -*-

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os

DOCUMENTATION = r'''
module: tp_link_port_security_expect
short_description: Configure Port Security on TP-Link switches
description:
    - Configures MAC address-based port security on TP-Link switches
    - Limits the number of MAC addresses that can be learned on a port
    - Supports different learning modes and violation actions
    - Flexible prompts for different switch models
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
    max_mac_count:
        description: Maximum number of MAC addresses allowed (0-64)
        required: false
        default: 1
        type: int
    mode:
        description: MAC address learning mode
        required: false
        default: "dynamic"
        choices: ['dynamic', 'static', 'permanent']
    status:
        description: Port security status/action
        required: false
        default: "forward"
        choices: ['forward', 'drop', 'disable']
    exceed_notification:
        description: Enable notification when max MAC count is exceeded
        required: false
        default: false
        type: bool
    state:
        description: Desired state of port security
        required: false
        default: "present"
        choices: ['present', 'absent']
    hostname:
        description: Switch hostname for expect prompts
        required: false
        default: "SG3210"
    user_prompt:
        description: User mode prompt
        required: false
        default: ">"
    enable_prompt:
        description: Enable mode prompt
        required: false
        default: "#"
    config_prompt:
        description: Config mode prompt
        required: false
        default: "(config)#"
    interface_prompt:
        description: Interface config mode prompt
        required: false
        default: "(config-if)#"
    save_success_msg:
        description: Success message after saving config
        required: false
        default: "Saving user config OK!"
'''

EXAMPLES = r'''
# Enable port security with max 1 MAC address
- tp_link_port_security_expect:
    host: 10.0.10.1
    username: admin
    password: neinnein
    port: 2
    max_mac_count: 1
    mode: permanent
    status: drop
    exceed_notification: true

# Allow up to 5 MACs in dynamic mode
- tp_link_port_security_expect:
    host: 10.0.10.1
    username: admin
    password: neinnein
    port: 3
    max_mac_count: 5
    mode: dynamic
    status: forward

# Disable port security
- tp_link_port_security_expect:
    host: 10.0.10.1
    username: admin
    password: neinnein
    port: 2
    state: absent

# With custom hostname
- tp_link_port_security_expect:
    host: 10.0.20.1
    username: admin
    password: secret
    port: 5
    hostname: "OFFICE-SW1"
'''

def create_port_security_script(host, username, password, port, 
                                 max_mac_count, mode, status, 
                                 exceed_notification, state,
                                 hostname, user_prompt, enable_prompt,
                                 config_prompt, interface_prompt,
                                 save_success_msg):
    """Generate expect script for port security configuration"""
    
    script = f'''#!/usr/bin/expect -f
set timeout 30

# Connect via SSH
spawn ssh -o PubkeyAuthentication=no {username}@{host}
expect "password:"
send "{password}\\r"
expect "{hostname}{user_prompt}"

# Enter privileged mode
send "enable\\r"
expect "{hostname}{enable_prompt}"

# Enter configuration mode
send "configure\\r"
expect "{hostname}{config_prompt}"

# Configure interface
send "interface gigabitEthernet 1/0/{port}\\r"
expect "{hostname}{interface_prompt}"
'''

    if state == 'present':
        # Enable port security
        script += f'''
# Configure max MAC count
send "mac address-table max-mac-count max-number {max_mac_count}\\r"
expect "{hostname}{interface_prompt}"

# Configure learning mode
send "mac address-table max-mac-count mode {mode}\\r"
expect "{hostname}{interface_prompt}"

# Configure status/action
send "mac address-table max-mac-count status {status}\\r"
expect "{hostname}{interface_prompt}"

# Configure exceed notification
'''
        exceed_action = "enable" if exceed_notification else "disable"
        script += f'''send "mac address-table max-mac-count exceed-max-learned {exceed_action}\\r"
expect "{hostname}{interface_prompt}"
'''
    
    elif state == 'absent':
        # Disable port security
        script += f'''
# Disable port security
send "mac address-table max-mac-count status disable\\r"
expect "{hostname}{interface_prompt}"

# Reset to defaults
send "mac address-table max-mac-count max-number 64\\r"
expect "{hostname}{interface_prompt}"
send "mac address-table max-mac-count mode dynamic\\r"
expect "{hostname}{interface_prompt}"
send "mac address-table max-mac-count exceed-max-learned disable\\r"
expect "{hostname}{interface_prompt}"
'''

    # Exit and save
    script += f'''
# Exit interface configuration
send "exit\\r"
expect "{hostname}{config_prompt}"

# Exit configuration mode
send "exit\\r"
expect "{hostname}{enable_prompt}"

# Save configuration
send "copy running-config startup-config\\r"
expect "{save_success_msg}"

# Exit
send "exit\\r"
expect "{hostname}{user_prompt}"
send "exit\\r"
expect {{
    eof {{ }}
    "Connection closed" {{ }}
    timeout {{ }}
}}
'''
    
    return script

def main():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type='str', required=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            port=dict(type='int', required=True),
            max_mac_count=dict(type='int', required=False, default=1),
            mode=dict(type='str', required=False, default='dynamic',
                     choices=['dynamic', 'static', 'permanent']),
            status=dict(type='str', required=False, default='forward',
                       choices=['forward', 'drop', 'disable']),
            exceed_notification=dict(type='bool', required=False, default=False),
            state=dict(type='str', required=False, default='present',
                      choices=['present', 'absent']),
            # Flexible prompts
            hostname=dict(type='str', required=False, default='SG3210'),
            user_prompt=dict(type='str', required=False, default='>'),
            enable_prompt=dict(type='str', required=False, default='#'),
            config_prompt=dict(type='str', required=False, default='(config)#'),
            interface_prompt=dict(type='str', required=False, default='(config-if)#'),
            save_success_msg=dict(type='str', required=False, default='Saving user config OK!'),
        ),
        supports_check_mode=False
    )
    
    # Validate port
    if not 1 <= module.params['port'] <= 10:
        module.fail_json(msg="Port must be between 1 and 10")
    
    # Validate max_mac_count
    if not 0 <= module.params['max_mac_count'] <= 64:
        module.fail_json(msg="max_mac_count must be between 0 and 64")
    
    # Generate expect script
    try:
        script = create_port_security_script(
            module.params['host'],
            module.params['username'],
            module.params['password'],
            module.params['port'],
            module.params['max_mac_count'],
            module.params['mode'],
            module.params['status'],
            module.params['exceed_notification'],
            module.params['state'],
            module.params['hostname'],
            module.params['user_prompt'],
            module.params['enable_prompt'],
            module.params['config_prompt'],
            module.params['interface_prompt'],
            module.params['save_success_msg']
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
        
        # Check for errors
        if "error" in result.stdout.lower() or "bad command" in result.stdout.lower():
            if os.path.exists(script_path):
                os.unlink(script_path)
            module.fail_json(
                msg=f"Port security configuration failed on port {module.params['port']}",
                stdout=result.stdout
            )
        
        os.unlink(script_path)
        
        action = "configured" if module.params['state'] == 'present' else "disabled"
        
        module.exit_json(
            changed=True,
            msg=f"Port security {action} on port {module.params['port']}",
            port_security={
                'port': module.params['port'],
                'max_mac_count': module.params['max_mac_count'],
                'mode': module.params['mode'],
                'status': module.params['status'],
                'exceed_notification': module.params['exceed_notification'],
                'state': module.params['state']
            },
            stdout=result.stdout
        )
    except subprocess.TimeoutExpired:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg="Timeout during port security configuration - check switch connectivity")
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg=f"Port security configuration error: {str(e)}")

if __name__ == '__main__':
    main()
