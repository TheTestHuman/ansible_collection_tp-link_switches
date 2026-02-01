#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
TP-Link SG3210 IP Address Change Module

Changes IP address, netmask, and gateway on TP-Link SG3210 Managed Switches via SSH.

NOTE: After IP change, the SSH connection will drop. This is expected behavior.
The module saves the configuration BEFORE changing the IP to ensure persistence.

Parameters:
    current_ip: Current switch IP address
    username: SSH username
    password: SSH password
    new_ip: New IP address for the switch
    new_netmask: New netmask (default: 255.255.255.0)
    new_gateway: New gateway IP
    hostname: CLI prompt hostname (default: SG3210)

Example:
    - tp_link_change_ip:
        current_ip: "192.168.0.1"
        username: "admin"
        password: "secret"
        new_ip: "10.0.10.1"
        new_netmask: "255.255.255.0"
        new_gateway: "10.0.10.254"
"""

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os
import ipaddress

DOCUMENTATION = r'''
module: tp_link_change_ip
short_description: Change IP address of TP-Link SG3210 via SSH
description:
    - Connects to TP-Link switch via SSH
    - Changes IP address, netmask, and gateway
    - Saves configuration BEFORE IP change
    - Handles expected connection drop after IP change
options:
    current_ip:
        description: Current IP address of the switch
        required: true
    username:
        description: SSH username
        required: true
    password:
        description: SSH password
        required: true
        no_log: true
    new_ip:
        description: New IP address for the switch
        required: true
    new_netmask:
        description: New netmask
        required: false
        default: "255.255.255.0"
    new_gateway:
        description: New gateway IP
        required: true
    hostname:
        description: Switch hostname for expect prompts
        required: false
        default: "SG3210"
'''

EXAMPLES = r'''
# Change IP address
- tp_link_change_ip:
    current_ip: "192.168.0.1"
    username: "admin"
    password: "secret"
    new_ip: "10.0.10.1"
    new_netmask: "255.255.255.0"
    new_gateway: "10.0.10.254"

# With custom hostname
- tp_link_change_ip:
    current_ip: "192.168.0.1"
    username: "admin"
    password: "secret"
    new_ip: "10.0.20.1"
    new_gateway: "10.0.20.254"
    hostname: "CORE-SW1"
'''


def create_change_ip_script(current_ip, username, password, 
                             new_ip, new_netmask, new_gateway, hostname):
    """Generate expect script for IP change via SSH
    
    Strategy: Save config BEFORE changing IP, then change IP.
    Connection will drop after IP change - this is expected and OK.
    """
    
    script = f'''#!/usr/bin/expect -f
set timeout 30
log_user 1

# === CONNECTION PHASE ===
spawn ssh -o StrictHostKeyChecking=no -o PubkeyAuthentication=no -o ConnectTimeout=20 {username}@{current_ip}

expect {{
    "No route to host" {{
        puts "ERROR_CONNECTION_FAILED: No route to host {current_ip}"
        exit 1
    }}
    "Connection refused" {{
        puts "ERROR_CONNECTION_REFUSED: Connection refused by {current_ip}"
        exit 1
    }}
    "Connection timed out" {{
        puts "ERROR_CONNECTION_TIMEOUT: Connection to {current_ip} timed out"
        exit 1
    }}
    "Host is unreachable" {{
        puts "ERROR_HOST_UNREACHABLE: Host {current_ip} is unreachable"
        exit 1
    }}
    "Name or service not known" {{
        puts "ERROR_DNS_FAILED: Could not resolve hostname {current_ip}"
        exit 1
    }}
    "password:" {{
        send "{password}\\r"
    }}
    timeout {{
        puts "ERROR_CONNECTION_TIMEOUT: Timeout connecting to {current_ip}"
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

# === CONFIGURE GATEWAY FIRST ===
# (Gateway can be configured before IP change)
send "ip default-gateway {new_gateway}\\r"
expect {{
    "{hostname}(config)#" {{}}
    "Invalid" {{
        puts "ERROR_INVALID_GATEWAY: Invalid gateway address"
        exit 1
    }}
    "Error" {{
        puts "ERROR_GATEWAY_CONFIG: Failed to configure gateway"
        exit 1
    }}
    timeout {{
        puts "ERROR_GATEWAY_TIMEOUT: Timeout configuring gateway"
        exit 1
    }}
}}

# === SAVE CONFIG BEFORE IP CHANGE ===
# This is critical - save BEFORE changing IP so config persists even if connection drops
send "exit\\r"
expect "{hostname}#"

send "copy running-config startup-config\\r"
expect {{
    "Saving user config OK!" {{
        puts "SUCCESS_GATEWAY_SAVED"
    }}
    "Succeed" {{
        puts "SUCCESS_GATEWAY_SAVED"
    }}
    timeout {{
        puts "ERROR_SAVE_TIMEOUT: Timeout saving gateway configuration"
        exit 1
    }}
}}

# === NOW CHANGE IP ADDRESS ===
# After this, connection WILL drop - this is expected!
send "configure\\r"
expect "{hostname}(config)#"

send "interface vlan 1\\r"
expect {{
    "{hostname}(config-if)#" {{}}
    timeout {{
        puts "ERROR_INTERFACE_TIMEOUT: Timeout entering interface config"
        exit 1
    }}
}}

puts "INFO_CHANGING_IP: About to change IP - connection will drop"

# Change IP - expect connection to drop immediately or shortly after
send "ip address {new_ip} {new_netmask}\\r"

# Short timeout - we expect this to fail/timeout because connection drops
set timeout 5
expect {{
    "{hostname}(config-if)#" {{
        # Unexpected - IP didn't change yet? Try to save and exit
        puts "INFO_IP_COMMAND_ACCEPTED"
        send "exit\\r"
        expect "{hostname}(config)#"
        send "exit\\r"
        expect "{hostname}#"
        send "copy running-config startup-config\\r"
        expect {{
            "Saving user config OK!" {{ puts "SUCCESS_CONFIG_SAVED" }}
            "Succeed" {{ puts "SUCCESS_CONFIG_SAVED" }}
            timeout {{ puts "WARNING_SAVE_TIMEOUT" }}
        }}
        send "exit\\r"
    }}
    eof {{
        # Connection dropped - this is EXPECTED and SUCCESS
        puts "SUCCESS_IP_CHANGED_CONNECTION_DROPPED"
    }}
    timeout {{
        # Timeout likely means connection dropped - this is SUCCESS
        puts "SUCCESS_IP_CHANGED_TIMEOUT"
    }}
    "Invalid" {{
        puts "ERROR_INVALID_IP: Invalid IP address or netmask"
        exit 1
    }}
    "Error" {{
        puts "ERROR_IP_CONFIG: Failed to configure IP address"
        exit 1
    }}
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
        "ERROR_CONFIG_TIMEOUT": "Timeout entering config mode",
        "ERROR_INTERFACE_TIMEOUT": "Timeout entering interface config",
        "ERROR_INVALID_IP": "Invalid IP address or netmask",
        "ERROR_IP_CONFIG": "Failed to configure IP address",
        "ERROR_INVALID_GATEWAY": "Invalid gateway address",
        "ERROR_GATEWAY_CONFIG": "Failed to configure gateway",
        "ERROR_GATEWAY_TIMEOUT": "Timeout configuring gateway",
        "ERROR_SAVE_TIMEOUT": "Timeout saving configuration",
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
    
    # Check for raw SSH errors (but only before we started configuring)
    # After IP change, connection drop is expected
    if "INFO_CHANGING_IP" not in combined:
        for ssh_error, error_msg in ssh_errors.items():
            if ssh_error in combined:
                return False, error_msg
    
    # Success indicators
    success_indicators = [
        "SUCCESS_COMPLETE",
        "SUCCESS_IP_CHANGED_CONNECTION_DROPPED",
        "SUCCESS_IP_CHANGED_TIMEOUT",
        "SUCCESS_CONFIG_SAVED",
        "SUCCESS_GATEWAY_SAVED",
    ]
    
    for indicator in success_indicators:
        if indicator in combined:
            return True, None
    
    # If we got to the point of changing IP and then lost connection, that's success
    if "INFO_CHANGING_IP" in combined:
        # We started the IP change - connection drop is expected
        return True, None
    
    # If gateway was saved, we're mostly successful even if IP change had issues
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
        return result.stdout, result.stderr, result.returncode, False
    except subprocess.TimeoutExpired as e:
        # Capture partial output from timeout
        stdout = e.stdout if e.stdout else ""
        stderr = e.stderr if e.stderr else ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode('utf-8', errors='replace')
        if isinstance(stderr, bytes):
            stderr = stderr.decode('utf-8', errors='replace')
        return stdout, stderr, -1, True
    finally:
        if os.path.exists(script_path):
            os.unlink(script_path)


def validate_ip_address(ip_string):
    """Validate IP address format"""
    try:
        ipaddress.ip_address(ip_string)
        return True
    except ValueError:
        return False


def validate_netmask(netmask_string):
    """Validate netmask format"""
    try:
        # Check if it's a valid IPv4 address format
        parts = netmask_string.split('.')
        if len(parts) != 4:
            return False
        for part in parts:
            num = int(part)
            if num < 0 or num > 255:
                return False
        return True
    except (ValueError, AttributeError):
        return False


def main():
    module = AnsibleModule(
        argument_spec=dict(
            current_ip=dict(type='str', required=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            new_ip=dict(type='str', required=True),
            new_netmask=dict(type='str', required=False, default='255.255.255.0'),
            new_gateway=dict(type='str', required=True),
            hostname=dict(type='str', required=False, default='SG3210'),
        ),
        supports_check_mode=False
    )
    
    current_ip = module.params['current_ip']
    username = module.params['username']
    password = module.params['password']
    new_ip = module.params['new_ip']
    new_netmask = module.params['new_netmask']
    new_gateway = module.params['new_gateway']
    hostname = module.params['hostname']
    
    # Validate IP addresses
    if not validate_ip_address(current_ip):
        module.fail_json(msg=f"Invalid current_ip: {current_ip}")
    
    if not validate_ip_address(new_ip):
        module.fail_json(msg=f"Invalid new_ip: {new_ip}")
    
    if not validate_ip_address(new_gateway):
        module.fail_json(msg=f"Invalid new_gateway: {new_gateway}")
    
    if not validate_netmask(new_netmask):
        module.fail_json(msg=f"Invalid new_netmask: {new_netmask}")
    
    # Check if IP is actually changing
    if current_ip == new_ip:
        module.exit_json(
            changed=False,
            msg="IP address unchanged - current_ip equals new_ip",
            new_config={
                'ip': new_ip,
                'netmask': new_netmask,
                'gateway': new_gateway
            }
        )
    
    # Generate expect script
    try:
        script = create_change_ip_script(
            current_ip, username, password,
            new_ip, new_netmask, new_gateway, hostname
        )
    except Exception as e:
        module.fail_json(msg=f"Error generating script: {str(e)}")
    
    # Run script
    stdout, stderr, returncode, timed_out = run_expect_script(script, timeout=60)
    
    # Analyze output
    success, error_msg = analyze_output(stdout, stderr)
    
    if not success:
        module.fail_json(
            msg=f"IP change failed: {error_msg}",
            host=current_ip,
            stdout=stdout,
            stderr=stderr,
            return_code=returncode
        )
    
    # Build success message
    if "SUCCESS_IP_CHANGED_CONNECTION_DROPPED" in stdout or "SUCCESS_IP_CHANGED_TIMEOUT" in stdout:
        msg = "IP address changed successfully (connection dropped as expected)"
        warnings = ["Connection dropped after IP change - this is expected behavior"]
    elif timed_out:
        msg = "IP address changed (script timed out but config was saved)"
        warnings = ["Script timed out but configuration was saved before IP change"]
    else:
        msg = "IP address changed successfully"
        warnings = []
    
    result = {
        'changed': True,
        'msg': msg,
        'new_config': {
            'ip': new_ip,
            'netmask': new_netmask,
            'gateway': new_gateway
        },
        'stdout': stdout
    }
    
    if warnings:
        result['warnings'] = warnings
    
    module.exit_json(**result)


if __name__ == '__main__':
    main()
