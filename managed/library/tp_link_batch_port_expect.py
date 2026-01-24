#!/usr/bin/python
# -*- coding: utf-8 -*-

from ansible.module_utils.basic import AnsibleModule
import subprocess
import tempfile
import os

def create_batch_port_script(host, username, password, port_config, hostname):
    """Generate expect script for BATCH port configuration"""
    
    port_commands = ""
    
    # Trunk Ports
    for trunk in port_config.get('trunk_ports', []):
        port_commands += f'''send "interface gigabitEthernet 1/0/{trunk['port']}\\r"
expect "{hostname}(config-if)#"
send "switchport general allowed vlan {trunk['vlans']} tagged\\r"
expect "{hostname}(config-if)#"
send "exit\\r"
expect "{hostname}(config)#"
'''
    
    # Access Ports (gruppiert nach VLAN)
    for access in port_config.get('access_ports', []):
        port_commands += f'''send "interface gigabitEthernet 1/0/{access['port']}\\r"
expect "{hostname}(config-if)#"
send "switchport general allowed vlan {access['vlan']} untagged\\r"
expect "{hostname}(config-if)#"
send "switchport pvid {access['vlan']}\\r"
expect "{hostname}(config-if)#"
send "exit\\r"
expect "{hostname}(config)#"
'''
    
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

# Alle Ports konfigurieren
{port_commands}

# NUR EINMAL speichern!
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
        ),
        supports_check_mode=False
    )
    
    script = create_batch_port_script(
        module.params['host'],
        module.params['username'],
        module.params['password'],
        module.params['port_config'],
        module.params['hostname']
    )
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.exp', delete=False) as f:
        f.write(script)
        script_path = f.name
    
    try:
        os.chmod(script_path, 0o700)
        result = subprocess.run([script_path], capture_output=True, text=True, timeout=120)
        os.unlink(script_path)
        
        port_cfg = module.params['port_config']
        total_ports = len(port_cfg.get('trunk_ports', [])) + len(port_cfg.get('access_ports', []))

        
        module.exit_json(
            changed=True,
            msg=f"Configured {total_ports} ports in batch",
            ports_configured=total_ports,
            stdout=result.stdout
        )
    except Exception as e:
        if os.path.exists(script_path):
            os.unlink(script_path)
        module.fail_json(msg=str(e))

if __name__ == '__main__':
    main()
