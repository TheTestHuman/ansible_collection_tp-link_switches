#!/usr/bin/env python3
"""
Inventory Manager Module
- Fügt neue Switches zum Inventory hinzu
- Aktualisiert bestehende Einträge
- Unterstützt alle Switch-Typen (Cisco, TP-Link SG3210, TP-Link SG108E)

Getestet mit:
  - Ansible 2.9+
  - Python 3.8+
"""

import os
import re
import yaml
from datetime import datetime
from ansible.module_utils.basic import AnsibleModule


DOCUMENTATION = '''
---
module: inventory_manager
short_description: Manage switch entries in Ansible inventory
description:
    - Add new switches to inventory
    - Update existing switch entries
    - Support for multiple switch types
options:
    inventory_path:
        description: Path to the inventory YAML file
        required: true
    switch_name:
        description: Name of the switch (e.g., 2900xl-lab, sg3210-office)
        required: true
    switch_data:
        description: Dictionary with switch configuration data
        required: true
        type: dict
    action:
        description: Action to perform
        choices: ['add', 'update', 'remove', 'check']
        default: add
    force:
        description: Overwrite existing entry without asking
        type: bool
        default: false
'''

EXAMPLES = '''
- name: Add Cisco switch to inventory
  inventory_manager:
    inventory_path: "../inventory/production.yml"
    switch_name: "2900xl-lab"
    switch_data:
      ansible_host: "10.0.20.1"
      switch_type: "cisco_2900xl"
      switch_model: "WS-C2924C-XL-EN"
      switch_location: "Lab"
      ownership:
        taken: true
        taken_at: "2026-02-06T12:00:00Z"
        ios_version: "12.0(5.2)XU"
    action: add
'''


class InventoryManager:
    """Verwaltet das Ansible Inventory YAML"""
    
    def __init__(self, inventory_path):
        self.inventory_path = os.path.abspath(inventory_path)
        self.inventory = None
        self._load()
    
    def _load(self):
        """Inventory-Datei laden"""
        if not os.path.exists(self.inventory_path):
            raise FileNotFoundError(f"Inventory not found: {self.inventory_path}")
        
        with open(self.inventory_path, 'r', encoding='utf-8') as f:
            self.inventory = yaml.safe_load(f)
        
        # Sicherstellen dass die Grundstruktur existiert
        if 'all' not in self.inventory:
            self.inventory = {'all': {'hosts': {}, 'children': {}}}
        if 'hosts' not in self.inventory['all']:
            self.inventory['all']['hosts'] = {}
    
    def _save(self):
        """Inventory-Datei speichern"""
        # Backup erstellen
        backup_path = self.inventory_path + '.bak'
        if os.path.exists(self.inventory_path):
            with open(self.inventory_path, 'r') as f:
                backup_content = f.read()
            with open(backup_path, 'w') as f:
                f.write(backup_content)
        
        # YAML mit schöner Formatierung speichern
        with open(self.inventory_path, 'w', encoding='utf-8') as f:
            yaml.dump(
                self.inventory, 
                f, 
                default_flow_style=False, 
                allow_unicode=True,
                sort_keys=False,
                indent=2
            )
    
    def switch_exists(self, switch_name):
        """Prüft ob ein Switch bereits existiert"""
        return switch_name in self.inventory['all'].get('hosts', {})
    
    def get_switch(self, switch_name):
        """Gibt Switch-Daten zurück oder None"""
        return self.inventory['all'].get('hosts', {}).get(switch_name)
    
    def add_switch(self, switch_name, switch_data, force=False):
        """
        Fügt einen neuen Switch hinzu.
        
        Returns:
            (success, message, was_updated)
        """
        exists = self.switch_exists(switch_name)
        
        if exists and not force:
            return False, f"Switch '{switch_name}' already exists. Use force=true to overwrite.", False
        
        # Switch hinzufügen/aktualisieren
        self.inventory['all']['hosts'][switch_name] = switch_data
        
        # In die richtige Gruppe eintragen
        switch_type = switch_data.get('switch_type', '')
        self._add_to_group(switch_name, switch_type)
        
        # Speichern
        self._save()
        
        if exists:
            return True, f"Switch '{switch_name}' updated.", True
        else:
            return True, f"Switch '{switch_name}' added to inventory.", False
    
    def _add_to_group(self, switch_name, switch_type):
        """Fügt Switch zur passenden Typ-Gruppe hinzu"""
        if not switch_type:
            return
        
        # Gruppe erstellen falls nicht vorhanden
        if 'children' not in self.inventory['all']:
            self.inventory['all']['children'] = {}
        
        if switch_type not in self.inventory['all']['children']:
            self.inventory['all']['children'][switch_type] = {'hosts': {}}
        
        if 'hosts' not in self.inventory['all']['children'][switch_type]:
            self.inventory['all']['children'][switch_type]['hosts'] = {}
        
        # Switch zur Gruppe hinzufügen (Wert ist None in Gruppen)
        self.inventory['all']['children'][switch_type]['hosts'][switch_name] = None
    
    def remove_switch(self, switch_name):
        """Entfernt einen Switch aus dem Inventory"""
        if not self.switch_exists(switch_name):
            return False, f"Switch '{switch_name}' not found."
        
        # Aus hosts entfernen
        del self.inventory['all']['hosts'][switch_name]
        
        # Aus allen Gruppen entfernen
        if 'children' in self.inventory['all']:
            for group_name, group_data in self.inventory['all']['children'].items():
                if 'hosts' in group_data and switch_name in group_data['hosts']:
                    del group_data['hosts'][switch_name]
        
        self._save()
        return True, f"Switch '{switch_name}' removed from inventory."
    
    def list_switches(self, switch_type=None):
        """Listet alle Switches auf, optional gefiltert nach Typ"""
        switches = []
        for name, data in self.inventory['all'].get('hosts', {}).items():
            if switch_type is None or data.get('switch_type') == switch_type:
                switches.append({'name': name, 'data': data})
        return switches


def build_switch_data(params):
    """Baut das Switch-Daten-Dictionary aus den Modul-Parametern"""
    data = {
        'ansible_host': params['ansible_host'],
        'switch_type': params['switch_type'],
        'switch_model': params.get('switch_model', ''),
        'switch_location': params.get('switch_location', 'Unknown'),
        'switch_role': params.get('switch_role', 'access'),
    }
    
    # Connection-Daten
    if params.get('connection'):
        data['connection'] = params['connection']
    else:
        # Defaults basierend auf Switch-Typ
        if params['switch_type'] == 'cisco_2900xl':
            data['connection'] = {'protocol': 'telnet', 'port': 23}
        elif params['switch_type'] == 'tp_link_sg3210':
            data['connection'] = {'protocol': 'ssh', 'port': 22}
        elif params['switch_type'] == 'tp_link_sg108e':
            data['connection'] = {'protocol': 'udp', 'port': 29808}
    
    # CLI-Daten (optional)
    if params.get('cli'):
        data['cli'] = params['cli']
    
    # Ownership-Daten
    data['ownership'] = {
        'taken': True,
        'taken_at': params.get('taken_at', datetime.utcnow().isoformat() + 'Z'),
    }
    
    # Hardware-spezifische Ownership-Daten
    if params.get('hardware_info'):
        hw = params['hardware_info']
        if 'ios_version' in hw:
            data['ownership']['ios_version'] = hw['ios_version']
        if 'firmware_version' in hw:
            data['ownership']['firmware_version'] = hw['firmware_version']
        if 'mac_address' in hw:
            data['ownership']['mac_address'] = hw['mac_address']
        if 'serial_number' in hw:
            data['ownership']['serial_number'] = hw['serial_number']
    
    # Config (initial leer oder aus Parameter)
    data['config'] = params.get('config', None)
    
    return data


def run_module():
    module_args = dict(
        inventory_path=dict(type='str', required=True),
        switch_name=dict(type='str', required=True),
        ansible_host=dict(type='str', required=False),
        switch_type=dict(type='str', required=False),
        switch_model=dict(type='str', required=False),
        switch_location=dict(type='str', required=False, default='Unknown'),
        switch_role=dict(type='str', required=False, default='access'),
        connection=dict(type='dict', required=False),
        cli=dict(type='dict', required=False),
        hardware_info=dict(type='dict', required=False),
        config=dict(type='dict', required=False),
        taken_at=dict(type='str', required=False),
        action=dict(type='str', default='add', choices=['add', 'update', 'remove', 'check']),
        force=dict(type='bool', default=False),
        switch_data=dict(type='dict', required=False),  # Alternative: komplettes Dict übergeben
    )
    
    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)
    
    result = dict(
        changed=False,
        message='',
        switch_name=module.params['switch_name'],
        switch_exists=False,
        was_updated=False,
    )
    
    try:
        inventory_path = module.params['inventory_path']
        
        # Relativen Pfad auflösen
        if not os.path.isabs(inventory_path):
            # Versuche relativ zum Playbook-Verzeichnis
            playbook_dir = os.environ.get('PWD', os.getcwd())
            inventory_path = os.path.join(playbook_dir, inventory_path)
        
        manager = InventoryManager(inventory_path)
        
        switch_name = module.params['switch_name']
        action = module.params['action']
        force = module.params['force']
        
        result['switch_exists'] = manager.switch_exists(switch_name)
        
        if action == 'check':
            # Nur prüfen ob Switch existiert
            if result['switch_exists']:
                result['message'] = f"Switch '{switch_name}' exists in inventory."
                result['switch_data'] = manager.get_switch(switch_name)
            else:
                result['message'] = f"Switch '{switch_name}' not found in inventory."
            module.exit_json(**result)
        
        elif action == 'remove':
            if module.check_mode:
                result['changed'] = result['switch_exists']
                module.exit_json(**result)
            
            success, message = manager.remove_switch(switch_name)
            result['changed'] = success
            result['message'] = message
            module.exit_json(**result)
        
        elif action in ['add', 'update']:
            # Switch-Daten erstellen
            if module.params.get('switch_data'):
                switch_data = module.params['switch_data']
            else:
                if not module.params.get('ansible_host') or not module.params.get('switch_type'):
                    module.fail_json(
                        msg="ansible_host and switch_type are required for add/update action",
                        **result
                    )
                switch_data = build_switch_data(module.params)
            
            if module.check_mode:
                result['changed'] = True
                result['switch_data'] = switch_data
                module.exit_json(**result)
            
            # Bei update immer force=True
            if action == 'update':
                force = True
            
            success, message, was_updated = manager.add_switch(switch_name, switch_data, force)
            
            if not success:
                module.fail_json(msg=message, **result)
            
            result['changed'] = True
            result['message'] = message
            result['was_updated'] = was_updated
            result['switch_data'] = switch_data
            
    except FileNotFoundError as e:
        module.fail_json(msg=str(e), **result)
    except Exception as e:
        module.fail_json(msg=f"ERROR_INVENTORY_MANAGER: {str(e)}", **result)
    
    module.exit_json(**result)


if __name__ == '__main__':
    run_module()
