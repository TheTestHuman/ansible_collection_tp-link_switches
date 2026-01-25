#!/usr/bin/python
# -*- coding: utf-8 -*-

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os

DOCUMENTATION = r'''
module: tp_link_batch_port_expect
short_description: Configure multiple ports in batch with ADD/REPLACE modes
description:
    - Configures multiple switch ports in a single SSH connection
    - Supports ADD mode (add VLANs to existing) and REPLACE mode (overwrite config)
    - Optional clear_existing flag to remove all VLANs before configuring
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
    port_config:
        description: Port configuration dict with trunk_ports and access_ports
        required: true
        type: dict
    hostname:
        description: Switch hostname for expect prompts
        required: false
        default: "SG3210"
    mode:
        description: Configuration mode
        required: false
        default: "replace"
        choices: ['add', 'replace']
    clear_existing:
        description: Clear existing VLAN config before applying (only with replace mode)
        required: false
        default: false
        type: bool
'''

EXAMPLES = r'''
# REPLACE mode - overwrite complete port config
- tp_link_batch_port_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    port_config:
      trunk_ports:
        - port: 1
          vlans: "1,10,20"
      access_ports:
        - port: 2
          vlan: 10
    mode: replace
    clear_existing: true

# ADD mode - add VLANs to existing trunk
- tp_link_batch_port_expect:
    host: 10.0.10.1
    username: admin
    password: secret
    port_config:
      trunk_ports:
        - port: 1
          vlans: "30,40"  # Add to existing VLANs
    mode: add
'''

def create_batch_port_script(host, username, password, port_config, hostname, mode, clear_existing):
    """Generate expect script for BATCH port configuration with ADD/REPLACE modes"""
    
    port_commands = ""
    
    # Optional: Clear existing VLAN configuration first (only in replace mode)
    if clear_existing and mode == 'replace':
        # Clear trunk ports
        for trunk in port_config.get('trunk_ports', []):
            port_commands += f'''# Clear existing VLANs on trunk port {trunk['port']}
send "interface gigabitEthernet 1/0/{trunk['port']}\\r"
expect "{hostname}(config-if)#"
send "no switchport general allowed vlan all\\r"
expect "{hostname}(config-if)#"
send "exit\\r"
expect "{hostname}(config)#"
'''
        
        # Clear access ports
        for access in port_config.get('access_ports', []):
            port_commands += f'''# Clear existing VLANs on access port {access['port']}
send "interface gigabitEthernet 1/0/{access['port']}\\r"
expect "{hostname}(config-if)#"
send "no switchport general allowed vlan all\\r"
expect "{hostname}(config-if)#"
send "no switchport pvid\\r"
expect "{hostname}(config-if)#"
send "exit\\r"
expect "{hostname}(config)#"
'''
    
    # Configure Trunk Ports
    for trunk in port_config.get('trunk_ports', []):
        vlans = trunk['vlans']
        
        port_commands += f'''# Configure trunk port {trunk['port']} ({mode} mode)
send "interface gigabitEthernet 1/0/{trunk['port']}\\r"
expect "{hostname}(config-if)#"
send "switchport general allowed vlan {vlans} tagged\\r"
expect "{hostname}(config-if)#"
send "exit\\r"
expect "{hostname}(config)#"
'''
    
    # Configure Access Ports
    for access in port_config.get('access_ports', []):
        vlan = access['vlan']
        
        port_commands += f'''# Configure access port {access['port']} (VLAN {vlan})
send "interface gigabitEthernet 1/0/{access['port']}\\r"
expect "{hostname}(config-if)#"
send "switchport general allowed vlan {vlan} untagged\\r"
expect "{hostname}(config-if)#"
send "switchport pvid {vlan}\\r"
expect "{hostname}(config-if)#"
send "exit\\r"
expect "{hostname}(config)#"
'''
    
    # Build complete expect script
    script = f'''#!/usr/bin/expect -f
set timeout 90

spawn ssh -o PubkeyAuthentication=no {username}@{host}
expect "password:"
send "{password}\\r"
expect "{hostname}>"
send "enable\\r"
expect "{hostname}#"
send "configure\\r"
expect "{hostname}(config)#"

# Configure all ports
{port_commands}

# Save configuration (only once!)
send "exit\\r"
expect "{hostname}#"
send "copy running-config startup-config\\r"
expect "Saving user config OK!"
send "exit\\r"
expect eof
'''
    return script

def main():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type='str', required=True),
            username=dict(type='str', required=True),
            password=dict(type='str', required=True, no_log=True),
            port_config=dict(type='dict', required=True),
            hostname=dict(type='str', required=False, default='SG3210'),
            mode=dict(type='str', required=False, default='replace', 
                     choices=['add', 'replace']),
            clear_existing=dict(type='bool', required=False, default=False),
        ),
        supports_check_mode=False
    )
    
    # Validate: clear_existing only makes sense with replace mode
    if module.params['clear_existing'] and module.params['mode'] == 'add':
        module.fail_json(msg="clear_existing=true only works with mode=replace")
    
    # Generate expect script
    script = create_batch_port_script(
        module.params['host'],
        module.params['username'],
        module.params['password'],
        module.params['port_config'],
        module.params['hostname'],
        module.params['mode'],
        module.params['clear_existing']
    )
    
    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.exp', delete=False) as f:
        f.write(script)
        script_path = f.name
    
    try:
        os.chmod(script_path, 0o700)
        result = subprocess.run([script_path], capture_output=True, text=True, timeout=120)
        os.unlink(script_path)
        
        # Count configured ports
        port_cfg = module.params['port_config']
        total_ports = len(port_cfg.get('trunk_ports', [])) + len(port_cfg.get('access_ports', []))
        
        module.exit_json(
            changed=True,
            msg=f"Configured {total_ports} ports in batch ({module.params['mode']} mode)",
            ports_configured=total_ports,
            mode=module.params['mode'],
            clear_existing=module.params['clear_existing'],
            stdout=result.stdout
        )
    except subprocess.TimeoutExpired:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg="Timeout during batch port configuration")
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg=str(e))

if __name__ == '__main__':
    main()
