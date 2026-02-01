#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
TP-Link SG3210 Batch Port Configuration Module

Configures ports on TP-Link SG3210 Managed Switches via SSH/expect.

Features:
    - Batch configuration of multiple ports in one session
    - Trunk ports: Multiple VLANs tagged
    - Access ports: Single VLAN untagged + PVID
    - Mode 'add': Only adds VLAN memberships (no removal)
    - Mode 'replace': Removes all VLANs from port first, then configures

Parameters:
    host: Switch IP address
    username: SSH username
    password: SSH password
    hostname: CLI prompt hostname (default: SG3210)
    mode: "replace" or "add" (default: add)
    trunk_ports: List of trunk port configurations
        - port: Port number (1-10)
        - vlans: List of VLAN IDs (all tagged)
    access_ports: List of access port configurations
        - port: Port number (1-10)
        - vlan: VLAN ID (untagged + PVID)

Example:
    - tp_link_batch_port_expect:
        host: "10.0.10.1"
        username: "admin"
        password: "secret"
        mode: "replace"
        trunk_ports:
          - port: 1
            vlans: [1, 10, 20, 30, 40]
        access_ports:
          - port: 2
            vlan: 10
          - port: 3
            vlan: 20
"""

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os


DOCUMENTATION = r'''
module: tp_link_batch_port_expect
short_description: Batch port configuration on TP-Link SG3210 switches
description:
    - Configures trunk and access ports on TP-Link SG3210 switches
    - Supports batch configuration of multiple ports
    - Mode 'replace' removes existing VLAN memberships first
    - Mode 'add' only adds VLAN memberships
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
    mode:
        description: Operation mode - 'add' only adds, 'replace' removes VLANs first
        required: false
        default: "add"
        choices: ['add', 'replace']
    trunk_ports:
        description: List of trunk port configurations with 'port' and 'vlans'
        required: false
        default: []
        type: list
        elements: dict
    access_ports:
        description: List of access port configurations with 'port' and 'vlan'
        required: false
        default: []
        type: list
        elements: dict
'''

EXAMPLES = r'''
# Configure trunk and access ports
- tp_link_batch_port_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    mode: replace
    trunk_ports:
      - port: 1
        vlans: [1, 10, 20, 30, 40]
    access_ports:
      - port: 2
        vlan: 10
      - port: 3
        vlan: 20

# Add VLANs to ports (no removal)
- tp_link_batch_port_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    mode: add
    access_ports:
      - port: 4
        vlan: 30
      - port: 5
        vlan: 30

# Configure only trunk ports
- tp_link_batch_port_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    trunk_ports:
      - port: 9
        vlans: [1, 10, 20, 30, 40, 50]
      - port: 10
        vlans: [1, 10, 20, 30, 40, 50]
'''


# Constants
MIN_PORT = 1
MAX_PORT = 10
MIN_VLAN = 1
MAX_VLAN = 4094


def validate_port_configs(module, trunk_ports, access_ports):
    """Validate port configurations and check for conflicts"""
    
    all_ports = set()
    trunk_port_nums = set()
    access_port_nums = set()
    
    # Validate trunk ports
    for i, trunk in enumerate(trunk_ports):
        # Check required field 'port'
        if 'port' not in trunk:
            module.fail_json(msg=f"Trunk port #{i+1}: Missing required field 'port'")
        
        port_num = trunk['port']
        
        # Validate port number type
        if not isinstance(port_num, int):
            module.fail_json(msg=f"Trunk port #{i+1}: 'port' must be an integer, got {type(port_num).__name__}")
        
        # Validate port number range
        if not MIN_PORT <= port_num <= MAX_PORT:
            module.fail_json(msg=f"Trunk port {port_num}: Port must be between {MIN_PORT} and {MAX_PORT}")
        
        # Check for duplicate ports in trunk_ports
        if port_num in trunk_port_nums:
            module.fail_json(msg=f"Trunk port {port_num}: Duplicate port number in trunk_ports list")
        trunk_port_nums.add(port_num)
        all_ports.add(port_num)
        
        # Validate VLANs
        vlans = trunk.get('vlans', [])
        if not isinstance(vlans, list):
            module.fail_json(msg=f"Trunk port {port_num}: 'vlans' must be a list")
        
        for vlan_id in vlans:
            if not isinstance(vlan_id, int):
                module.fail_json(msg=f"Trunk port {port_num}: VLAN ID must be an integer, got {type(vlan_id).__name__}")
            if not MIN_VLAN <= vlan_id <= MAX_VLAN:
                module.fail_json(msg=f"Trunk port {port_num}: VLAN {vlan_id} must be between {MIN_VLAN} and {MAX_VLAN}")
    
    # Validate access ports
    for i, access in enumerate(access_ports):
        # Check required field 'port'
        if 'port' not in access:
            module.fail_json(msg=f"Access port #{i+1}: Missing required field 'port'")
        
        port_num = access['port']
        
        # Validate port number type
        if not isinstance(port_num, int):
            module.fail_json(msg=f"Access port #{i+1}: 'port' must be an integer, got {type(port_num).__name__}")
        
        # Validate port number range
        if not MIN_PORT <= port_num <= MAX_PORT:
            module.fail_json(msg=f"Access port {port_num}: Port must be between {MIN_PORT} and {MAX_PORT}")
        
        # Check for duplicate ports in access_ports
        if port_num in access_port_nums:
            module.fail_json(msg=f"Access port {port_num}: Duplicate port number in access_ports list")
        access_port_nums.add(port_num)
        
        # Check for port conflict (same port in trunk AND access)
        if port_num in trunk_port_nums:
            module.fail_json(msg=f"Port {port_num}: Cannot be configured as both trunk and access port")
        all_ports.add(port_num)
        
        # Validate VLAN (optional, defaults to 1)
        vlan_id = access.get('vlan', 1)
        if not isinstance(vlan_id, int):
            module.fail_json(msg=f"Access port {port_num}: 'vlan' must be an integer, got {type(vlan_id).__name__}")
        if not MIN_VLAN <= vlan_id <= MAX_VLAN:
            module.fail_json(msg=f"Access port {port_num}: VLAN {vlan_id} must be between {MIN_VLAN} and {MAX_VLAN}")
    
    return list(all_ports)


def create_batch_port_script(host, username, password, hostname, mode, trunk_ports, access_ports):
    """Generate expect script for BATCH port configuration with error handling"""
    
    port_commands = ""
    
    # Configure trunk ports
    for trunk in trunk_ports:
        port_num = trunk['port']
        vlans = trunk.get('vlans', [])
        
        port_commands += f'''
# === TRUNK PORT {port_num} ===
send "interface gigabitEthernet 1/0/{port_num}\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    "Invalid" {{
        puts "ERROR_INVALID_PORT: Invalid port number {port_num}"
        exit 1
    }}
    timeout {{
        puts "ERROR_PORT_TIMEOUT: Timeout entering interface config for port {port_num}"
        exit 1
    }}
}}
'''
        
        # For replace mode: Remove all VLANs first
        if mode == "replace":
            port_commands += f'''send "no switchport general allowed vlan all\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    timeout {{
        puts "ERROR_VLAN_TIMEOUT: Timeout removing VLANs from port {port_num}"
        exit 1
    }}
}}
'''
        
        # Add VLANs as tagged
        for vlan_id in vlans:
            port_commands += f'''send "switchport general allowed vlan {vlan_id} tagged\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    "Invalid" {{
        puts "WARNING_VLAN_FAILED: Could not add VLAN {vlan_id} to port {port_num}"
    }}
    timeout {{
        puts "ERROR_VLAN_TIMEOUT: Timeout adding VLAN {vlan_id} to port {port_num}"
        exit 1
    }}
}}
'''
        
        # Set PVID to VLAN 1 (standard for trunk)
        port_commands += f'''send "switchport pvid 1\\r"
expect "{hostname}(config-if)#"
send "exit\\r"
expect "{hostname}(config)#"
'''
    
    # Configure access ports
    for access in access_ports:
        port_num = access['port']
        vlan_id = access.get('vlan', 1)
        
        port_commands += f'''
# === ACCESS PORT {port_num} (VLAN {vlan_id}) ===
send "interface gigabitEthernet 1/0/{port_num}\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    "Invalid" {{
        puts "ERROR_INVALID_PORT: Invalid port number {port_num}"
        exit 1
    }}
    timeout {{
        puts "ERROR_PORT_TIMEOUT: Timeout entering interface config for port {port_num}"
        exit 1
    }}
}}
'''
        
        # For replace mode: Remove all VLANs first
        if mode == "replace":
            port_commands += f'''send "no switchport general allowed vlan all\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    timeout {{
        puts "ERROR_VLAN_TIMEOUT: Timeout removing VLANs from port {port_num}"
        exit 1
    }}
}}
'''
        
        # Add VLAN as untagged + set PVID
        port_commands += f'''send "switchport general allowed vlan {vlan_id} untagged\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    "Invalid" {{
        puts "ERROR_INVALID_VLAN: Invalid VLAN {vlan_id} for port {port_num}"
        exit 1
    }}
    timeout {{
        puts "ERROR_VLAN_TIMEOUT: Timeout adding VLAN {vlan_id} to port {port_num}"
        exit 1
    }}
}}
send "switchport pvid {vlan_id}\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    "Invalid" {{
        puts "ERROR_INVALID_PVID: Invalid PVID {vlan_id} for port {port_num}"
        exit 1
    }}
    timeout {{
        puts "ERROR_PVID_TIMEOUT: Timeout setting PVID on port {port_num}"
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

# === PORT CONFIGURATION ===
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
        "ERROR_INVALID_VLAN": "Invalid VLAN ID",
        "ERROR_INVALID_PVID": "Invalid PVID",
        "ERROR_VLAN_TIMEOUT": "Timeout configuring VLAN on port",
        "ERROR_PVID_TIMEOUT": "Timeout setting PVID",
    }
    
    ssh_errors = {
        "No route to host": "Connection failed: No route to host",
        "Connection refused": "Connection refused: SSH service not reachable",
        "Connection timed out": "Connection timeout: Host not responding",
        "Host is unreachable": "Host unreachable",
        "Permission denied": "Authentication failed: Wrong username or password",
    }
    
    combined = stdout + stderr
    
    # Check for our custom error markers first
    for error_key, error_msg in error_patterns.items():
        if error_key in combined:
            return False, error_msg
    
    # Check for raw SSH errors
    for ssh_error, error_msg in ssh_errors.items():
        if ssh_error in combined:
            return False, error_msg
    
    # Check for success
    if "SUCCESS_COMPLETE" in combined or "SUCCESS_CONFIG_SAVED" in combined:
        return True, None
    
    # Check for timeout markers
    if "TIMEOUT" in combined.upper():
        return False, "Timeout during configuration"
    
    # Fallback success check
    if "Saving user config OK!" in combined:
        return True, None
    
    return False, "Unknown error - check stdout"


def run_expect_script(script_content, timeout=180):
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
        # Cleanup is now in finally block - always executed
        if os.path.exists(script_path):
            os.unlink(script_path)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type='str', required=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            hostname=dict(type='str', required=False, default='SG3210'),
            mode=dict(type='str', required=False, default='add', choices=['add', 'replace']),
            trunk_ports=dict(type='list', required=False, default=[], elements='dict'),
            access_ports=dict(type='list', required=False, default=[], elements='dict'),
        ),
        supports_check_mode=False
    )
    
    host = module.params['host']
    username = module.params['username']
    password = module.params['password']
    hostname = module.params['hostname']
    mode = module.params['mode']
    trunk_ports = module.params['trunk_ports']
    access_ports = module.params['access_ports']
    
    # Validate that at least one port type is specified
    if not trunk_ports and not access_ports:
        module.fail_json(msg="At least one of trunk_ports or access_ports must be specified")
    
    # Validate port configurations
    all_ports = validate_port_configs(module, trunk_ports, access_ports)
    
    # Generate expect script
    try:
        script = create_batch_port_script(
            host, username, password, hostname, mode, trunk_ports, access_ports
        )
    except Exception as e:
        module.fail_json(msg=f"Error generating script: {str(e)}")
    
    # Run script
    try:
        stdout, stderr, returncode = run_expect_script(script, timeout=180)
    except subprocess.TimeoutExpired:
        module.fail_json(
            msg="Total timeout exceeded (180s) - switch not responding",
            host=host
        )
    except Exception as e:
        module.fail_json(msg=f"Unexpected error: {str(e)}", host=host)
    
    # Analyze output
    success, error_msg = analyze_output(stdout, stderr)
    
    if not success:
        module.fail_json(
            msg=f"Port configuration failed: {error_msg}",
            host=host,
            stdout=stdout,
            stderr=stderr,
            return_code=returncode
        )
    
    # Count operations
    trunk_count = len(trunk_ports)
    access_count = len(access_ports)
    
    module.exit_json(
        changed=True,
        msg=f"Mode '{mode}': Configured {trunk_count} trunk ports, {access_count} access ports",
        host=host,
        mode=mode,
        trunk_ports_configured=trunk_count,
        access_ports_configured=access_count,
        ports_configured=all_ports,
        stdout=stdout
    )


if __name__ == '__main__':
    main()
