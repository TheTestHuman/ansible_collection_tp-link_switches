#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
TP-Link SG3210 Initial Setup Module

Erstmalige Einrichtung eines Factory-Reset TP-Link SG3210 via Telnet.
Setzt Admin-Passwort und aktiviert SSH-Server.

HINWEIS: Dieses Modul verwendet Telnet, da SSH auf einem Factory-Reset
Switch noch nicht aktiviert ist. Telnet überträgt Passwörter unverschlüsselt -
nur in sicheren Netzwerken verwenden!

Parameter:
    default_ip: Standard-IP des Factory-Reset Switch (default: 192.168.0.1)
    default_user: Standard-Benutzername (default: admin)
    default_password: Standard-Passwort (default: admin)
    new_password: Neues Admin-Passwort (required)
    enable_ssh: SSH-Server aktivieren (default: true)
    hostname: CLI Prompt Hostname (default: SG3210)

Beispiel:
    - tp_link_initial_setup:
        default_ip: "192.168.0.1"
        new_password: "sicheres_passwort"
        enable_ssh: true
"""

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os

DOCUMENTATION = r'''
module: tp_link_initial_setup
short_description: Initial setup of factory-reset TP-Link SG3210 - Password and SSH
description:
    - Connects to a factory-reset TP-Link switch via Telnet
    - Sets the admin password
    - Enables SSH server
    - Saves configuration
    - Does NOT change IP address (use tp_link_change_ip for that)
    - Detects if switch is already configured (password changed)
options:
    default_ip:
        description: Default IP address of factory-reset switch
        required: false
        default: "192.168.0.1"
    default_user:
        description: Default username
        required: false
        default: "admin"
    default_password:
        description: Default password (factory default)
        required: false
        default: "admin"
    new_password:
        description: New admin password to set
        required: true
        no_log: true
    enable_ssh:
        description: Enable SSH server
        required: false
        default: true
        type: bool
    hostname:
        description: Switch hostname for expect prompts
        required: false
        default: "SG3210"
'''

EXAMPLES = r'''
# Basic initial setup
- tp_link_initial_setup:
    default_ip: "192.168.0.1"
    new_password: "neues_sicheres_passwort"

# With custom hostname
- tp_link_initial_setup:
    default_ip: "192.168.0.1"
    new_password: "neues_sicheres_passwort"
    hostname: "SWITCH-01"

# Without SSH (not recommended)
- tp_link_initial_setup:
    default_ip: "192.168.0.1"
    new_password: "neues_sicheres_passwort"
    enable_ssh: false
'''


def create_initial_setup_script(default_ip, default_user, default_password, 
                                 new_password, enable_ssh, hostname):
    """Generate expect script for initial switch setup via Telnet"""
    
    script = f'''#!/usr/bin/expect -f
set timeout 30
log_user 1

# === CONNECTION PHASE ===
spawn telnet {default_ip}

expect {{
    "Connection refused" {{
        puts "ERROR_CONNECTION_REFUSED: Telnet port closed on {default_ip}"
        exit 1
    }}
    "No route to host" {{
        puts "ERROR_CONNECTION_FAILED: No route to {default_ip}"
        exit 1
    }}
    "Unable to connect" {{
        puts "ERROR_CONNECTION_FAILED: Unable to connect to {default_ip}"
        exit 1
    }}
    "Connection timed out" {{
        puts "ERROR_CONNECTION_TIMEOUT: Connection to {default_ip} timed out"
        exit 1
    }}
    "Network is unreachable" {{
        puts "ERROR_HOST_UNREACHABLE: Network is unreachable"
        exit 1
    }}
    "User:" {{
        send "{default_user}\\r"
    }}
    timeout {{
        puts "ERROR_CONNECTION_TIMEOUT: Timeout connecting to {default_ip}"
        exit 1
    }}
}}

# === LOGIN PHASE ===
expect "Password:"
send "{default_password}\\r"

# === CHECK LOGIN RESULT ===
# Wait for either:
# - "Change now?" = Factory reset, needs password change
# - "Login invalid" = Password already changed (switch configured)
# - hostname prompt = Already logged in (password is still default but no change prompt)
expect {{
    "Change now?" {{
        # Factory-reset switch - password change required
        puts "INFO_FACTORY_RESET: Switch requires password change"
        send "Y\\r"
    }}
    "Login invalid" {{
        # Password already changed - switch is already configured
        puts "ERROR_ALREADY_CONFIGURED: Switch password already changed - not a factory-reset switch"
        exit 2
    }}
    "invalid" {{
        # Alternative invalid message
        puts "ERROR_ALREADY_CONFIGURED: Switch password already changed - not a factory-reset switch"
        exit 2
    }}
    "{hostname}>" {{
        # Logged in without password change prompt - unusual but handle it
        puts "INFO_ALREADY_LOGGED_IN: Switch accepted default password without change prompt"
        # Continue to enable SSH if requested
        send "enable\\r"
        expect "{hostname}#"
        send "configure\\r"
        expect "{hostname}(config)#"
'''

    if enable_ssh:
        script += f'''
        send "ip ssh server\\r"
        expect "{hostname}(config)#"
'''

    script += f'''
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
        exit 0
    }}
    "Access denied" {{
        puts "ERROR_ALREADY_CONFIGURED: Access denied - switch password already changed"
        exit 2
    }}
    timeout {{
        puts "ERROR_AUTH_TIMEOUT: Timeout after login - password may be incorrect or switch already configured"
        exit 1
    }}
}}

# === PASSWORD CHANGE SEQUENCE ===
expect "Please enter the new password:"
send "{new_password}\\r"

expect "Please confirm new password again:"
send "{new_password}\\r"

# Wait for confirmation and press ENTER
expect {{
    "Please Press ENTER" {{
        send "\\r"
    }}
    "Password changed" {{
        send "\\r"
    }}
    timeout {{
        puts "ERROR_PASSWORD_CHANGE: Timeout after password change"
        exit 1
    }}
}}

# Wait for prompt after password change
expect {{
    "{hostname}>" {{}}
    timeout {{
        puts "ERROR_POST_PASSWORD: Timeout waiting for prompt after password change"
        exit 1
    }}
}}

# === ENABLE MODE ===
send "enable\\r"
expect {{
    "{hostname}#" {{}}
    "Password:" {{
        puts "ERROR_ENABLE_PASSWORD: Enable password required but not supported"
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
'''

    # Enable SSH if requested
    if enable_ssh:
        script += f'''
# === ENABLE SSH ===
send "ip ssh server\\r"
expect {{
    "{hostname}(config)#" {{}}
    "Error" {{
        puts "ERROR_SSH_ENABLE: Failed to enable SSH"
        exit 1
    }}
    "Invalid" {{
        puts "ERROR_SSH_ENABLE: Invalid command for SSH activation"
        exit 1
    }}
    timeout {{
        puts "ERROR_SSH_TIMEOUT: Timeout enabling SSH"
        exit 1
    }}
}}
'''

    # Save configuration and exit
    script += f'''
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
expect {{
    eof {{}}
    "Connection closed" {{}}
    timeout {{}}
}}

puts "SUCCESS_COMPLETE"
'''
    
    return script


def analyze_output(stdout, stderr, returncode):
    """Analyze expect output for errors and return appropriate message"""
    
    combined = stdout + stderr
    
    # Check for "already configured" - this is a special case (exit code 2)
    if "ERROR_ALREADY_CONFIGURED" in combined or returncode == 2:
        return False, "Switch is already configured (password changed) - not a factory-reset switch", True
    
    error_patterns = {
        "ERROR_CONNECTION_REFUSED": "Connection refused: Telnet port not open",
        "ERROR_CONNECTION_FAILED": "Connection failed: Host not reachable",
        "ERROR_CONNECTION_TIMEOUT": "Connection timeout: Host not responding",
        "ERROR_HOST_UNREACHABLE": "Host unreachable: Network problem",
        "ERROR_LOGIN_TIMEOUT": "Timeout during login",
        "ERROR_AUTH_FAILED": "Authentication failed: Wrong username or password",
        "ERROR_AUTH_TIMEOUT": "Authentication timeout: Password may be incorrect or switch already configured",
        "ERROR_PASSWORD_CHANGE": "Error during password change",
        "ERROR_POST_PASSWORD": "Error after password change",
        "ERROR_ENABLE_PASSWORD": "Enable password required",
        "ERROR_ENABLE_TIMEOUT": "Timeout entering enable mode",
        "ERROR_CONFIG_TIMEOUT": "Timeout entering config mode",
        "ERROR_SSH_ENABLE": "Failed to enable SSH",
        "ERROR_SSH_TIMEOUT": "Timeout enabling SSH",
        "ERROR_SAVE_TIMEOUT": "Timeout saving configuration",
    }
    
    # Telnet-specific errors in raw output
    telnet_errors = {
        "Connection refused": "Connection refused: Telnet service not reachable",
        "No route to host": "Connection failed: No route to host",
        "Unable to connect": "Unable to connect",
        "Connection timed out": "Connection timed out",
        "Network is unreachable": "Network is unreachable",
    }
    
    # Check for "Login invalid" in raw output (switch already configured)
    if "Login invalid" in combined or "login invalid" in combined.lower():
        return False, "Switch is already configured (password changed) - not a factory-reset switch", True
    
    # Check for our custom error markers
    for error_key, error_msg in error_patterns.items():
        if error_key in combined:
            return False, error_msg, False
    
    # Check for raw telnet errors
    for telnet_error, error_msg in telnet_errors.items():
        if telnet_error in combined:
            return False, error_msg, False
    
    # Check for success
    if "SUCCESS_COMPLETE" in combined or "SUCCESS_CONFIG_SAVED" in combined:
        return True, None, False
    
    # Check for timeout markers
    if "TIMEOUT" in combined.upper():
        return False, "Timeout during configuration", False
    
    # If we got "Saving user config OK!" that's also success
    if "Saving user config OK!" in combined:
        return True, None, False
    
    return False, "Unknown error - check stdout", False


def run_expect_script(script_content, timeout=90):
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
            default_ip=dict(type='str', required=False, default='192.168.0.1'),
            default_user=dict(type='str', required=False, default='admin'),
            default_password=dict(type='str', required=False, default='admin', no_log=True),
            new_password=dict(type='str', required=True, no_log=True),
            enable_ssh=dict(type='bool', required=False, default=True),
            hostname=dict(type='str', required=False, default='SG3210'),
        ),
        supports_check_mode=False
    )
    
    default_ip = module.params['default_ip']
    default_user = module.params['default_user']
    default_password = module.params['default_password']
    new_password = module.params['new_password']
    enable_ssh = module.params['enable_ssh']
    hostname = module.params['hostname']
    
    # Password validation
    if len(new_password) < 1:
        module.fail_json(msg="new_password must not be empty")
    
    # Generate expect script
    try:
        script = create_initial_setup_script(
            default_ip, default_user, default_password,
            new_password, enable_ssh, hostname
        )
    except Exception as e:
        module.fail_json(msg=f"Error generating script: {str(e)}")
    
    # Run script
    try:
        stdout, stderr, returncode = run_expect_script(script, timeout=90)
    except subprocess.TimeoutExpired:
        module.fail_json(
            msg="Total timeout exceeded (90s) - switch not responding",
            host=default_ip
        )
    except Exception as e:
        module.fail_json(msg=f"Unexpected error: {str(e)}", host=default_ip)
    
    # Analyze output
    success, error_msg, already_configured = analyze_output(stdout, stderr, returncode)
    
    if already_configured:
        # Special case: Switch is already configured - fail with clear message
        module.fail_json(
            msg=f"Switch is already configured (not factory-reset). Password has been changed previously. Please factory-reset the switch or use different credentials.",
            host=default_ip,
            already_configured=True,
            stdout=stdout,
            stderr=stderr
        )
    
    if not success:
        module.fail_json(
            msg=f"Initial setup failed: {error_msg}",
            host=default_ip,
            stdout=stdout,
            stderr=stderr,
            return_code=returncode
        )
    
    msg = f"Initial setup completed. SSH {'enabled' if enable_ssh else 'not enabled'}."
    
    module.exit_json(
        changed=True,
        msg=msg,
        config={
            'ssh_enabled': enable_ssh,
            'ip': default_ip,
            'hostname': hostname
        },
        stdout=stdout
    )


if __name__ == '__main__':
    main()
