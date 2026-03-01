#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
TP-Link SG3452X Port Security Configuration Module

Configures MAC address-based port security on TP-Link SG3452X Managed Switches via SSH.

Features:
    - Limits the number of MAC addresses that can be learned on a port
    - Supports different learning modes (dynamic, static, permanent)
    - Supports different violation actions (forward, drop, disable)
    - Exceed notification when max MAC count is reached
    - Supports SFP+ ports 49-52 (ten-gigabitEthernet)

Parameters:
    host: Switch IP address
    username: SSH username
    password: SSH password
    port: Port number (1-52)
    max_mac_count: Maximum MAC addresses allowed (0-64, default: 1)
    mode: Learning mode - dynamic, static, permanent (default: dynamic)
    status: Violation action - forward, drop, disable (default: forward)
    exceed_notification: Enable notification on exceed (default: false)
    state: present or absent (default: present)
    hostname: CLI prompt hostname (default: SG3452X)
"""

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os

DOCUMENTATION = r'''
module: sg3452x_port_security_expect
short_description: Configure Port Security on TP-Link SG3452X switches
description:
    - Configures MAC address-based port security on TP-Link switches
    - Limits the number of MAC addresses that can be learned on a port
    - Supports different learning modes and violation actions
    - Supports SFP+ ports 49-52 (ten-gigabitEthernet)
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
        description: Port number (1-52)
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
        default: "SG3452X"
'''

EXAMPLES = r'''
# Enable port security with max 1 MAC address
- sg3452x_port_security_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    port: 2
    max_mac_count: 1
    mode: permanent
    status: drop
    exceed_notification: true

# Port security on SFP+ port
- sg3452x_port_security_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    port: 49
    max_mac_count: 5
    mode: dynamic
    status: forward

# Allow up to 5 MACs in dynamic mode
- sg3452x_port_security_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    port: 3
    max_mac_count: 5
    mode: dynamic
    status: forward

# Disable port security
- sg3452x_port_security_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    port: 2
    state: absent
'''


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


def create_port_security_script(host, username, password, port, 
                                 max_mac_count, mode, status, 
                                 exceed_notification, state, hostname):
    """Generate expect script for port security configuration with robust error handling"""
    
    # Get the correct interface type
    iface_type = get_interface_type(port)
    
    # Build configuration commands based on state
    if state == 'present':
        config_commands = f'''
# === CONFIGURE PORT SECURITY ===
# Configure max MAC count
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

# Configure learning mode
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

# Configure status/action
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

# Configure exceed notification
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
    else:  # state == 'absent'
        config_commands = f'''
# === DISABLE PORT SECURITY ===
# Disable port security
send "mac address-table max-mac-count status disable\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    timeout {{
        puts "ERROR_CONFIG_TIMEOUT: Timeout disabling port security"
        exit 1
    }}
}}

# Reset to defaults
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

# === INTERFACE MODE ===
send "interface {iface_type} 1/0/{port}\\r"
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

# === EXIT AND SAVE ===
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

# === LOGOUT ===
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
    
    if "SUCCESS_COMPLETE" in combined or "SUCCESS_CONFIG_SAVED" in combined:
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
            hostname=dict(type='str', required=False, default='SG3452X'),
        ),
        supports_check_mode=False
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
    if not 1 <= port <= 52:
        module.fail_json(msg=f"Port must be between 1 and 52, got {port}")
    
    # Validate max_mac_count
    if not 0 <= max_mac_count <= 64:
        module.fail_json(msg=f"max_mac_count must be between 0 and 64, got {max_mac_count}")
    
    # Generate expect script
    try:
        script = create_port_security_script(
            host, username, password, port,
            max_mac_count, mode, status,
            exceed_notification, state, hostname
        )
    except Exception as e:
        module.fail_json(msg=f"Error generating script: {str(e)}")
    
    # Run script
    try:
        stdout, stderr, returncode = run_expect_script(script, timeout=60)
    except subprocess.TimeoutExpired:
        module.fail_json(
            msg="Total timeout exceeded (60s) - switch not responding",
            host=host
        )
    except Exception as e:
        module.fail_json(msg=f"Unexpected error: {str(e)}", host=host)
    
    # Analyze output
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
    
    action = "configured" if state == 'present' else "disabled"
    
    module.exit_json(
        changed=True,
        msg=f"Port security {action} on port {port}",
        host=host,
        port_security={
            'port': port,
            'max_mac_count': max_mac_count,
            'mode': mode,
            'status': status,
            'exceed_notification': exceed_notification,
            'state': state
        },
        stdout=stdout
    )


if __name__ == '__main__':
    main()
