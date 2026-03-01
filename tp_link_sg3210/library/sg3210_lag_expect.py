#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
TP-Link SG3210 LAG (Link Aggregation) Configuration Module (Idempotent)

Configures Link Aggregation Groups on TP-Link SG3210 Managed Switches via SSH/expect.

Features:
    - IDEMPOTENT: Only applies changes when configuration differs from desired state
    - Create LAG with multiple ports
    - LACP modes: active, passive, on (static)
    - Remove LAG configuration
    - Input validation and error handling

Parameters:
    host: Switch IP address
    username: SSH username
    password: SSH password
    hostname: CLI prompt hostname (default: SG3210)
    lag_id: LAG/Port-Channel ID (1-8)
    ports: List of ports for LAG (minimum 2)
    lacp_mode: LACP mode - active, passive, on (default: active)
    state: present or absent (default: present)
    max_port: Maximum port number on switch (default: 10)
"""

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os
import re


DOCUMENTATION = r'''
module: sg3210_lag_expect
short_description: Idempotent LAG configuration on TP-Link SG3210 switches
description:
    - Configures LAG (Link Aggregation Groups) on TP-Link SG3210 switches
    - IDEMPOTENT - only applies changes when needed (changed=false if config matches)
    - Supports LACP modes active, passive, and static (on)
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
        default: "SG3210"
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
        default: 10
        type: int
'''

EXAMPLES = r'''
# Create LAG with LACP active mode (idempotent)
- sg3210_lag_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    lag_id: 1
    ports: [9, 10]
    lacp_mode: active
    state: present

# Remove LAG
- sg3210_lag_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    lag_id: 1
    ports: [9, 10]
    state: absent
'''


# Constants
MIN_LAG_ID = 1
MAX_LAG_ID = 8
MIN_PORT = 1
MIN_PORTS_IN_LAG = 2


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


# =============================================================================
# IDEMPOTENCY FUNCTIONS
# =============================================================================

def parse_running_config_lags(output):
    """
    Parse 'show running-config' output to extract current LAG configuration.
    
    Returns:
        dict: {
            lag_id: {
                'ports': [port_numbers],
                'mode': 'active' | 'passive' | 'on'
            }
        }
    """
    lags = {}
    current_port = None
    
    lines = output.split('\n')
    
    for line in lines:
        line_stripped = line.strip()
        
        # Parse gigabitEthernet interface
        gi_match = re.match(r'^interface\s+gigabitEthernet\s+1/0/(\d+)', line_stripped)
        if gi_match:
            current_port = int(gi_match.group(1))
            continue
        
        # Parse channel-group command: "channel-group 1 mode active"
        if current_port and line_stripped.startswith('channel-group'):
            lag_match = re.match(r'channel-group\s+(\d+)\s+mode\s+(\w+)', line_stripped)
            if lag_match:
                lag_id = int(lag_match.group(1))
                mode = lag_match.group(2)
                
                if lag_id not in lags:
                    lags[lag_id] = {'ports': [], 'mode': mode}
                
                if current_port not in lags[lag_id]['ports']:
                    lags[lag_id]['ports'].append(current_port)
                
                lags[lag_id]['mode'] = mode
            continue
        
        # Reset context on interface boundary
        if line_stripped.startswith('#') or line_stripped == 'end':
            current_port = None
    
    # Sort port lists
    for lag_id in lags:
        lags[lag_id]['ports'] = sorted(lags[lag_id]['ports'])
    
    return lags


def calculate_lag_diff(current_lags, lag_id, desired_ports, desired_mode, state):
    """
    Calculate the difference between current and desired LAG configuration.
    """
    diff = {
        'needs_change': False,
        'ports_to_add': [],
        'ports_to_remove': [],
        'mode_change': False,
        'reasons': []
    }
    
    desired_ports_set = set(desired_ports)
    
    if state == 'present':
        if lag_id not in current_lags:
            diff['needs_change'] = True
            diff['ports_to_add'] = sorted(desired_ports)
            diff['reasons'].append(f"LAG {lag_id} does not exist")
        else:
            current = current_lags[lag_id]
            current_ports_set = set(current['ports'])
            current_mode = current['mode']
            
            missing_ports = desired_ports_set - current_ports_set
            if missing_ports:
                diff['needs_change'] = True
                diff['ports_to_add'] = sorted(missing_ports)
                diff['reasons'].append(f"Ports {sorted(missing_ports)} need to be added to LAG {lag_id}")
            
            extra_ports = current_ports_set - desired_ports_set
            if extra_ports:
                diff['needs_change'] = True
                diff['ports_to_remove'] = sorted(extra_ports)
                diff['reasons'].append(f"Ports {sorted(extra_ports)} need to be removed from LAG {lag_id}")
            
            if current_mode != desired_mode:
                diff['needs_change'] = True
                diff['mode_change'] = True
                diff['reasons'].append(f"LAG {lag_id} mode needs to change from {current_mode} to {desired_mode}")
    
    elif state == 'absent':
        if lag_id in current_lags:
            current = current_lags[lag_id]
            ports_in_lag = set(current['ports']) & desired_ports_set
            if ports_in_lag:
                diff['needs_change'] = True
                diff['ports_to_remove'] = sorted(ports_in_lag)
                diff['reasons'].append(f"Ports {sorted(ports_in_lag)} need to be removed from LAG {lag_id}")
    
    return diff


# =============================================================================
# EXPECT SCRIPT GENERATORS
# =============================================================================

def create_get_config_script(host, username, password, hostname):
    """Generate expect script to get running-config"""
    
    script = f'''#!/usr/bin/expect -f
set timeout 60
log_user 1

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
    "password:" {{
        send "{password}\\r"
    }}
    timeout {{
        puts "ERROR_CONNECTION_TIMEOUT: Timeout connecting to {host}"
        exit 1
    }}
}}

expect {{
    "Permission denied" {{
        puts "ERROR_AUTH_FAILED: Authentication failed"
        exit 1
    }}
    "{hostname}>" {{}}
    timeout {{
        puts "ERROR_AUTH_FAILED: Login timeout"
        exit 1
    }}
}}

send "enable\\r"
expect {{
    "{hostname}#" {{}}
    "Password:" {{
        puts "ERROR_ENABLE_PASSWORD: Enable password required"
        exit 1
    }}
    timeout {{
        puts "ERROR_ENABLE_TIMEOUT: Timeout entering enable mode"
        exit 1
    }}
}}

send "terminal length 0\\r"
expect "{hostname}#"

send "show running-config\\r"
expect "{hostname}#"

send "exit\\r"
expect "{hostname}>"
send "exit\\r"
expect eof

puts "SUCCESS_GET_CONFIG"
'''
    return script


def create_lag_config_script(host, username, password, hostname, lag_id, diff, lacp_mode):
    """Generate expect script for LAG configuration based on calculated diff"""
    
    port_commands = ""
    
    # Remove ports first
    for port in diff.get('ports_to_remove', []):
        port_commands += f'''
# === Remove PORT {port} from LAG ===
send "interface gigabitEthernet 1/0/{port}\\r"
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
    
    # Add ports
    for port in diff.get('ports_to_add', []):
        port_commands += f'''
# === Add PORT {port} to LAG {lag_id} ===
send "interface gigabitEthernet 1/0/{port}\\r"
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
    
    script = f'''#!/usr/bin/expect -f
set timeout 30
log_user 1

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
    "password:" {{
        send "{password}\\r"
    }}
    timeout {{
        puts "ERROR_CONNECTION_TIMEOUT: Timeout connecting to {host}"
        exit 1
    }}
}}

expect {{
    "Permission denied" {{
        puts "ERROR_AUTH_FAILED: Authentication failed"
        exit 1
    }}
    "{hostname}>" {{}}
    timeout {{
        puts "ERROR_AUTH_FAILED: Login timeout"
        exit 1
    }}
}}

send "enable\\r"
expect {{
    "{hostname}#" {{}}
    "Password:" {{
        puts "ERROR_ENABLE_PASSWORD: Enable password required"
        exit 1
    }}
    timeout {{
        puts "ERROR_ENABLE_TIMEOUT: Timeout entering enable mode"
        exit 1
    }}
}}

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

send "exit\\r"
expect "{hostname}>"
send "exit\\r"
expect eof

puts "SUCCESS_COMPLETE"
'''
    return script


def analyze_output(stdout, stderr):
    """Analyze expect output for errors"""
    
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
    
    if "SUCCESS_COMPLETE" in combined or "SUCCESS_CONFIG_SAVED" in combined or "SUCCESS_GET_CONFIG" in combined:
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
            hostname=dict(type='str', required=False, default='SG3210'),
            lag_id=dict(type='int', required=True),
            ports=dict(type='list', required=True, elements='int'),
            lacp_mode=dict(type='str', required=False, default='active',
                          choices=['active', 'passive', 'on']),
            state=dict(type='str', required=False, default='present',
                      choices=['present', 'absent']),
            max_port=dict(type='int', required=False, default=10),
        ),
        supports_check_mode=True
    )
    
    host = module.params['host']
    username = module.params['username']
    password = module.params['password']
    hostname = module.params['hostname']
    lag_id = module.params['lag_id']
    ports = sorted(module.params['ports'])
    lacp_mode = module.params['lacp_mode']
    state = module.params['state']
    max_port = module.params['max_port']
    
    validate_lag_config(module, lag_id, ports, max_port)
    
    # === STEP 1: Get current configuration ===
    get_config_script = create_get_config_script(host, username, password, hostname)
    
    try:
        stdout, stderr, returncode = run_expect_script(get_config_script, timeout=60)
    except subprocess.TimeoutExpired:
        module.fail_json(msg="Timeout getting current configuration", host=host)
    except Exception as e:
        module.fail_json(msg=f"Error getting configuration: {str(e)}", host=host)
    
    success, error_msg = analyze_output(stdout, stderr)
    if not success:
        module.fail_json(
            msg=f"Failed to get configuration: {error_msg}",
            host=host,
            stdout=stdout,
            stderr=stderr
        )
    
    # === STEP 2: Parse current LAG configuration ===
    current_lags = parse_running_config_lags(stdout)
    
    # === STEP 3: Calculate diff ===
    diff = calculate_lag_diff(current_lags, lag_id, ports, lacp_mode, state)
    
    # === STEP 4: Check if changes are needed ===
    if not diff['needs_change']:
        if state == 'present':
            msg = f"LAG {lag_id} already configured with ports {ports} (mode: {lacp_mode})"
        else:
            msg = f"LAG {lag_id} already absent or ports not in LAG"
        
        module.exit_json(
            changed=False,
            msg=msg,
            host=host,
            lag_id=lag_id,
            ports=ports,
            lacp_mode=lacp_mode,
            state=state,
            current_lags=current_lags,
        )
    
    # === STEP 5: Check mode (dry-run) ===
    if module.check_mode:
        module.exit_json(
            changed=True,
            msg=f"Would apply changes: {'; '.join(diff['reasons'])}",
            host=host,
            lag_id=lag_id,
            diff=diff,
        )
    
    # === STEP 6: Apply changes ===
    config_script = create_lag_config_script(
        host, username, password, hostname, lag_id, diff, lacp_mode
    )
    
    try:
        stdout, stderr, returncode = run_expect_script(config_script, timeout=120)
    except subprocess.TimeoutExpired:
        module.fail_json(msg="Total timeout exceeded (120s)", host=host)
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
    
    # === STEP 7: Report success ===
    warnings = []
    if "WARNING_PORT_IN_LAG" in stdout:
        warnings.append("One or more ports were already members of another LAG")
    if "WARNING_NO_LAG" in stdout:
        warnings.append("One or more ports were not in a LAG")
    
    action = "configured" if state == 'present' else "removed"
    
    result = {
        'changed': True,
        'msg': f"LAG {lag_id} {action}: {'; '.join(diff['reasons'])}",
        'host': host,
        'lag_id': lag_id,
        'ports': ports,
        'lacp_mode': lacp_mode,
        'state': state,
        'ports_added': diff.get('ports_to_add', []),
        'ports_removed': diff.get('ports_to_remove', []),
        'stdout': stdout
    }
    
    if warnings:
        result['warnings'] = warnings
    
    module.exit_json(**result)


if __name__ == '__main__':
    main()
