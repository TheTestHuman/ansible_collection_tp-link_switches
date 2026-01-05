#!/usr/bin/python
# -*- coding: utf-8 -*-

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os

DOCUMENTATION = r'''
module: tp_link_config_backup
short_description: Backup and restore configuration on TP-Link SG3210
description:
    - Creates local backup of running/startup configuration on the switch
    - Restores configuration from backup-config to running/startup
    - Uses the switch's internal backup-config storage
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
    action:
        description: Action to perform
        required: true
        choices: ['backup', 'restore']
    source:
        description: Source configuration (for backup action)
        required: false
        default: "running-config"
        choices: ['running-config', 'startup-config']
    destination:
        description: Destination configuration (for restore action)
        required: false
        default: "startup-config"
        choices: ['running-config', 'startup-config']
'''

EXAMPLES = r'''
# Create backup from running-config
- tp_link_config_backup:
    host: 10.0.10.1
    username: admin
    password: neinnein
    action: backup
    source: running-config

# Create backup from startup-config
- tp_link_config_backup:
    host: 10.0.10.1
    username: admin
    password: neinnein
    action: backup
    source: startup-config

# Restore backup to startup-config
- tp_link_config_backup:
    host: 10.0.10.1
    username: admin
    password: neinnein
    action: restore
    destination: startup-config

# Restore backup to running-config (immediate effect!)
- tp_link_config_backup:
    host: 10.0.10.1
    username: admin
    password: neinnein
    action: restore
    destination: running-config
'''

def create_backup_script(host, username, password, action, source, destination):
    """Generate expect script for backup/restore operations"""
    
    script = f'''#!/usr/bin/expect -f
set timeout 30

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
        # Create backup
        script += f'''
# Create backup from {source}
send "copy {source} backup-config\\r"
expect "Saving user config OK!"
expect "SG3210#"
'''
    
    elif action == 'restore':
        # Restore from backup
        script += f'''
# Restore backup to {destination}
send "copy backup-config {destination}\\r"
expect {{
    "Saving user config OK!" {{
        expect "SG3210#"
    }}
    "Startup configuration is being used by the system!" {{
        expect "SG3210#"
    }}
    timeout {{
        send_user "\\nTimeout waiting for restore completion\\n"
    }}
}}
'''
        # If restoring to startup, also save
        if destination == 'startup-config':
            script += '''
# Configuration already saved to startup
'''
        else:
            # Restoring to running-config - offer to save
            script += '''
# Save running-config to startup-config
send "copy running-config startup-config\\r"
expect "Saving user config OK!"
expect "SG3210#"
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
    
    return script

def main():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type='str', required=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            action=dict(type='str', required=True, choices=['backup', 'restore']),
            source=dict(type='str', required=False, default='running-config',
                       choices=['running-config', 'startup-config']),
            destination=dict(type='str', required=False, default='startup-config',
                           choices=['running-config', 'startup-config']),
        ),
        supports_check_mode=False
    )
    
    # Generate expect script
    try:
        script = create_backup_script(
            module.params['host'],
            module.params['username'],
            module.params['password'],
            module.params['action'],
            module.params['source'],
            module.params['destination']
        )
    except Exception as e:
        module.fail_json(msg=f"Error generating script: {str(e)}")
    
    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.exp', delete=False) as f:
        f.write(script)
        script_path = f.name
    
    try:
        os.chmod(script_path, 0o700)
        result = subprocess.run([script_path], capture_output=True, text=True, timeout=60)
        
        os.unlink(script_path)
        
        if module.params['action'] == 'backup':
            msg = f"Configuration backed up from {module.params['source']}"
            result_data = {
                'action': 'backup',
                'source': module.params['source'],
                'backup_location': 'backup-config (on switch)'
            }
        else:
            msg = f"Configuration restored to {module.params['destination']}"
            result_data = {
                'action': 'restore',
                'destination': module.params['destination'],
                'source': 'backup-config (on switch)'
            }
        
        module.exit_json(
            changed=True,
            msg=msg,
            backup_info=result_data,
            stdout=result.stdout
        )
    except subprocess.TimeoutExpired:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg="Timeout during backup/restore operation")
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg=str(e))

if __name__ == '__main__':
    main()
