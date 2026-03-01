#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
TP-Link SG3210 Port Security Configuration Module (Idempotent)

Configures MAC address-based port security on TP-Link SG3210 Managed Switches via SSH.

Features:
    - IDEMPOTENT: Only applies changes when configuration differs from desired state
    - Limits the number of MAC addresses that can be learned on a port
    - Supports different learning modes (dynamic, static, permanent)
    - Supports different violation actions (forward, drop, disable)
    - Exceed notification when max MAC count is reached

Parameters:
    host: Switch IP address
    username: SSH username
    password: SSH password
    port: Port number (1-10)
    max_mac_count: Maximum MAC addresses allowed (0-64, default: 1)
    mode: Learning mode - dynamic, static, permanent (default: dynamic)
    status: Violation action - forward, drop, disable (default: forward)
    exceed_notification: Enable notification on exceed (default: false)
    state: present or absent (default: present)
    hostname: CLI prompt hostname (default: SG3210)
"""

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os
import re

DOCUMENTATION = r'''
module: sg3210_port_security_expect
short_description: Idempotent Port Security configuration on TP-Link SG3210 switches
description:
    - Configures MAC address-based port security on TP-Link switches
    - IDEMPOTENT - only applies changes when needed (changed=false if config matches)
    - Limits the number of MAC addresses that can be learned on a port
    - Supports different learning modes and violation actions
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
        description: Port security status/action on violation
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
'''

EXAMPLES = r'''
# Enable port security (idempotent)
- sg3210_port_security_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    port: 2
    max_mac_count: 1
    mode: permanent
    status: drop
    exceed_notification: true

# Disable port security
- sg3210_port_security_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    port: 2
    state: absent
'''


# =============================================================================
# IDEMPOTENCY FUNCTIONS
# =============================================================================

def parse_running_config_port_security(output, target_port):
    """
    Parse 'show running-config' output to extract port security configuration.
    
    The switch outputs port security in a single line format:
    mac address-table max-mac-count max-number 1 mode permanent status drop exceed-max-learned enable
    
    All parameters are optional except max-number when configured.
    Default values if not present in config:
    - mode: dynamic
    - status: forward  
    - exceed-max-learned: disable (False)
    """
    config = {
        'max_mac_count': 64,
        'mode': 'dynamic',
        'status': 'forward',
        'exceed_notification': False,
        'configured': False
    }
    
    current_port = None
    in_target_port = False
    
    lines = output.split('\n')
    
    for line in lines:
        line_stripped = line.strip()
        
        # Parse gigabitEthernet interface
        gi_match = re.match(r'^interface\s+gigabitEthernet\s+1/0/(\d+)', line_stripped)
        if gi_match:
            current_port = int(gi_match.group(1))
            in_target_port = (current_port == target_port)
            continue
        
        # Parse port security config only for target port
        # Format: mac address-table max-mac-count max-number X [mode Y] [status Z] [exceed-max-learned enable/disable]
        if in_target_port and line_stripped.startswith('mac address-table max-mac-count'):
            config['configured'] = True
            
            # Parse max-number (required when configured)
            max_match = re.search(r'max-number\s+(\d+)', line_stripped)
            if max_match:
                config['max_mac_count'] = int(max_match.group(1))
            
            # Parse mode (optional, default: dynamic)
            mode_match = re.search(r'\bmode\s+(dynamic|static|permanent)\b', line_stripped)
            if mode_match:
                config['mode'] = mode_match.group(1)
            
            # Parse status (optional, default: forward)
            status_match = re.search(r'\bstatus\s+(forward|drop|disable)\b', line_stripped)
            if status_match:
                config['status'] = status_match.group(1)
            
            # Parse exceed-max-learned (optional, default: disable)
            exceed_match = re.search(r'exceed-max-learned\s+(enable|disable)', line_stripped)
            if exceed_match:
                config['exceed_notification'] = (exceed_match.group(1) == 'enable')
            
            continue
        
        # Reset context on next interface
        if line_stripped.startswith('interface ') and current_port == target_port:
            break
        if line_stripped.startswith('#') and in_target_port:
            break
    
    return config


def calculate_port_security_diff(current_config, desired_config, state):
    """Calculate the difference between current and desired configuration."""
    diff = {
        'needs_change': False,
        'reasons': []
    }
    
    if state == 'present':
        if current_config['max_mac_count'] != desired_config['max_mac_count']:
            diff['needs_change'] = True
            diff['reasons'].append(
                f"max_mac_count: {current_config['max_mac_count']} -> {desired_config['max_mac_count']}"
            )
        
        if current_config['mode'] != desired_config['mode']:
            diff['needs_change'] = True
            diff['reasons'].append(
                f"mode: {current_config['mode']} -> {desired_config['mode']}"
            )
        
        if current_config['status'] != desired_config['status']:
            diff['needs_change'] = True
            diff['reasons'].append(
                f"status: {current_config['status']} -> {desired_config['status']}"
            )
        
        if current_config['exceed_notification'] != desired_config['exceed_notification']:
            diff['needs_change'] = True
            diff['reasons'].append(
                f"exceed_notification: {current_config['exceed_notification']} -> {desired_config['exceed_notification']}"
            )
    
    elif state == 'absent':
        if current_config['configured'] and current_config['status'] != 'disable':
            diff['needs_change'] = True
            diff['reasons'].append("Port security needs to be disabled")
    
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


def create_port_security_script(host, username, password, port, 
                                 max_mac_count, mode, status, 
                                 exceed_notification, state, hostname):
    """Generate expect script for port security configuration"""
    
    if state == 'present':
        config_commands = f'''
# === CONFIGURE PORT SECURITY ===
send "mac address-table max-mac-count max-number {max_mac_count}\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    "Invalid" {{
        puts "ERROR_INVALID_COMMAND: Invalid max-mac-count value"
        exit 1
    }}
    timeout {{
        puts "ERROR_CONFIG_TIMEOUT: Timeout configuring max-mac-count"
        exit 1
    }}
}}

send "mac address-table max-mac-count mode {mode}\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    "Invalid" {{
        puts "ERROR_INVALID_COMMAND: Invalid mode value"
        exit 1
    }}
    timeout {{
        puts "ERROR_CONFIG_TIMEOUT: Timeout configuring mode"
        exit 1
    }}
}}

send "mac address-table max-mac-count status {status}\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    "Invalid" {{
        puts "ERROR_INVALID_COMMAND: Invalid status value"
        exit 1
    }}
    timeout {{
        puts "ERROR_CONFIG_TIMEOUT: Timeout configuring status"
        exit 1
    }}
}}

send "mac address-table max-mac-count exceed-max-learned {'enable' if exceed_notification else 'disable'}\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    "Invalid" {{
        puts "ERROR_INVALID_COMMAND: Invalid exceed-max-learned value"
        exit 1
    }}
    timeout {{
        puts "ERROR_CONFIG_TIMEOUT: Timeout configuring exceed notification"
        exit 1
    }}
}}
'''
    else:
        config_commands = f'''
# === DISABLE PORT SECURITY ===
send "mac address-table max-mac-count status disable\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    timeout {{
        puts "ERROR_CONFIG_TIMEOUT: Timeout disabling port security"
        exit 1
    }}
}}

send "mac address-table max-mac-count max-number 64\\r"
expect "{hostname}(config-if)#"

send "mac address-table max-mac-count mode dynamic\\r"
expect "{hostname}(config-if)#"

send "mac address-table max-mac-count exceed-max-learned disable\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    timeout {{
        puts "ERROR_CONFIG_TIMEOUT: Timeout resetting to defaults"
        exit 1
    }}
}}
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

send "interface gigabitEthernet 1/0/{port}\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    "Invalid" {{
        puts "ERROR_INVALID_PORT: Invalid port number {port}"
        exit 1
    }}
    timeout {{
        puts "ERROR_INTERFACE_TIMEOUT: Timeout entering interface config for port {port}"
        exit 1
    }}
}}

{config_commands}

send "exit\\r"
expect "{hostname}(config)#"

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
expect {{
    eof {{}}
    "Connection closed" {{}}
    timeout {{}}
}}

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
        "ERROR_CONFIG_TIMEOUT": "Timeout during configuration",
        "ERROR_INTERFACE_TIMEOUT": "Timeout entering interface config",
        "ERROR_INVALID_PORT": "Invalid port number",
        "ERROR_INVALID_COMMAND": "Invalid command or parameter",
        "ERROR_SAVE_TIMEOUT": "Timeout saving configuration",
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


def run_expect_script(script_content, timeout=60):
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
            port=dict(type='int', required=True),
            max_mac_count=dict(type='int', required=False, default=1),
            mode=dict(type='str', required=False, default='dynamic',
                     choices=['dynamic', 'static', 'permanent']),
            status=dict(type='str', required=False, default='forward',
                       choices=['forward', 'drop', 'disable']),
            exceed_notification=dict(type='bool', required=False, default=False),
            state=dict(type='str', required=False, default='present',
                      choices=['present', 'absent']),
            hostname=dict(type='str', required=False, default='SG3210'),
        ),
        supports_check_mode=True
    )
    
    host = module.params['host']
    username = module.params['username']
    password = module.params['password']
    port = module.params['port']
    max_mac_count = module.params['max_mac_count']
    mode = module.params['mode']
    status = module.params['status']
    exceed_notification = module.params['exceed_notification']
    state = module.params['state']
    hostname = module.params['hostname']
    
    # Validate port
    if not 1 <= port <= 10:
        module.fail_json(msg=f"Port must be between 1 and 10, got {port}")
    
    # Validate max_mac_count
    if not 0 <= max_mac_count <= 64:
        module.fail_json(msg=f"max_mac_count must be between 0 and 64, got {max_mac_count}")
    
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
    
    # === STEP 2: Parse current port security configuration ===
    current_config = parse_running_config_port_security(stdout, port)
    
    # === STEP 3: Build desired configuration ===
    desired_config = {
        'max_mac_count': max_mac_count,
        'mode': mode,
        'status': status,
        'exceed_notification': exceed_notification,
    }
    
    # === STEP 4: Calculate diff ===
    diff = calculate_port_security_diff(current_config, desired_config, state)
    
    # === STEP 5: Check if changes are needed ===
    if not diff['needs_change']:
        if state == 'present':
            msg = f"Port {port} security already configured as desired"
        else:
            msg = f"Port {port} security already disabled"
        
        module.exit_json(
            changed=False,
            msg=msg,
            host=host,
            port=port,
            current_config=current_config,
        )
    
    # === STEP 6: Check mode (dry-run) ===
    if module.check_mode:
        module.exit_json(
            changed=True,
            msg=f"Would apply changes: {'; '.join(diff['reasons'])}",
            host=host,
            port=port,
            diff=diff,
        )
    
    # === STEP 7: Apply changes ===
    try:
        script = create_port_security_script(
            host, username, password, port,
            max_mac_count, mode, status,
            exceed_notification, state, hostname
        )
    except Exception as e:
        module.fail_json(msg=f"Error generating script: {str(e)}")
    
    try:
        stdout, stderr, returncode = run_expect_script(script, timeout=60)
    except subprocess.TimeoutExpired:
        module.fail_json(msg="Total timeout exceeded (60s)", host=host)
    except Exception as e:
        module.fail_json(msg=f"Unexpected error: {str(e)}", host=host)
    
    success, error_msg = analyze_output(stdout, stderr)
    
    if not success:
        module.fail_json(
            msg=f"Port security configuration failed: {error_msg}",
            host=host,
            port=port,
            stdout=stdout,
            stderr=stderr,
            return_code=returncode
        )
    
    # === STEP 8: Report success ===
    action = "configured" if state == 'present' else "disabled"
    
    module.exit_json(
        changed=True,
        msg=f"Port {port} security {action}: {'; '.join(diff['reasons'])}",
        host=host,
        port_security={
            'port': port,
            'max_mac_count': max_mac_count,
            'mode': mode,
            'status': status,
            'exceed_notification': exceed_notification,
            'state': state
        },
        changes=diff['reasons'],
        stdout=stdout
    )


if __name__ == '__main__':
    main()
