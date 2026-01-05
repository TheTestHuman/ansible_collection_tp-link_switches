#!/usr/bin/python
# -*- coding: utf-8 -*-

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os
from datetime import datetime

DOCUMENTATION = r'''
module: tp_link_tftp_backup
short_description: Backup/restore configuration via TFTP on TP-Link SG3210
description:
    - Backs up switch configuration to a TFTP server
    - Restores switch configuration from a TFTP server
    - Supports startup-config and backup-config
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
    tftp_server:
        description: TFTP server IP address
        required: true
    action:
        description: Action to perform
        required: true
        choices: ['backup', 'restore']
    config_type:
        description: Configuration type to backup/restore
        required: false
        default: "startup-config"
        choices: ['startup-config', 'backup-config']
    filename:
        description: Filename on TFTP server
        required: false
        default: "auto"
    auto_timestamp:
        description: Add timestamp to filename (only for backup)
        required: false
        default: true
        type: bool
'''

EXAMPLES = r'''
# Backup startup-config to TFTP with timestamp
- tp_link_tftp_backup:
    host: 10.0.10.1
    username: admin
    password: neinnein
    tftp_server: 192.168.0.15
    action: backup
    config_type: startup-config
    auto_timestamp: true

# Backup with custom filename
- tp_link_tftp_backup:
    host: 10.0.10.1
    username: admin
    password: neinnein
    tftp_server: 192.168.0.15
    action: backup
    filename: switch-sg3210-config.txt

# Restore from TFTP
- tp_link_tftp_backup:
    host: 10.0.10.1
    username: admin
    password: neinnein
    tftp_server: 192.168.0.15
    action: restore
    config_type: startup-config
    filename: switch-sg3210-backup-20250107.txt
'''

def create_tftp_script(host, username, password, tftp_server, action, 
                       config_type, filename, auto_timestamp):
    """Generate expect script for TFTP backup/restore operations"""
    
    # Generate filename if auto or add timestamp
    if filename == "auto" or auto_timestamp:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        if filename == "auto":
            filename = f"switch-{host}-{config_type}-{timestamp}.txt"
        elif auto_timestamp and action == 'backup':
            # Add timestamp before extension
            name, ext = os.path.splitext(filename) if '.' in filename else (filename, '.txt')
            filename = f"{name}-{timestamp}{ext}"
    
    script = f'''#!/usr/bin/expect -f
set timeout 60

# Connect via SSH
spawn ssh -o PubkeyAuthentication=no {username}@{host}
expect "password:"
send "{password}\\r"
expect "SG3210>"

# Enter privileged mode
send "enable\\r"
expect "SG3210#"
'''

    if action == 'backup':
        # Backup to TFTP
        script += f'''
# Backup {config_type} to TFTP server
send "copy {config_type} tftp ip-address {tftp_server} filename {filename}\\r"
expect {{
    "successfully" {{
        send_user "\\nBackup completed successfully\\n"
        expect "SG3210#"
    }}
    "Error" {{
        send_user "\\nBackup failed\\n"
        expect "SG3210#"
    }}
    timeout {{
        send_user "\\nTimeout during TFTP backup\\n"
    }}
}}
'''
    
    elif action == 'restore':
        # Restore from TFTP
        script += f'''
# Restore {config_type} from TFTP server
send "copy tftp {config_type} ip-address {tftp_server} filename {filename}\\r"
expect {{
    "successfully" {{
        send_user "\\nRestore completed successfully\\n"
        expect "SG3210#"
    }}
    "Error" {{
        send_user "\\nRestore failed\\n"
        expect "SG3210#"
    }}
    timeout {{
        send_user "\\nTimeout during TFTP restore\\n"
    }}
}}
'''

    # Exit
    script += '''
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
    
    return script, filename

def main():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type='str', required=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            tftp_server=dict(type='str', required=True),
            action=dict(type='str', required=True, choices=['backup', 'restore']),
            config_type=dict(type='str', required=False, default='startup-config',
                           choices=['startup-config', 'backup-config']),
            filename=dict(type='str', required=False, default='auto'),
            auto_timestamp=dict(type='bool', required=False, default=True),
        ),
        supports_check_mode=False
    )
    
    # Generate expect script
    try:
        script, final_filename = create_tftp_script(
            module.params['host'],
            module.params['username'],
            module.params['password'],
            module.params['tftp_server'],
            module.params['action'],
            module.params['config_type'],
            module.params['filename'],
            module.params['auto_timestamp']
        )
    except Exception as e:
        module.fail_json(msg=f"Error generating script: {str(e)}")
    
    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.exp', delete=False) as f:
        f.write(script)
        script_path = f.name
    
    try:
        os.chmod(script_path, 0o700)
        result = subprocess.run([script_path], capture_output=True, text=True, timeout=90)
        
        os.unlink(script_path)
        
        # Check if operation was successful
        if "successfully" in result.stdout.lower() or "Backup completed" in result.stdout:
            success = True
            if module.params['action'] == 'backup':
                msg = f"Configuration backed up to TFTP server {module.params['tftp_server']}"
            else:
                msg = f"Configuration restored from TFTP server {module.params['tftp_server']}"
        else:
            success = False
            msg = f"TFTP {module.params['action']} may have failed - check TFTP server"
        
        result_data = {
            'action': module.params['action'],
            'tftp_server': module.params['tftp_server'],
            'config_type': module.params['config_type'],
            'filename': final_filename
        }
        
        module.exit_json(
            changed=success,
            msg=msg,
            tftp_info=result_data,
            stdout=result.stdout,
            warnings=[] if success else ["TFTP operation may have failed - verify TFTP server logs"]
        )
    except subprocess.TimeoutExpired:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg="Timeout during TFTP operation - check TFTP server accessibility")
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg=str(e))

if __name__ == '__main__':
    main()
