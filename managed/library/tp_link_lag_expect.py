#!/usr/bin/python
# -*- coding: utf-8 -*-

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os

DOCUMENTATION = r'''
module: tp_link_lag_expect
short_description: Configure Link Aggregation (LAG/Port-Channel) on TP-Link SG3210
description:
    - Creates or modifies Link Aggregation Groups (LAG) on TP-Link switches
    - Supports LACP modes: active, passive, or on (static)
    - Configures multiple ports into a single port-channel
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
        description: LAG/Port-Channel group number (1-8)
        required: true
        type: int
    ports:
        description: List of ports to add to the LAG (e.g., [9, 10])
        required: true
        type: list
    mode:
        description: LACP mode
        required: false
        default: "active"
        choices: ['active', 'passive', 'on']
    lacp_priority:
        description: LACP port priority (0-65535)
        required: false
        type: int
    state:
        description: Desired state of the LAG
        required: false
        default: "present"
        choices: ['present', 'absent']
'''

def create_lag_expect_script(host, username, password, lag_id, ports, mode, 
                              lacp_priority=None, state='present'):
    """Generate expect script for LAG configuration"""
    
    script = f'''#!/usr/bin/expect -f
set timeout 30

# Connect via SSH
spawn ssh -o PubkeyAuthentication=no {username}@{host}
expect "password:"
send "{password}\\r"
expect "SG3210>"

# Enter privileged mode
send "enable\\r"
expect "SG3210#"

# Enter configuration mode
send "configure\\r"
expect "SG3210(config)#"
'''

    if state == 'present':
        # Add each port to the LAG
        for port in ports:
            script += f'''
# Configure port {port}
send "interface gigabitEthernet 1/0/{port}\\r"
expect "SG3210(config-if)#"
send "channel-group {lag_id} mode {mode}\\r"
expect "SG3210(config-if)#"
'''
            # Set LACP priority if specified
            if lacp_priority is not None and mode in ['active', 'passive']:
                script += f'''send "lacp port-priority {lacp_priority}\\r"
expect "SG3210(config-if)#"
'''
            script += f'''send "exit\\r"
expect "SG3210(config)#"
'''
    
    elif state == 'absent':
        # Remove each port from the LAG
        for port in ports:
            script += f'''
# Remove port {port} from LAG
send "interface gigabitEthernet 1/0/{port}\\r"
expect "SG3210(config-if)#"
send "no channel-group {lag_id}\\r"
expect "SG3210(config-if)#"
send "exit\\r"
expect "SG3210(config)#"
'''

    # Exit and save
    script += '''
# Exit configuration mode
send "exit\\r"
expect "SG3210#"

# Save configuration
send "copy running-config startup-config\\r"
expect "Saving user config OK!"

# Exit
send "exit\\r"
expect "SG3210>"
send "exit\\r"
expect {
    eof { }
    "Connection closed" { }
    timeout { }
}
'''
    
    return script

def main():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type='str', required=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            lag_id=dict(type='int', required=True),
            ports=dict(type='list', elements='int', required=True),
            mode=dict(type='str', required=False, default='active', 
                     choices=['active', 'passive', 'on']),
            lacp_priority=dict(type='int', required=False),
            state=dict(type='str', required=False, default='present',
                      choices=['present', 'absent']),
        ),
        supports_check_mode=False
    )
    
    # Validate LAG ID
    if not 1 <= module.params['lag_id'] <= 8:
        module.fail_json(msg="lag_id must be between 1 and 8")
    
    # Validate ports
    for port in module.params['ports']:
        if not 1 <= port <= 10:
            module.fail_json(msg=f"Port {port} is invalid. Must be between 1 and 10")
    
    # Generate expect script
    try:
        script = create_lag_expect_script(
            module.params['host'],
            module.params['username'],
            module.params['password'],
            module.params['lag_id'],
            module.params['ports'],
            module.params['mode'],
            module.params.get('lacp_priority'),
            module.params['state']
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
        
        action = "configured" if module.params['state'] == 'present' else "removed"
        
        module.exit_json(
            changed=True,
            msg=f"LAG {module.params['lag_id']} {action} successfully",
            lag={
                'lag_id': module.params['lag_id'],
                'ports': module.params['ports'],
                'mode': module.params['mode'],
                'state': module.params['state']
            },
            stdout=result.stdout
        )
    except subprocess.TimeoutExpired:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg="Timeout during LAG configuration")
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg=str(e))

if __name__ == '__main__':
    main()
