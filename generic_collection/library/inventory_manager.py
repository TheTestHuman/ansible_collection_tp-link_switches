#!/usr/bin/env python3
"""
Inventory Manager Module (Idempotent)
- Fügt neue Switches zum Inventory hinzu
- Aktualisiert bestehende Einträge NUR wenn sich etwas ändert
- Verwaltet Passwörter in vault.yml
- Unterstützt alle Switch-Typen (Cisco, TP-Link SG3210, TP-Link SG3452X, TP-Link SG108E)

Idempotenz:
  - changed=False wenn keine Änderungen nötig
  - changed=True nur bei tatsächlichen Änderungen

Getestet mit:
  - Ansible 2.9+
  - Python 3.8+
"""

import os
import yaml
from datetime import datetime
from ansible.module_utils.basic import AnsibleModule
import copy


DOCUMENTATION = '''
---
module: inventory_manager
short_description: Manage switch entries in Ansible inventory and vault (idempotent)
description:
    - Add new switches to inventory
    - Update existing switch entries ONLY if configuration differs
    - Manage passwords in vault.yml
    - Support for multiple switch types
    - IDEMPOTENT - returns changed=False if no changes needed
options:
    inventory_path:
        description: Path to the inventory YAML file
        required: true
    switch_name:
        description: Name of the switch (e.g., c2924-lab, sg3210-office)
        required: true
    switch_data:
        description: Dictionary with switch configuration data
        required: false
        type: dict
    action:
        description: Action to perform
        choices: ['add', 'update', 'remove', 'check']
        default: add
    force:
        description: Overwrite existing entry without asking
        type: bool
        default: false
    vault_path:
        description: Path to vault.yml for password storage
        required: false
    switch_password:
        description: Password to store in vault (only used with vault_path)
        required: false
        no_log: true
'''

EXAMPLES = '''
- name: Add Cisco switch to inventory with vault password
  inventory_manager:
    inventory_path: "../inventory/production.yml"
    vault_path: "../inventory/vault.yml"
    switch_name: "c2924-lab"
    switch_password: "secret123"
    switch_data:
      ansible_host: "10.0.20.1"
      switch_type: "cisco_c2924"
    action: add

- name: Update switch (idempotent - only changes if different)
  inventory_manager:
    inventory_path: "../inventory/production.yml"
    switch_name: "sg3210-test"
    switch_data:
      ansible_host: "10.0.10.1"
      switch_type: "tp_link_sg3210"
      config:
        vlans: [...]
    action: update
    force: true
'''


def normalize_for_comparison(data):
    """
    Normalisiert Daten für den Vergleich.
    Sortiert Listen und konvertiert zu vergleichbaren Typen.
    """
    if data is None:
        return None
    
    if isinstance(data, dict):
        return {k: normalize_for_comparison(v) for k, v in sorted(data.items())}
    
    if isinstance(data, list):
        # Bei Listen von Dicts (z.B. VLANs) nach einem Key sortieren
        if len(data) > 0 and isinstance(data[0], dict):
            # Versuche nach vlan_id, id, oder name zu sortieren
            sort_key = None
            for key in ['vlan_id', 'id', 'name', 'port', 'lag_id']:
                if key in data[0]:
                    sort_key = key
                    break
            
            if sort_key:
                try:
                    sorted_data = sorted(data, key=lambda x: x.get(sort_key, 0))
                    return [normalize_for_comparison(item) for item in sorted_data]
                except TypeError:
                    pass
        
        # Einfache Listen sortieren wenn möglich
        try:
            return sorted([normalize_for_comparison(item) for item in data])
        except TypeError:
            return [normalize_for_comparison(item) for item in data]
    
    return data


def configs_are_equal(current, new):
    """
    Vergleicht zwei Konfigurationen nach Normalisierung.
    Ignoriert Felder die sich automatisch ändern (z.B. timestamps).
    """
    # Felder die beim Vergleich ignoriert werden
    ignore_fields = {'taken_at', 'last_updated'}
    
    def remove_ignored(data):
        if isinstance(data, dict):
            return {k: remove_ignored(v) for k, v in data.items() if k not in ignore_fields}
        if isinstance(data, list):
            return [remove_ignored(item) for item in data]
        return data
    
    current_clean = remove_ignored(current)
    new_clean = remove_ignored(new)
    
    current_norm = normalize_for_comparison(current_clean)
    new_norm = normalize_for_comparison(new_clean)
    
    return current_norm == new_norm


class VaultManager:
    """Verwaltet die vault.yml Datei"""
    
    def __init__(self, vault_path):
        self.vault_path = os.path.abspath(vault_path)
        self.vault = None
        self._load()
    
    def _load(self):
        """Vault-Datei laden"""
        if not os.path.exists(self.vault_path):
            self.vault = {
                'vault_default_username': 'admin',
                'vault_default_password': 'neinnein',
                'vault_passwords': {}
            }
            return
        
        with open(self.vault_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if content.startswith('$ANSIBLE_VAULT'):
            raise ValueError("vault.yml is encrypted. Please decrypt first or use --ask-vault-pass")
        
        self.vault = yaml.safe_load(content) or {}
        
        if 'vault_passwords' not in self.vault:
            self.vault['vault_passwords'] = {}
        if 'vault_default_password' not in self.vault:
            self.vault['vault_default_password'] = 'neinnein'
        if 'vault_default_username' not in self.vault:
            self.vault['vault_default_username'] = 'admin'
    
    def _save(self):
        """Vault-Datei speichern"""
        backup_path = self.vault_path + '.bak'
        if os.path.exists(self.vault_path):
            with open(self.vault_path, 'r') as f:
                backup_content = f.read()
            if not backup_content.startswith('$ANSIBLE_VAULT'):
                with open(backup_path, 'w') as f:
                    f.write(backup_content)
        
        header = '''---
# =============================================================================
# Ansible Vault - Credentials
# =============================================================================
# Diese Datei sollte verschlüsselt werden:
#   ansible-vault encrypt vault.yml
# =============================================================================

'''
        
        yaml_content = yaml.dump(
            self.vault,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            indent=2
        )
        
        with open(self.vault_path, 'w', encoding='utf-8') as f:
            f.write(header + yaml_content)
    
    def get_password(self, switch_name):
        """Passwort für einen Switch abrufen"""
        if self.vault['vault_passwords'] and switch_name in self.vault['vault_passwords']:
            return self.vault['vault_passwords'][switch_name]
        return self.vault.get('vault_default_password', 'neinnein')
    
    def set_password(self, switch_name, password):
        """
        Passwort für einen Switch setzen.
        Returns: True wenn geändert, False wenn identisch
        """
        if self.vault['vault_passwords'] is None:
            self.vault['vault_passwords'] = {}
        
        current_password = self.vault['vault_passwords'].get(switch_name)
        
        if current_password == password:
            return False  # Keine Änderung
        
        self.vault['vault_passwords'][switch_name] = password
        self._save()
        return True
    
    def remove_password(self, switch_name):
        """Passwort für einen Switch entfernen"""
        if self.vault['vault_passwords'] and switch_name in self.vault['vault_passwords']:
            del self.vault['vault_passwords'][switch_name]
            self._save()
            return True
        return False


class InventoryManager:
    """Verwaltet das Ansible Inventory YAML (idempotent)"""
    
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
        
        if 'all' not in self.inventory:
            self.inventory = {'all': {'hosts': {}, 'children': {}}}
        if 'hosts' not in self.inventory['all']:
            self.inventory['all']['hosts'] = {}
    
    def _save(self):
        """Inventory-Datei speichern"""
        backup_path = self.inventory_path + '.bak'
        if os.path.exists(self.inventory_path):
            with open(self.inventory_path, 'r') as f:
                backup_content = f.read()
            with open(backup_path, 'w') as f:
                f.write(backup_content)
        
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
        Fügt einen neuen Switch hinzu oder aktualisiert einen bestehenden.
        IDEMPOTENT: Gibt changed=False zurück wenn keine Änderungen nötig.
        
        Returns:
            (success, message, changed)
        """
        exists = self.switch_exists(switch_name)
        
        if exists and not force:
            return False, f"Switch '{switch_name}' already exists. Use force=true to overwrite.", False
        
        if exists:
            # Vergleiche aktuelle mit neuer Konfiguration
            current_data = self.get_switch(switch_name)
            
            if configs_are_equal(current_data, switch_data):
                # Keine Änderungen nötig
                return True, f"Switch '{switch_name}' already up-to-date.", False
        
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
            return True, f"Switch '{switch_name}' added to inventory.", True
    
    def _add_to_group(self, switch_name, switch_type):
        """Fügt Switch zur passenden Typ-Gruppe hinzu"""
        if not switch_type:
            return
        
        if 'children' not in self.inventory['all']:
            self.inventory['all']['children'] = {}
        
        if switch_type not in self.inventory['all']['children']:
            self.inventory['all']['children'][switch_type] = {'hosts': {}}
        
        if 'hosts' not in self.inventory['all']['children'][switch_type]:
            self.inventory['all']['children'][switch_type]['hosts'] = {}
        
        self.inventory['all']['children'][switch_type]['hosts'][switch_name] = None
    
    def remove_switch(self, switch_name):
        """Entfernt einen Switch aus dem Inventory"""
        if not self.switch_exists(switch_name):
            return False, f"Switch '{switch_name}' not found.", False
        
        del self.inventory['all']['hosts'][switch_name]
        
        if 'children' in self.inventory['all']:
            for group_name, group_data in self.inventory['all']['children'].items():
                if 'hosts' in group_data and switch_name in group_data['hosts']:
                    del group_data['hosts'][switch_name]
        
        self._save()
        return True, f"Switch '{switch_name}' removed from inventory.", True
    
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
    
    if params.get('connection'):
        conn = dict(params['connection'])
        conn.pop('password', None)
        data['connection'] = conn
    else:
        if params['switch_type'] == 'cisco_c2924':
            data['connection'] = {'protocol': 'telnet', 'port': 23}
        elif params['switch_type'] in ['tp_link_sg3210', 'tp_link_sg3452x']:
            data['connection'] = {'protocol': 'ssh', 'port': 22}
        elif params['switch_type'] == 'tp_link_sg108e':
            data['connection'] = {'protocol': 'udp', 'port': 29808}
    
    if params.get('cli'):
        data['cli'] = params['cli']
    
    data['ownership'] = {
        'taken': True,
        'taken_at': params.get('taken_at', datetime.utcnow().isoformat() + 'Z'),
    }
    
    if params.get('hardware_info'):
        hw = params['hardware_info']
        for key in ['ios_version', 'firmware_version', 'mac_address', 'serial_number']:
            if key in hw:
                data['ownership'][key] = hw[key]
    
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
        switch_data=dict(type='dict', required=False),
        vault_path=dict(type='str', required=False),
        switch_password=dict(type='str', required=False, no_log=True),
    )
    
    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)
    
    result = dict(
        changed=False,
        message='',
        switch_name=module.params['switch_name'],
        switch_exists=False,
        was_updated=False,
        vault_updated=False,
    )
    
    try:
        inventory_path = module.params['inventory_path']
        vault_path = module.params.get('vault_path')
        switch_password = module.params.get('switch_password')
        
        # Relativen Pfad auflösen
        if not os.path.isabs(inventory_path):
            playbook_dir = os.environ.get('PWD', os.getcwd())
            inventory_path = os.path.join(playbook_dir, inventory_path)
        
        if vault_path and not os.path.isabs(vault_path):
            playbook_dir = os.environ.get('PWD', os.getcwd())
            vault_path = os.path.join(playbook_dir, vault_path)
        
        manager = InventoryManager(inventory_path)
        
        vault_manager = None
        if vault_path:
            vault_manager = VaultManager(vault_path)
        
        switch_name = module.params['switch_name']
        action = module.params['action']
        force = module.params['force']
        
        result['switch_exists'] = manager.switch_exists(switch_name)
        
        if action == 'check':
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
            
            success, message, changed = manager.remove_switch(switch_name)
            result['changed'] = changed
            result['message'] = message
            
            if changed and vault_manager:
                vault_manager.remove_password(switch_name)
                result['vault_updated'] = True
            
            module.exit_json(**result)
        
        elif action in ['add', 'update']:
            if module.params.get('switch_data'):
                switch_data = module.params['switch_data']
                if 'connection' in switch_data and 'password' in switch_data['connection']:
                    if not switch_password:
                        switch_password = switch_data['connection']['password']
                    del switch_data['connection']['password']
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
            
            if action == 'update':
                force = True
            
            success, message, changed = manager.add_switch(switch_name, switch_data, force)
            
            if not success:
                module.fail_json(msg=message, **result)
            
            result['changed'] = changed
            result['message'] = message
            result['was_updated'] = changed
            result['switch_data'] = switch_data
            
            # Passwort in Vault speichern (nur wenn sich geändert hat)
            if vault_manager and switch_password:
                vault_changed = vault_manager.set_password(switch_name, switch_password)
                if vault_changed:
                    result['vault_updated'] = True
                    result['changed'] = True
                    if not changed:
                        result['message'] = f"Switch '{switch_name}' unchanged, but password updated in vault."
            
    except FileNotFoundError as e:
        module.fail_json(msg=str(e), **result)
    except ValueError as e:
        module.fail_json(msg=str(e), **result)
    except Exception as e:
        module.fail_json(msg=f"ERROR_INVENTORY_MANAGER: {str(e)}", **result)
    
    module.exit_json(**result)


if __name__ == '__main__':
    run_module()
