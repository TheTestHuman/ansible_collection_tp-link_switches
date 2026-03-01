#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
TP-Link SG3210 Batch VLAN Configuration Module (Idempotent)

Creates and manages VLANs on TP-Link SG3210 Managed Switches via SSH/expect.

Features:
    - IDEMPOTENT: Only applies changes when configuration differs from desired state
    - Batch creation of multiple VLANs in one session
    - Mode 'add': Only adds new VLANs/ports (no deletion)
    - Mode 'replace': Queries existing config, removes non-protected VLANs, then creates new
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
"""

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os
import re


DOCUMENTATION = r'''
module: tp_link_batch_vlan_expect
short_description: Idempotent batch VLAN configuration on TP-Link SG3210 switches
description:
    - Creates and manages VLANs on TP-Link SG3210 Managed Switches
    - IDEMPOTENT - only applies changes when needed (changed=false if config matches)
    - Supports batch creation of multiple VLANs
    - Mode 'replace' queries existing config and removes non-protected VLANs
    - Mode 'add' only adds VLANs/ports without removing existing ones
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
# Add VLANs with port configuration (idempotent)
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
'''


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

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
            'tagged_ports': sorted(vlan.get('tagged_ports', [])),
            'untagged_ports': sorted(vlan.get('untagged_ports', [])),
        }
        normalized.append(norm_vlan)
    return normalized


def validate_vlans(module, vlans, protected_vlans, max_port=10):
    """Validate VLAN list structure and values"""
    seen_ids = set()
    
    for i, vlan in enumerate(vlans):
        vlan_id = get_vlan_id(vlan)
        
        if vlan_id is None:
            module.fail_json(msg=f"VLAN #{i+1}: Missing required field 'vlan_id' or 'id'")
        if 'name' not in vlan:
            module.fail_json(msg=f"VLAN #{i+1} (ID {vlan_id}): Missing required field 'name'")
        
        vlan_name = vlan['name']
        
        if not isinstance(vlan_id, int):
            module.fail_json(msg=f"VLAN #{i+1}: 'vlan_id' must be an integer, got {type(vlan_id).__name__}")
        
        if not 1 <= vlan_id <= 4094:
            module.fail_json(msg=f"VLAN {vlan_id}: ID must be between 1 and 4094")
        
        if vlan_id in seen_ids:
            module.fail_json(msg=f"VLAN {vlan_id}: Duplicate VLAN ID in list")
        seen_ids.add(vlan_id)
        
        if not isinstance(vlan_name, str):
            module.fail_json(msg=f"VLAN {vlan_id}: 'name' must be a string, got {type(vlan_name).__name__}")
        
        if not vlan_name.strip():
            module.fail_json(msg=f"VLAN {vlan_id}: 'name' cannot be empty")
        
        for port_type in ['tagged_ports', 'untagged_ports']:
            if port_type in vlan:
                ports = vlan[port_type]
                if not isinstance(ports, list):
                    module.fail_json(msg=f"VLAN {vlan_id}: '{port_type}' must be a list")
                for port in ports:
                    if not isinstance(port, int) or port < 1 or port > max_port:
                        module.fail_json(msg=f"VLAN {vlan_id}: Invalid port {port} in '{port_type}' (must be 1-{max_port})")


# =============================================================================
# IDEMPOTENCY FUNCTIONS - Parse current config and calculate diff
# =============================================================================

def parse_running_config(output, max_port=10):
    """
    Parse 'show running-config' output to extract current VLAN and port configuration.
    
    Returns:
        dict: {
            'vlans': {vlan_id: {'name': 'xxx', 'tagged_ports': [...], 'untagged_ports': [...]}},
        }
    """
    config = {
        'vlans': {},
    }
    
    # VLAN 1 always exists implicitly
    config['vlans'][1] = {'name': 'System-VLAN', 'tagged_ports': [], 'untagged_ports': []}
    
    current_vlan_id = None
    current_port = None
    
    lines = output.split('\n')
    
    for line in lines:
        line_stripped = line.strip()
        
        # Parse VLAN definitions: "vlan 10"
        vlan_def_match = re.match(r'^vlan\s+(\d+)\s*$', line_stripped)
        if vlan_def_match:
            current_vlan_id = int(vlan_def_match.group(1))
            if current_vlan_id not in config['vlans']:
                config['vlans'][current_vlan_id] = {'name': '', 'tagged_ports': [], 'untagged_ports': []}
            current_port = None
            continue
        
        # Parse VLAN name: 'name "Management"'
        name_match = re.match(r'^name\s+"([^"]*)"', line_stripped)
        if name_match and current_vlan_id is not None:
            config['vlans'][current_vlan_id]['name'] = name_match.group(1)
            continue
        
        # Parse interface: "interface gigabitEthernet 1/0/1"
        interface_match = re.match(r'^interface\s+gigabitEthernet\s+1/0/(\d+)', line_stripped)
        if interface_match:
            current_port = int(interface_match.group(1))
            current_vlan_id = None  # Reset VLAN context when entering interface
            continue
        
        # Parse switchport general allowed vlan X,Y tagged/untagged
        # Format: "switchport general allowed vlan 10,22 tagged"
        # Format: "switchport general allowed vlan 10 untagged"
        if current_port and line_stripped.startswith('switchport general allowed vlan'):
            vlan_match = re.match(r'switchport general allowed vlan\s+([\d,]+)\s+(tagged|untagged)', line_stripped)
            if vlan_match:
                vlan_list_str = vlan_match.group(1)
                mode = vlan_match.group(2)
                
                # Parse comma-separated VLAN list
                vlan_ids = [int(v.strip()) for v in vlan_list_str.split(',') if v.strip()]
                
                for vid in vlan_ids:
                    # Ensure VLAN exists in our config
                    if vid not in config['vlans']:
                        config['vlans'][vid] = {'name': '', 'tagged_ports': [], 'untagged_ports': []}
                    
                    if mode == 'tagged':
                        if current_port not in config['vlans'][vid]['tagged_ports']:
                            config['vlans'][vid]['tagged_ports'].append(current_port)
                    else:  # untagged
                        if current_port not in config['vlans'][vid]['untagged_ports']:
                            config['vlans'][vid]['untagged_ports'].append(current_port)
            continue
        
        # Parse PVID: "switchport pvid 10"
        # PVID indicates the port is untagged member of that VLAN
        pvid_match = re.match(r'switchport pvid\s+(\d+)', line_stripped)
        if pvid_match and current_port:
            pvid = int(pvid_match.group(1))
            if pvid not in config['vlans']:
                config['vlans'][pvid] = {'name': '', 'tagged_ports': [], 'untagged_ports': []}
            # PVID means this port is untagged in this VLAN (if not already added)
            if current_port not in config['vlans'][pvid]['untagged_ports']:
                config['vlans'][pvid]['untagged_ports'].append(current_port)
            continue
        
        # Reset context on section boundaries
        if line_stripped.startswith('#') or line_stripped == 'end':
            current_port = None
            current_vlan_id = None
    
    # Ports without explicit VLAN config are in VLAN 1 untagged (default)
    # Find ports that have no configuration
    configured_ports = set()
    for vid, vlan_data in config['vlans'].items():
        configured_ports.update(vlan_data['tagged_ports'])
        configured_ports.update(vlan_data['untagged_ports'])
    
    for port in range(1, max_port + 1):
        if port not in configured_ports:
            config['vlans'][1]['untagged_ports'].append(port)
    
    # Sort port lists for consistent comparison
    for vid in config['vlans']:
        config['vlans'][vid]['tagged_ports'] = sorted(set(config['vlans'][vid]['tagged_ports']))
        config['vlans'][vid]['untagged_ports'] = sorted(set(config['vlans'][vid]['untagged_ports']))
    
    return config


def calculate_diff(current_config, desired_vlans, mode, protected_vlans):
    """
    Calculate the difference between current and desired configuration.
    
    Returns:
        dict with needs_change, vlans_to_create, vlans_to_delete, ports_to_configure, reasons
    """
    diff = {
        'needs_change': False,
        'vlans_to_create': [],
        'vlans_to_delete': [],
        'ports_to_configure': [],
        'reasons': []
    }
    
    current_vlans = current_config.get('vlans', {})
    desired_vlan_ids = {v['id'] for v in desired_vlans}
    
    for desired in desired_vlans:
        vlan_id = desired['id']
        
        # Skip VLAN 1 for creation (it always exists)
        if vlan_id == 1:
            # But still check port configuration for VLAN 1
            if vlan_id in current_vlans:
                current = current_vlans[vlan_id]
                current_tagged = set(current.get('tagged_ports', []))
                desired_tagged = set(desired.get('tagged_ports', []))
                current_untagged = set(current.get('untagged_ports', []))
                desired_untagged = set(desired.get('untagged_ports', []))
                
                if mode == 'add':
                    missing_tagged = desired_tagged - current_tagged
                    missing_untagged = desired_untagged - current_untagged
                    
                    if missing_tagged or missing_untagged:
                        diff['ports_to_configure'].append({
                            'vlan_id': vlan_id,
                            'add_tagged': sorted(missing_tagged),
                            'add_untagged': sorted(missing_untagged),
                            'remove_tagged': [],
                            'remove_untagged': []
                        })
                        diff['needs_change'] = True
                        if missing_tagged:
                            diff['reasons'].append(f"VLAN {vlan_id}: add tagged ports {sorted(missing_tagged)}")
                        if missing_untagged:
                            diff['reasons'].append(f"VLAN {vlan_id}: add untagged ports {sorted(missing_untagged)}")
                
                elif mode == 'replace':
                    if current_tagged != desired_tagged or current_untagged != desired_untagged:
                        diff['ports_to_configure'].append({
                            'vlan_id': vlan_id,
                            'add_tagged': sorted(desired_tagged - current_tagged),
                            'add_untagged': sorted(desired_untagged - current_untagged),
                            'remove_tagged': sorted(current_tagged - desired_tagged),
                            'remove_untagged': sorted(current_untagged - desired_untagged)
                        })
                        diff['needs_change'] = True
                        diff['reasons'].append(f"VLAN {vlan_id}: port configuration differs")
            continue
        
        # Skip other protected VLANs
        if vlan_id in protected_vlans:
            continue
        
        if vlan_id not in current_vlans:
            # VLAN doesn't exist - needs to be created
            diff['vlans_to_create'].append(desired)
            diff['needs_change'] = True
            diff['reasons'].append(f"VLAN {vlan_id} does not exist")
        else:
            # VLAN exists - check if port configuration matches
            current = current_vlans[vlan_id]
            
            current_tagged = set(current.get('tagged_ports', []))
            desired_tagged = set(desired.get('tagged_ports', []))
            current_untagged = set(current.get('untagged_ports', []))
            desired_untagged = set(desired.get('untagged_ports', []))
            
            if mode == 'add':
                missing_tagged = desired_tagged - current_tagged
                missing_untagged = desired_untagged - current_untagged
                
                if missing_tagged or missing_untagged:
                    diff['ports_to_configure'].append({
                        'vlan_id': vlan_id,
                        'add_tagged': sorted(missing_tagged),
                        'add_untagged': sorted(missing_untagged),
                        'remove_tagged': [],
                        'remove_untagged': []
                    })
                    diff['needs_change'] = True
                    if missing_tagged:
                        diff['reasons'].append(f"VLAN {vlan_id}: add tagged ports {sorted(missing_tagged)}")
                    if missing_untagged:
                        diff['reasons'].append(f"VLAN {vlan_id}: add untagged ports {sorted(missing_untagged)}")
            
            elif mode == 'replace':
                if current_tagged != desired_tagged or current_untagged != desired_untagged:
                    diff['ports_to_configure'].append({
                        'vlan_id': vlan_id,
                        'add_tagged': sorted(desired_tagged - current_tagged),
                        'add_untagged': sorted(desired_untagged - current_untagged),
                        'remove_tagged': sorted(current_tagged - desired_tagged),
                        'remove_untagged': sorted(current_untagged - desired_untagged)
                    })
                    diff['needs_change'] = True
                    diff['reasons'].append(f"VLAN {vlan_id}: port configuration differs")
    
    # Check for VLANs to delete (replace mode only)
    if mode == 'replace':
        for vlan_id in current_vlans:
            if vlan_id not in protected_vlans and vlan_id not in desired_vlan_ids:
                diff['vlans_to_delete'].append(vlan_id)
                diff['needs_change'] = True
                diff['reasons'].append(f"VLAN {vlan_id} should not exist")
    
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


def create_batch_vlan_script(host, username, password, vlans, hostname, diff, protected_vlans):
    """Generate expect script for VLAN configuration based on calculated diff"""
    
    # Generate delete commands
    delete_commands = ""
    for vlan_id in diff.get('vlans_to_delete', []):
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
    
    # Generate create commands for new VLANs
    create_commands = ""
    for vlan in diff.get('vlans_to_create', []):
        escaped_name = escape_vlan_name(vlan['name'])
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
    
    # Generate port configuration commands
    port_commands = ""
    
    # Configure ports for newly created VLANs
    for vlan in diff.get('vlans_to_create', []):
        vlan_id = vlan['id']
        tagged_ports = vlan.get('tagged_ports', [])
        untagged_ports = vlan.get('untagged_ports', [])
        
        for port in tagged_ports:
            port_commands += f'''send "interface gigabitEthernet 1/0/{port}\\r"
expect "{hostname}(config-if)#"
send "switchport general allowed vlan {vlan_id} tagged\\r"
expect "{hostname}(config-if)#"
send "exit\\r"
expect "{hostname}(config)#"
'''
        
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
    
    # Configure ports that need changes on existing VLANs
    for port_config in diff.get('ports_to_configure', []):
        vlan_id = port_config['vlan_id']
        
        for port in port_config.get('add_tagged', []):
            port_commands += f'''send "interface gigabitEthernet 1/0/{port}\\r"
expect "{hostname}(config-if)#"
send "switchport general allowed vlan {vlan_id} tagged\\r"
expect "{hostname}(config-if)#"
send "exit\\r"
expect "{hostname}(config)#"
'''
        
        for port in port_config.get('add_untagged', []):
            port_commands += f'''send "interface gigabitEthernet 1/0/{port}\\r"
expect "{hostname}(config-if)#"
send "switchport general allowed vlan {vlan_id} untagged\\r"
expect "{hostname}(config-if)#"
send "switchport pvid {vlan_id}\\r"
expect "{hostname}(config-if)#"
send "exit\\r"
expect "{hostname}(config)#"
'''
        
        for port in port_config.get('remove_tagged', []):
            port_commands += f'''send "interface gigabitEthernet 1/0/{port}\\r"
expect "{hostname}(config-if)#"
send "no switchport general allowed vlan {vlan_id}\\r"
expect "{hostname}(config-if)#"
send "exit\\r"
expect "{hostname}(config)#"
'''
        
        for port in port_config.get('remove_untagged', []):
            port_commands += f'''send "interface gigabitEthernet 1/0/{port}\\r"
expect "{hostname}(config-if)#"
send "no switchport general allowed vlan {vlan_id}\\r"
expect "{hostname}(config-if)#"
send "switchport pvid 1\\r"
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


# =============================================================================
# OUTPUT ANALYSIS
# =============================================================================

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
    
    if "SUCCESS_COMPLETE" in combined or "SUCCESS_CONFIG_SAVED" in combined or "SUCCESS_GET_CONFIG" in combined:
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


# =============================================================================
# MAIN MODULE
# =============================================================================

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
        supports_check_mode=True
    )
    
    host = module.params['host']
    username = module.params['username']
    password = module.params['password']
    vlans_raw = module.params['vlans']
    hostname = module.params['hostname']
    mode = module.params['mode']
    protected_vlans = module.params['protected_vlans']
    
    # SG3210 has 10 ports
    max_port = 10
    
    # Validate VLAN list
    validate_vlans(module, vlans_raw, protected_vlans, max_port)
    
    # Normalize VLANs
    desired_vlans = normalize_vlans(vlans_raw)
    
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
    
    # === STEP 2: Parse current configuration ===
    current_config = parse_running_config(stdout, max_port)
    
    # === STEP 3: Calculate diff ===
    diff = calculate_diff(current_config, desired_vlans, mode, protected_vlans)
    
    # === STEP 4: Check if changes are needed ===
    if not diff['needs_change']:
        module.exit_json(
            changed=False,
            msg="Configuration already matches desired state",
            host=host,
            mode=mode,
            current_vlans=list(current_config['vlans'].keys()),
            desired_vlans=[v['id'] for v in desired_vlans],
        )
    
    # === STEP 5: Check mode (dry-run) ===
    if module.check_mode:
        module.exit_json(
            changed=True,
            msg=f"Would apply changes: {'; '.join(diff['reasons'])}",
            host=host,
            mode=mode,
            diff=diff,
        )
    
    # === STEP 6: Apply changes ===
    config_script = create_batch_vlan_script(
        host, username, password, desired_vlans, hostname, diff, protected_vlans
    )
    
    try:
        stdout, stderr, returncode = run_expect_script(config_script, timeout=180)
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
    
    # === STEP 7: Report success ===
    vlans_created = len(diff.get('vlans_to_create', []))
    vlans_deleted = len(diff.get('vlans_to_delete', []))
    ports_changed = len(diff.get('ports_to_configure', []))
    
    module.exit_json(
        changed=True,
        msg=f"Configuration applied: {'; '.join(diff['reasons'])}",
        host=host,
        mode=mode,
        vlans_created=vlans_created,
        vlans_deleted=vlans_deleted,
        ports_changed=ports_changed,
        changes=diff['reasons'],
        stdout=stdout
    )


if __name__ == '__main__':
    main()
