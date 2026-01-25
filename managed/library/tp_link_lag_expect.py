#!/usr/bin/python
# -*- coding: utf-8 -*-

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os

DOCUMENTATION = r'''
module: tp_link_lag_expect
short_description: Configure Link Aggregation (LAG) on TP-Link switches
description:
    - Creates and manages Link Aggregation Groups (LAG/Port-Channel)
    - Supports LACP modes (active, passive, on)
    - Configures multiple ports into a single LAG
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
    lag_id:
        description: LAG/Port-Channel ID (1-8)
        required: true
        type: int
    ports:
        description: List of ports to add to LAG
        required: true
        type: list
    lacp_mode:
        description: LACP mode
        required: false
        default: "active"
        choices: ['active', 'passive', 'on']
    lacp_priority:
        description: LACP port priority (0-65535)
        required: false
        type: int
    state:
        description: Desired state of LAG
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
# Create LAG with LACP active mode
- tp_link_lag_expect:
    host: 10.0.10.1
    username: admin
    password: neinnein
    lag_id: 1
    ports: [9, 10]
    lacp_mode: active

# Create LAG with static mode
- tp_link_lag_expect:
    host: 10.0.10.1
    username: admin
    password: neinnein
    lag_id: 2
    ports: [5, 6, 7, 8]
    lacp_mode: on

# Remove LAG
- tp_link_lag_expect:
    host: 10.0.10.1
    username: admin
    password: neinnein
    lag_id: 1
    ports: [9, 10]
    state: absent
'''

def create_lag_script(host, username, password, lag_id, ports, lacp_mode, 
                      lacp_priority, state, hostname, user_prompt, enable_prompt,
                      config_prompt, interface_prompt, save_success_msg):
    """Generate expect script for LAG configuration"""
    
    script = f'''#!/usr/bin/expect -f
set timeout 60

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
'''

    if state == 'present':
        # Create LAG and add ports
        for port in ports:
            script += f'''
# Configure port {port} for LAG {lag_id}
send "interface gigabitEthernet 1/0/{port}\\r"
expect "{hostname}{interface_prompt}"
send "channel-group {lag_id} mode {lacp_mode}\\r"
expect "{hostname}{interface_prompt}"
'''
            if lacp_priority and lacp_mode in ['active', 'passive']:
                script += f'''send "lacp port-priority {lacp_priority}\\r"
expect "{hostname}{interface_prompt}"
'''
            script += f'''send "exit\\r"
expect "{hostname}{config_prompt}"
'''
        
        # Configure port-channel interface
        script += f'''
# Configure port-channel interface
send "interface port-channel {lag_id}\\r"
expect "{hostname}{interface_prompt}"
send "exit\\r"
expect "{hostname}{config_prompt}"
'''
    
    elif state == 'absent':
        # Remove ports from LAG
        for port in ports:
            script += f'''
# Remove port {port} from LAG {lag_id}
send "interface gigabitEthernet 1/0/{port}\\r"
expect "{hostname}{interface_prompt}"
send "no channel-group\\r"
expect "{hostname}{interface_prompt}"
send "exit\\r"
expect "{hostname}{config_prompt}"
'''

    # Exit and save
    script += f'''
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
            lag_id=dict(type='int', required=True),
            ports=dict(type='list', required=True, elements='int'),
            lacp_mode=dict(type='str', required=False, default='active',
                          choices=['active', 'passive', 'on']),
            lacp_priority=dict(type='int', required=False),
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
    
    # Validate LAG ID
    if not 1 <= module.params['lag_id'] <= 8:
        module.fail_json(msg="LAG ID must be between 1 and 8")
    
    # Validate ports
    for port in module.params['ports']:
        if not 1 <= port <= 10:
            module.fail_json(msg=f"Port {port} is invalid. Must be between 1 and 10")
    
    # Validate LACP priority
    if module.params['lacp_priority'] is not None:
        if not 0 <= module.params['lacp_priority'] <= 65535:
            module.fail_json(msg="LACP priority must be between 0 and 65535")
    
    # Generate expect script
    try:
        script = create_lag_script(
            module.params['host'],
            module.params['username'],
            module.params['password'],
            module.params['lag_id'],
            module.params['ports'],
            module.params['lacp_mode'],
            module.params['lacp_priority'],
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
        result = subprocess.run([script_path], capture_output=True, text=True, timeout=90)
        
        # Check for errors
        if "error" in result.stdout.lower() or "bad command" in result.stdout.lower():
            if os.path.exists(script_path):
                os.unlink(script_path)
            module.fail_json(
                msg=f"LAG configuration failed for LAG {module.params['lag_id']}",
                stdout=result.stdout
            )
        
        os.unlink(script_path)
        
        action = "configured" if module.params['state'] == 'present' else "removed"
        
        module.exit_json(
            changed=True,
            msg=f"LAG {module.params['lag_id']} {action} with ports {module.params['ports']}",
            lag_config={
                'lag_id': module.params['lag_id'],
                'ports': module.params['ports'],
                'lacp_mode': module.params['lacp_mode'],
                'state': module.params['state']
            },
            stdout=result.stdout
        )
    except subprocess.TimeoutExpired:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg="Timeout during LAG configuration - check switch connectivity")
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg=f"LAG configuration error: {str(e)}")

if __name__ == '__main__':
    main()
