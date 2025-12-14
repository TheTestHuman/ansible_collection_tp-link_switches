# Managed Switches (TP-Link SG3210)

## Übersicht

Ansible-Module für TP-Link SG3210 Managed Switch via SSH mit `expect`.

**WICHTIG:** Dieser Switch hat spezielle TTY-Anforderungen und funktioniert **nur** mit `expect`, nicht mit Standard-Python-SSH-Bibliotheken! Siehe [Dokumentation](../docs/sg3210-ssh-expect-solution.md) für Details.

## Module

### tp_link_ssh_vlan_expect
VLAN-Management via SSH

**Parameter:**
- `host`: Switch IP
- `username`: SSH Username
- `password`: SSH Password
- `vlan_id`: VLAN ID (1-4094)
- `vlan_name`: VLAN Name

### tp_link_ssh_port_expect
Port-Konfiguration via SSH

**Parameter:**
- `host`: Switch IP
- `username`: SSH Username  
- `password`: SSH Password
- `port`: Port-Nummer (1-10)
- `mode`: `access` oder `trunk`
- `access_vlan`: VLAN ID für Access-Mode
- `trunk_vlans`: Komma-separierte VLAN-Liste für Trunk (z.B. "10,20,30")

## Voraussetzungen
```bash
# expect installieren
sudo apt-get install expect -y

# SSH auf dem Switch aktivieren (über Web-Interface)
# System Tools → User Config → SSH: Enable
```

## Verwendung

### Inventory konfigurieren

`inventory/production.yml`:
```yaml
all:
  children:
    managed_switches:
      hosts:
        switch-sg3210:
          ansible_host: 192.168.0.1
          switch_model: "TL-SG3210"
          total_ports: 10
```

`inventory/host_vars/switch-sg3210.yml`:
```yaml
switch_ip_address: "192.168.0.1"
admin_password: "neinnein"

port_roles:
  management_trunk: 1
  management_access: [2]
  clients: [3, 4]
  guests: [5, 6]
  iot: [7, 8]
```

### VLANs und Ports konfigurieren
```bash
cd ~/ansible_collection_tp-link_switches/managed
ansible-playbook -i inventory/production.yml playbooks/configure-vlans.yml -v
```

## Port-Bezeichnungen

- Ports 1-8: `gigabitEthernet 1/0/1` bis `1/0/8` (Copper)
- Ports 9-10: `gigabitEthernet 1/0/9` bis `1/0/10` (SFP - aktuell nicht verwendet)

## Troubleshooting

### SSH-Key-Probleme
```bash
# SSH ohne Public-Key-Auth
ssh -o PubkeyAuthentication=no admin@192.168.0.1
```

In `inventory/group_vars/all.yml` hinzufügen:
```yaml
ansible_ssh_common_args: '-o PubkeyAuthentication=no'
```

### expect nicht gefunden
```bash
sudo apt-get install expect -y
```

### Konfiguration funktioniert nicht

1. Manuell per SSH testen ob Befehle funktionieren
2. Prüfen ob SSH aktiviert ist (Web-Interface)
3. Logs prüfen: Module geben stdout zurück

## Weitere Dokumentation

- [Warum expect?](../docs/sg3210-ssh-expect-solution.md) - Ausführliche Erklärung des Problems
- [CLI Exploration](../docs/sg3210-cli-exploration.md) - CLI-Befehle und Struktur
