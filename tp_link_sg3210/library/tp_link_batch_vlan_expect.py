#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
TP-Link SG3210 Batch VLAN Configuration Module

Creates and manages VLANs on TP-Link SG3210 Managed Switches via SSH/expect.

Features:
    - Batch creation of multiple VLANs in one session
    - Mode 'add': Only adds new VLANs (no deletion)
    - Mode 'replace': Queries existing VLANs first, deletes non-protected ones, then creates new
    - Protected VLANs are never deleted (default: VLAN 1)
    - Supports both 'id' and 'vlan_id' field names
    - Supports tagged_ports and untagged_ports (port configuration)

Parameters:
    host: Switch IP address
    username: SSH username
    password: SSH password
    vlans: List of VLANs [{vlan_id: 10, name: "Management", tagged_ports: [1], untagged_ports: [2]}, ...]
    hostname: CLI prompt hostname (default: SG3210)
    mode: "replace" or "add" (default: add)
    protected_vlans: List of VLAN IDs that are never deleted (default: [1])

Example:
    - tp_link_batch_vlan_expect:
        host: "10.0.10.1"
        username: "admin"
        password: "secret"
        vlans:
          - vlan_id: 10
            name: "Management"
            tagged_ports: [1]
            untagged_ports: [2]
          - vlan_id: 20
            name: "Clients"
            tagged_ports: [1]
            untagged_ports: [3, 4, 5, 6, 7, 8]
        mode: "replace"
        protected_vlans: [1]
"""

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os
import re


DOCUMENTATION = r'''
module: tp_link_batch_vlan_expect
short_description: Batch VLAN configuration on TP-Link SG3210 switches
description:
    - Creates and manages VLANs on TP-Link SG3210 Managed Switches
    - Supports batch creation of multiple VLANs
    - Mode 'replace' queries existing VLANs and removes non-protected ones
    - Mode 'add' only adds VLANs without removing existing ones
    - Supports tagged/untagged port configuration
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
    vlans:
        description: List of VLANs to create, each with 'vlan_id' (or 'id'), 'name', optional 'tagged_ports', 'untagged_ports'
        required: true
        type: list
        elements: dict
    hostname:
        description: Switch hostname for expect prompts
        required: false
        default: "SG3210"
    mode:
        description: Operation mode - 'add' only adds, 'replace' removes non-protected VLANs first
        required: false
        default: "add"
        choices: ['add', 'replace']
    protected_vlans:
        description: List of VLAN IDs that should never be deleted
        required: false
        default: [1]
        type: list
        elements: int
'''

EXAMPLES = r'''
# Add VLANs with port configuration
- tp_link_batch_vlan_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    vlans:
      - vlan_id: 10
        name: "Management"
        tagged_ports: [1]
        untagged_ports: [2]
      - vlan_id: 20
        name: "Clients"
        tagged_ports: [1]
        untagged_ports: [3, 4, 5, 6, 7, 8]
    mode: add

# Replace VLANs (delete existing, then create new)
- tp_link_batch_vlan_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    vlans:
      - vlan_id: 10
        name: "Management"
      - vlan_id: 20
        name: "Clients"
      - vlan_id: 30
        name: "Servers"
    mode: replace
    protected_vlans: [1]
'''


def escape_vlan_name(name):
    """Escape special characters in VLAN name for expect script"""
    escaped = name.replace('\\', '')
    escaped = escaped.replace('"', '')
    escaped = escaped.replace("'", '')
    escaped = escaped.replace('$', '')
    escaped = escaped.replace('[', '')
    escaped = escaped.replace(']', '')
    escaped = escaped.replace('{', '')
    escaped = escaped.replace('}', '')
    return escaped[:32]


def get_vlan_id(vlan):
    """Get VLAN ID from dict, supporting both 'id' and 'vlan_id' field names"""
    if 'vlan_id' in vlan:
        return vlan['vlan_id']
    elif 'id' in vlan:
        return vlan['id']
    return None


def normalize_vlans(vlans):
    """Normalize VLAN list to use consistent 'id' field internally"""
    normalized = []
    for vlan in vlans:
        norm_vlan = {
            'id': get_vlan_id(vlan),
            'name': vlan.get('name', ''),
            'tagged_ports': vlan.get('tagged_ports', []),
            'untagged_ports': vlan.get('untagged_ports', []),
        }
        normalized.append(norm_vlan)
    return normalized


def validate_vlans(module, vlans, protected_vlans):
    """Validate VLAN list structure and values"""
    seen_ids = set()
    
    for i, vlan in enumerate(vlans):
        vlan_id = get_vlan_id(vlan)
        
        # Check required fields
        if vlan_id is None:
            module.fail_json(msg=f"VLAN #{i+1}: Missing required field 'vlan_id' or 'id'")
        if 'name' not in vlan:
            module.fail_json(msg=f"VLAN #{i+1} (ID {vlan_id}): Missing required field 'name'")
        
        vlan_name = vlan['name']
        
        # Validate VLAN ID type
        if not isinstance(vlan_id, int):
            module.fail_json(msg=f"VLAN #{i+1}: 'vlan_id' must be an integer, got {type(vlan_id).__name__}")
        
        # Validate VLAN ID range
        if not 1 <= vlan_id <= 4094:
            module.fail_json(msg=f"VLAN {vlan_id}: ID must be between 1 and 4094")
        
        # Check for duplicate VLAN IDs
        if vlan_id in seen_ids:
            module.fail_json(msg=f"VLAN {vlan_id}: Duplicate VLAN ID in list")
        seen_ids.add(vlan_id)
        
        # Validate VLAN name type
        if not isinstance(vlan_name, str):
            module.fail_json(msg=f"VLAN {vlan_id}: 'name' must be a string, got {type(vlan_name).__name__}")
        
        # Validate VLAN name not empty
        if not vlan_name.strip():
            module.fail_json(msg=f"VLAN {vlan_id}: 'name' cannot be empty")
        
        # Validate port lists if present
        for port_type in ['tagged_ports', 'untagged_ports']:
            if port_type in vlan:
                ports = vlan[port_type]
                if not isinstance(ports, list):
                    module.fail_json(msg=f"VLAN {vlan_id}: '{port_type}' must be a list")
                for port in ports:
                    if not isinstance(port, int) or port < 1 or port > 10:
                        module.fail_json(msg=f"VLAN {vlan_id}: Invalid port {port} in '{port_type}' (must be 1-10)")
        
        # Warn about protected VLANs in list
        if vlan_id in protected_vlans and vlan_id != 1:
            module.warn(f"VLAN {vlan_id} is in protected_vlans list and will be skipped")


def create_check_vlan_script(host, username, password, hostname):
    """Generate expect script to get current VLANs via 'show vlan'"""
    
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

send "terminal length 0\\r"
expect "{hostname}#"
send "show vlan\\r"
expect "{hostname}#"

send "exit\\r"
expect "{hostname}>"
send "exit\\r"
expect eof

puts "SUCCESS_CHECK_COMPLETE"
'''
    return script


def parse_existing_vlans(output):
    """Parse 'show vlan' output to get list of existing VLAN IDs"""
    existing_vlans = []
    pattern = r'^\s*(\d+)\s+\S+\s+(?:active|suspend|creating)'
    
    for line in output.split('\n'):
        match = re.match(pattern, line)
        if match:
            vlan_id = int(match.group(1))
            existing_vlans.append(vlan_id)
    
    return existing_vlans


def create_batch_vlan_script(host, username, password, vlans, hostname, mode, protected_vlans, vlans_to_delete):
    """Generate expect script for BATCH VLAN creation with port configuration"""
    
    # Generate delete commands
    delete_commands = ""
    if mode == "replace" and vlans_to_delete:
        for vlan_id in vlans_to_delete:
            delete_commands += f'''send "no vlan {vlan_id}\\r"
expect {{
    "{hostname}(config)#" {{}}
    "Invalid" {{
        puts "WARNING_DELETE_FAILED: Could not delete VLAN {vlan_id}"
    }}
    timeout {{
        puts "ERROR_DELETE_TIMEOUT: Timeout deleting VLAN {vlan_id}"
        exit 1
    }}
}}
'''
    
    # Generate create commands with port configuration
    create_commands = ""
    for vlan in vlans:
        if vlan['id'] not in protected_vlans:
            escaped_name = escape_vlan_name(vlan['name'])
            
            # Create VLAN and set name
            create_commands += f'''send "vlan {vlan['id']}\\r"
expect {{
    "{hostname}(config-vlan)#" {{}}
    "Invalid" {{
        puts "ERROR_INVALID_VLAN: Invalid VLAN ID {vlan['id']}"
        exit 1
    }}
    timeout {{
        puts "ERROR_VLAN_TIMEOUT: Timeout creating VLAN {vlan['id']}"
        exit 1
    }}
}}
send "name {escaped_name}\\r"
expect {{
    "{hostname}(config-vlan)#" {{}}
    "Invalid" {{
        puts "WARNING_NAME_FAILED: Could not set name for VLAN {vlan['id']}"
    }}
    timeout {{
        puts "ERROR_NAME_TIMEOUT: Timeout setting name for VLAN {vlan['id']}"
        exit 1
    }}
}}
send "exit\\r"
expect "{hostname}(config)#"
'''
    
    # Generate port configuration commands (TP-Link SG3210 syntax)
    # SG3210 uses:
    #   switchport general allowed vlan <id> tagged   - for trunk/tagged ports
    #   switchport general allowed vlan <id> untagged - for access/untagged ports
    #   switchport pvid <id>                          - sets PVID for untagged traffic
    port_commands = ""
    for vlan in vlans:
        vlan_id = vlan['id']
        tagged_ports = vlan.get('tagged_ports', [])
        untagged_ports = vlan.get('untagged_ports', [])
        
        # Configure tagged ports
        for port in tagged_ports:
            port_commands += f'''send "interface gigabitEthernet 1/0/{port}\\r"
expect "{hostname}(config-if)#"
send "switchport general allowed vlan {vlan_id} tagged\\r"
expect "{hostname}(config-if)#"
send "exit\\r"
expect "{hostname}(config)#"
'''
        
        # Configure untagged ports (also set PVID)
        for port in untagged_ports:
            port_commands += f'''send "interface gigabitEthernet 1/0/{port}\\r"
expect "{hostname}(config-if)#"
send "switchport general allowed vlan {vlan_id} untagged\\r"
expect "{hostname}(config-if)#"
send "switchport pvid {vlan_id}\\r"
expect "{hostname}(config-if)#"
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

# === DELETE PHASE ===
{delete_commands}

# === CREATE PHASE ===
{create_commands}

# === PORT CONFIGURATION PHASE ===
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
        "ERROR_AUTH_FAILED": "Authentication failed: Wrong username or password",
        "ERROR_ENABLE_PASSWORD": "Enable password required",
        "ERROR_ENABLE_TIMEOUT": "Timeout entering enable mode",
        "ERROR_CONFIG_TIMEOUT": "Timeout entering config mode",
        "ERROR_SAVE_TIMEOUT": "Timeout saving configuration",
        "ERROR_DELETE_TIMEOUT": "Timeout deleting VLAN",
        "ERROR_VLAN_TIMEOUT": "Timeout creating VLAN",
        "ERROR_NAME_TIMEOUT": "Timeout setting VLAN name",
        "ERROR_INVALID_VLAN": "Invalid VLAN ID",
    }
    
    combined = stdout + stderr
    
    for error_key, error_msg in error_patterns.items():
        if error_key in combined:
            return False, error_msg
    
    if "SUCCESS_COMPLETE" in combined or "SUCCESS_CONFIG_SAVED" in combined or "SUCCESS_CHECK_COMPLETE" in combined:
        return True, None
    
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
        if os.path.exists(script_path):
            os.unlink(script_path)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type='str', required=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            vlans=dict(type='list', required=True, elements='dict'),
            hostname=dict(type='str', required=False, default='SG3210'),
            mode=dict(type='str', required=False, default='add', choices=['add', 'replace']),
            protected_vlans=dict(type='list', required=False, default=[1], elements='int'),
        ),
        supports_check_mode=False
    )
    
    host = module.params['host']
    username = module.params['username']
    password = module.params['password']
    vlans_raw = module.params['vlans']
    hostname = module.params['hostname']
    mode = module.params['mode']
    protected_vlans = module.params['protected_vlans']
    
    # Validate VLAN list
    validate_vlans(module, vlans_raw, protected_vlans)
    
    # Normalize VLANs to use consistent 'id' field
    vlans = normalize_vlans(vlans_raw)
    
    # Extract target VLAN IDs
    target_vlan_ids = [v['id'] for v in vlans]
    
    # For mode=replace: First query existing VLANs
    vlans_to_delete = []
    existing_vlans = []
    
    if mode == "replace":
        check_script = create_check_vlan_script(host, username, password, hostname)
        
        try:
            stdout, stderr, returncode = run_expect_script(check_script, timeout=60)
        except subprocess.TimeoutExpired:
            module.fail_json(msg="Timeout querying VLANs", host=host)
        except Exception as e:
            module.fail_json(msg=f"Error querying VLANs: {str(e)}", host=host)
        
        success, error_msg = analyze_output(stdout, stderr)
        if not success:
            module.fail_json(
                msg=f"VLAN query failed: {error_msg}",
                host=host,
                stdout=stdout,
                stderr=stderr
            )
        
        existing_vlans = parse_existing_vlans(stdout)
        
        for vlan_id in existing_vlans:
            if vlan_id not in protected_vlans and vlan_id not in target_vlan_ids:
                vlans_to_delete.append(vlan_id)
    
    # Configure VLANs
    script = create_batch_vlan_script(
        host, username, password, vlans, hostname, mode, protected_vlans, vlans_to_delete
    )
    
    try:
        stdout, stderr, returncode = run_expect_script(script, timeout=180)
    except subprocess.TimeoutExpired:
        module.fail_json(
            msg="Total timeout exceeded (180s) - switch not responding",
            host=host
        )
    except Exception as e:
        module.fail_json(msg=f"Unexpected error: {str(e)}", host=host)
    
    success, error_msg = analyze_output(stdout, stderr)
    
    if not success:
        module.fail_json(
            msg=f"VLAN configuration failed: {error_msg}",
            host=host,
            stdout=stdout,
            stderr=stderr,
            return_code=returncode
        )
    
    vlans_created = len([v for v in vlans if v['id'] not in protected_vlans])
    vlans_deleted = len(vlans_to_delete)
    
    module.exit_json(
        changed=True,
        msg=f"Mode '{mode}': Created {vlans_created} VLANs" + (f", deleted {vlans_deleted} VLANs" if vlans_deleted > 0 else ""),
        host=host,
        mode=mode,
        vlans_created=vlans_created,
        vlans_deleted=vlans_deleted,
        vlans_deleted_ids=vlans_to_delete,
        existing_vlans_found=existing_vlans if mode == "replace" else [],
        target_vlans=target_vlan_ids,
        protected_vlans=protected_vlans,
        stdout=stdout
    )


if __name__ == '__main__':
    main()
