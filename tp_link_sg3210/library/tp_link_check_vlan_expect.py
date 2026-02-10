#!/usr/bin/python
# -*- coding: utf-8 -*-
from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os
import re


def check_existing_vlans(host, username, password, hostname):
    """Check which VLANs already exist on switch"""
    
    # Fix: Einfacheres, sequentielles Script ohne verschachtelte expect-Blöcke
    
    script = f'''#!/usr/bin/expect -f
set timeout 60
log_user 1

spawn ssh -o StrictHostKeyChecking=no -o PubkeyAuthentication=no {username}@{host}

expect "password:"
send "{password}\\r"

expect "{hostname}>"
send "enable\\r"

expect "{hostname}#"
send "terminal length 0\\r"

expect "{hostname}#"
send "show vlan\\r"

# Warte auf kompletten Output + nächsten Prompt
expect {{
    -re "{hostname}#" {{}}
    "--More--" {{
        send " "
        exp_continue
    }}
    timeout {{
        puts "TIMEOUT_SHOW_VLAN"
    }}
}}

send "exit\\r"
expect "{hostname}>"
send "exit\\r"
expect eof
'''
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.exp', delete=False) as f:
        f.write(script)
        script_path = f.name
    
    try:
        os.chmod(script_path, 0o700)
        # Subprocess timeout MUSS größer sein als expect timeout
        result = subprocess.run([script_path], capture_output=True, text=True, timeout=90)
        os.unlink(script_path)
        
        # Parse VLAN IDs from output
        existing_vlans = []
        vlan_details = []
        
        for line in result.stdout.split('\n'):
            # Match VLAN lines: "10    Management           active    Gi1/0/1..."
            # Format: VLAN_ID  NAME  STATUS  PORTS
            match = re.match(r'^\s*(\d+)\s+(\S+)\s+(active|suspend)', line)
            if match:
                vlan_id = int(match.group(1))
                vlan_name = match.group(2)
                if 1 <= vlan_id <= 4094:
                    existing_vlans.append(vlan_id)
                    vlan_details.append({
                        'id': vlan_id,
                        'name': vlan_name
                    })
        
        return {
            'vlan_ids': sorted(list(set(existing_vlans))),
            'vlan_details': vlan_details,
            'raw_output': result.stdout
        }
    
    except subprocess.TimeoutExpired as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        raise Exception(f"Command timed out after 90 seconds")
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        raise


def main():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type='str', required=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            hostname=dict(type='str', required=False, default='SG3210'),
            debug=dict(type='bool', required=False, default=False),
        ),
        supports_check_mode=True
    )
    
    try:
        result = check_existing_vlans(
            module.params['host'],
            module.params['username'],
            module.params['password'],
            module.params['hostname']
        )
        
        output = {
            'changed': False,
            'existing_vlans': result['vlan_ids'],
            'vlan_details': result['vlan_details'],
            'vlan_count': len(result['vlan_ids'])
        }
        
        # Debug-Output nur wenn angefordert
        if module.params['debug']:
            output['raw_output'] = result['raw_output']
        
        module.exit_json(**output)
    
    except Exception as e:
        module.fail_json(msg=f"Failed to check VLANs: {str(e)}")


if __name__ == '__main__':
    main()
