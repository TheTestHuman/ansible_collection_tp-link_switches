#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
TP-Link SG3452X LAG (Link Aggregation) Configuration Module

Configures Link Aggregation Groups on TP-Link SG3452X Managed Switches via SSH/expect.

Features:
    - Create LAG with multiple ports
    - LACP modes: active, passive, on (static)
    - Remove LAG configuration
    - Input validation and error handling
    - Supports SFP+ ports 49-52 (ten-gigabitEthernet)

Parameters:
    host: Switch IP address
    username: SSH username
    password: SSH password
    hostname: CLI prompt hostname (default: SG3452X)
    lag_id: LAG/Port-Channel ID (1-8)
    ports: List of ports for LAG (minimum 2)
    lacp_mode: LACP mode - active, passive, on (default: active)
    state: present or absent (default: present)
    max_port: Maximum port number on switch (default: 52)
"""

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os


DOCUMENTATION = r'''
module: sg3452x_lag_expect
short_description: Configure Link Aggregation Groups on TP-Link SG3452X switches
description:
    - Configures LAG (Link Aggregation Groups) on TP-Link SG3452X switches
    - Supports LACP modes active, passive, and static (on)
    - Supports SFP+ ports 49-52 (ten-gigabitEthernet)
    - Minimum 2 ports required for LAG
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
    hostname:
        description: Switch hostname for expect prompts
        required: false
        default: "SG3452X"
    lag_id:
        description: LAG/Port-Channel ID (1-8)
        required: true
        type: int
    ports:
        description: List of port numbers to include in LAG (minimum 2)
        required: true
        type: list
        elements: int
    lacp_mode:
        description: LACP mode - active (initiate), passive (respond), on (static/manual)
        required: false
        default: "active"
        choices: ['active', 'passive', 'on']
    state:
        description: Desired state of LAG
        required: false
        default: "present"
        choices: ['present', 'absent']
    max_port:
        description: Maximum port number on switch (for validation)
        required: false
        default: 52
        type: int
'''

EXAMPLES = r'''
# Create LAG with LACP active mode on copper ports
- sg3452x_lag_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    lag_id: 1
    ports: [47, 48]
    lacp_mode: active
    state: present

# Create LAG with SFP+ ports (49-52)
- sg3452x_lag_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    lag_id: 2
    ports: [49, 50]
    lacp_mode: active
    state: present

# Create static LAG (no LACP negotiation)
- sg3452x_lag_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    lag_id: 3
    ports: [7, 8]
    lacp_mode: "on"
    state: present

# Remove LAG
- sg3452x_lag_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    lag_id: 1
    ports: [47, 48]
    state: absent
'''


# Constants
MIN_LAG_ID = 1
MAX_LAG_ID = 8
MIN_PORT = 1
MIN_PORTS_IN_LAG = 2


def get_interface_type(port):
    """
    Determine the interface type based on port number.
    
    Ports 1-48: gigabitEthernet (Copper)
    Ports 49-52: ten-gigabitEthernet (SFP+)
    """
    if port >= 49:
        return "ten-gigabitEthernet"
    else:
        return "gigabitEthernet"


def validate_lag_config(module, lag_id, ports, max_port):
    """Validate LAG configuration parameters"""
    
    if not MIN_LAG_ID <= lag_id <= MAX_LAG_ID:
        module.fail_json(msg=f"LAG ID must be between {MIN_LAG_ID} and {MAX_LAG_ID}, got {lag_id}")
    
    if len(ports) < MIN_PORTS_IN_LAG:
        module.fail_json(msg=f"At least {MIN_PORTS_IN_LAG} ports required for LAG, got {len(ports)}")
    
    seen_ports = set()
    for port in ports:
        if port in seen_ports:
            module.fail_json(msg=f"Duplicate port {port} in ports list")
        seen_ports.add(port)
    
    for port in ports:
        if not isinstance(port, int):
            module.fail_json(msg=f"Port must be an integer, got {type(port).__name__}")
        if not MIN_PORT <= port <= max_port:
            module.fail_json(msg=f"Port {port} must be between {MIN_PORT} and {max_port}")


def create_lag_script(host, username, password, hostname, lag_id, ports, lacp_mode, state):
    """Generate expect script for LAG configuration with error handling"""
    
    port_commands = ""
    
    if state == 'present':
        for port in ports:
            iface_type = get_interface_type(port)
            port_commands += f'''
# === Add PORT {port} to LAG {lag_id} ===
send "interface {iface_type} 1/0/{port}\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    "Invalid" {{
        puts "ERROR_INVALID_PORT: Invalid port number {port}"
        exit 1
    }}
    timeout {{
        puts "ERROR_PORT_TIMEOUT: Timeout entering interface config for port {port}"
        exit 1
    }}
}}
send "channel-group {lag_id} mode {lacp_mode}\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    "already a member" {{
        puts "WARNING_PORT_IN_LAG: Port {port} is already a member of another LAG"
    }}
    "Invalid" {{
        puts "ERROR_LAG_COMMAND: Invalid LAG command for port {port}"
        exit 1
    }}
    "Error" {{
        puts "ERROR_LAG_FAILED: Failed to add port {port} to LAG {lag_id}"
        exit 1
    }}
    timeout {{
        puts "ERROR_LAG_TIMEOUT: Timeout adding port {port} to LAG {lag_id}"
        exit 1
    }}
}}
send "exit\\r"
expect "{hostname}(config)#"
'''
    elif state == 'absent':
        for port in ports:
            iface_type = get_interface_type(port)
            port_commands += f'''
# === Remove PORT {port} from LAG ===
send "interface {iface_type} 1/0/{port}\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    "Invalid" {{
        puts "ERROR_INVALID_PORT: Invalid port number {port}"
        exit 1
    }}
    timeout {{
        puts "ERROR_PORT_TIMEOUT: Timeout entering interface config for port {port}"
        exit 1
    }}
}}
send "no channel-group\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    "Invalid" {{
        puts "WARNING_NO_LAG: Port {port} was not in a LAG"
    }}
    timeout {{
        puts "ERROR_LAG_TIMEOUT: Timeout removing port {port} from LAG"
        exit 1
    }}
}}
send "exit\\r"
expect "{hostname}(config)#"
'''
    
    script = f'''#!/usr/bin/expect -f
set timeout 30
log_user 1

# === CONNECTION PHASE ===
spawn ssh -o StrictHostKeyChecking=no -o PubkeyAuthentication=no -o ConnectTimeout=20 {username}@{host}

expect {{
    "No route to host" {{
        puts "ERROR_CONNECTION_FAILED: No route to host {host}"
        exit 1
    }}
    "Connection refused" {{
        puts "ERROR_CONNECTION_REFUSED: Connection refused by {host}"
        exit 1
    }}
    "Connection timed out" {{
        puts "ERROR_CONNECTION_TIMEOUT: Connection to {host} timed out"
        exit 1
    }}
    "Host is unreachable" {{
        puts "ERROR_HOST_UNREACHABLE: Host {host} is unreachable"
        exit 1
    }}
    "Name or service not known" {{
        puts "ERROR_DNS_FAILED: Could not resolve hostname {host}"
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

# === LOGIN PHASE ===
expect {{
    "Permission denied" {{
        puts "ERROR_AUTH_FAILED: Authentication failed - wrong username or password"
        exit 1
    }}
    "Access denied" {{
        puts "ERROR_AUTH_FAILED: Access denied - wrong username or password"
        exit 1
    }}
    "{hostname}>" {{
        # Login successful
    }}
    timeout {{
        puts "ERROR_AUTH_FAILED: Login timeout - check username/password"
        exit 1
    }}
}}

# === ENABLE MODE ===
send "enable\\r"
expect {{
    "{hostname}#" {{}}
    "Password:" {{
        puts "ERROR_ENABLE_PASSWORD: Enable password required but not provided"
        exit 1
    }}
    timeout {{
        puts "ERROR_ENABLE_TIMEOUT: Timeout entering enable mode"
        exit 1
    }}
}}

# === CONFIGURE MODE ===
send "configure\\r"
expect {{
    "{hostname}(config)#" {{}}
    timeout {{
        puts "ERROR_CONFIG_TIMEOUT: Timeout entering config mode"
        exit 1
    }}
}}

# === LAG CONFIGURATION ===
{port_commands}

# === SAVE CONFIG ===
send "exit\\r"
expect "{hostname}#"
send "copy running-config startup-config\\r"

expect {{
    "Saving user config OK!" {{
        puts "SUCCESS_CONFIG_SAVED"
    }}
    "Succeed" {{
        puts "SUCCESS_CONFIG_SAVED"
    }}
    timeout {{
        puts "ERROR_SAVE_TIMEOUT: Timeout saving configuration"
        exit 1
    }}
}}

# === LOGOUT ===
send "exit\\r"
expect "{hostname}>"
send "exit\\r"
expect eof

puts "SUCCESS_COMPLETE"
'''
    return script


def analyze_output(stdout, stderr):
    """Analyze expect output for errors and return appropriate message"""
    
    error_patterns = {
        "ERROR_CONNECTION_FAILED": "Connection failed: No route to host",
        "ERROR_CONNECTION_REFUSED": "Connection refused: SSH port not open",
        "ERROR_CONNECTION_TIMEOUT": "Connection timeout: Host not responding",
        "ERROR_HOST_UNREACHABLE": "Host unreachable: Network problem",
        "ERROR_DNS_FAILED": "DNS resolution failed",
        "ERROR_AUTH_FAILED": "Authentication failed: Wrong username or password",
        "ERROR_ENABLE_PASSWORD": "Enable password required",
        "ERROR_ENABLE_TIMEOUT": "Timeout entering enable mode",
        "ERROR_CONFIG_TIMEOUT": "Timeout entering config mode",
        "ERROR_SAVE_TIMEOUT": "Timeout saving configuration",
        "ERROR_PORT_TIMEOUT": "Timeout during port configuration",
        "ERROR_INVALID_PORT": "Invalid port number",
        "ERROR_LAG_COMMAND": "Invalid LAG command",
        "ERROR_LAG_FAILED": "LAG configuration failed",
        "ERROR_LAG_TIMEOUT": "Timeout during LAG configuration",
    }
    
    combined = stdout + stderr
    
    for error_key, error_msg in error_patterns.items():
        if error_key in combined:
            return False, error_msg
    
    if "SUCCESS_COMPLETE" in combined or "SUCCESS_CONFIG_SAVED" in combined:
        return True, None
    
    if "Saving user config OK!" in combined:
        return True, None
    
    return False, "Unknown error - check stdout"


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
            hostname=dict(type='str', required=False, default='SG3452X'),
            lag_id=dict(type='int', required=True),
            ports=dict(type='list', required=True, elements='int'),
            lacp_mode=dict(type='str', required=False, default='active',
                          choices=['active', 'passive', 'on']),
            state=dict(type='str', required=False, default='present',
                      choices=['present', 'absent']),
            max_port=dict(type='int', required=False, default=52),
        ),
        supports_check_mode=False
    )
    
    host = module.params['host']
    username = module.params['username']
    password = module.params['password']
    hostname = module.params['hostname']
    lag_id = module.params['lag_id']
    ports = module.params['ports']
    lacp_mode = module.params['lacp_mode']
    state = module.params['state']
    max_port = module.params['max_port']
    
    validate_lag_config(module, lag_id, ports, max_port)
    
    try:
        script = create_lag_script(
            host, username, password, hostname, lag_id, ports, lacp_mode, state
        )
    except Exception as e:
        module.fail_json(msg=f"Error generating script: {str(e)}")
    
    try:
        stdout, stderr, returncode = run_expect_script(script, timeout=120)
    except subprocess.TimeoutExpired:
        module.fail_json(
            msg="Total timeout exceeded (120s) - switch not responding",
            host=host
        )
    except Exception as e:
        module.fail_json(msg=f"Unexpected error: {str(e)}", host=host)
    
    success, error_msg = analyze_output(stdout, stderr)
    
    if not success:
        module.fail_json(
            msg=f"LAG configuration failed: {error_msg}",
            host=host,
            lag_id=lag_id,
            stdout=stdout,
            stderr=stderr,
            return_code=returncode
        )
    
    warnings = []
    if "WARNING_PORT_IN_LAG" in stdout:
        warnings.append("One or more ports were already members of another LAG")
    if "WARNING_NO_LAG" in stdout:
        warnings.append("One or more ports were not in a LAG")
    
    action = "created" if state == 'present' else "removed"
    mode_desc = f" (mode: {lacp_mode})" if state == 'present' else ""
    
    result = {
        'changed': True,
        'msg': f"LAG {lag_id} {action} with ports {ports}{mode_desc}",
        'host': host,
        'lag_id': lag_id,
        'ports': ports,
        'lacp_mode': lacp_mode,
        'state': state,
        'stdout': stdout
    }
    
    if warnings:
        result['warnings'] = warnings
    
    module.exit_json(**result)


if __name__ == '__main__':
    main()
