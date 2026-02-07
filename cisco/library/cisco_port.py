#!/usr/bin/env python3
"""
Cisco VLAN Configuration
- VLAN erstellen/löschen
- VLAN-Name setzen
"""

import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ansible.module_utils.basic import AnsibleModule
from cisco_telnet_connection import CiscoTelnetConnection


def get_existing_vlans(conn):
    """Aktuelle VLANs auslesen"""
    output = conn.execute("show vlan", wait=1)
    vlans = {}
    
    for line in output.split('\n'):
        # Format: 10   Management                       active
        match = re.match(r'^(\d+)\s+(\S+)\s+(active|suspend)', line)
        if match:
            vlans[int(match.group(1))] = match.group(2)
    
    return vlans


def run_module():
    module_args = dict(
        host=dict(type='str', required=True),
        password=dict(type='str', required=True, no_log=True),
        enable_password=dict(type='str', required=False, no_log=True),
        vlans=dict(type='list', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
    )
    
    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)
    result = dict(changed=False, message='', vlans_created=[], vlans_deleted=[])
    
    try:
        with CiscoTelnetConnection(
            host=module.params['host'],
            password=module.params['password'],
            enable_password=module.params.get('enable_password')
        ) as conn:
            conn.enable()
            existing = get_existing_vlans(conn)
            
            conn.configure()
            
            for vlan in module.params['vlans']:
                vlan_id = vlan['id']
                vlan_name = vlan.get('name', f'VLAN{vlan_id:04d}')
                
                if module.params['state'] == 'present':
                    if vlan_id not in existing:
                        conn.execute(f"vlan {vlan_id}")
                        conn.execute(f"name {vlan_name}")
                        conn.execute("exit")
                        result['vlans_created'].append(vlan_id)
                        result['changed'] = True
                        
                elif module.params['state'] == 'absent':
                    if vlan_id in existing and vlan_id != 1:
                        conn.execute(f"no vlan {vlan_id}")
                        result['vlans_deleted'].append(vlan_id)
                        result['changed'] = True
            
            conn.exit_configure()
            if result['changed']:
                conn.save_config()
            
            result['message'] = 'SUCCESS_VLAN_CONFIGURED'
            
    except Exception as e:
        module.fail_json(msg=f'ERROR_VLAN_FAILED: {str(e)}', **result)
    
    module.exit_json(**result)

if __name__ == '__main__':
    run_module()
