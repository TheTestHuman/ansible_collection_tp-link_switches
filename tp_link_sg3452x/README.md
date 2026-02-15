# TP-Link SG3452X Switch Management

Dieser Ordner enthält alle Module und Skripte für die Verwaltung von TP-Link SG3452X Switches.

## Übersicht

Der **SG3452X** ist ein Managed Switch mit 48 Gigabit-Ports plus 4 SFP+ Ports. Die CLI-Befehle sind identisch zum SG3210, jedoch unterscheidet sich der CLI-Prompt:

- **SG3210 Prompt:** `SG3210>`, `SG3210#`, `SG3210(config)#`
- **SG3452X Prompt:** `SG3452X>`, `SG3452X#`, `SG3452X(config)#`

Alle Module in diesem Ordner wurden vom SG3210 angepasst, um die unterschiedlichen Prompts zu unterstützen.

## Verfügbare Module

### library/
- `tp_link_initial_setup.py` - Erstmalige Einrichtung (Passwort + SSH)
- `tp_link_change_ip.py` - IP-Adresse ändern
- `tp_link_batch_vlan_expect.py` - VLAN-Konfiguration
- `tp_link_lag_expect.py` - Link Aggregation Groups (LAG)
- `tp_link_port_security_expect.py` - Port-Security Konfiguration
- `tp_link_config_backup.py` - Backup & Restore
- `inventory_manager.py` - Inventory-Verwaltung

## Unterschiede zum SG3210

| Feature | SG3210 | SG3452X |
|---------|--------|---------|
| Ports | 10 Gigabit | 48 Gigabit + 4 SFP+ |
| CLI-Befehle | Identisch | Identisch |
| CLI-Prompt | SG3210> | SG3452X> |
| Python-Module | tp_link_sg3210/library/ | tp_link_sg3452x/library/ |

## Nutzung

Die Module werden **nicht direkt** aufgerufen, sondern über die Playbooks in `generic_collection/playbooks/`:

```bash
cd generic_collection
ansible-playbook playbooks/take-ownership-sg3452x.yml
ansible-playbook playbooks/configure-vlans-sg3452x.yml
ansible-playbook playbooks/configure-lag-sg3452x.yml
ansible-playbook playbooks/configure-port-security-sg3452x.yml
ansible-playbook playbooks/backup-sg3452x.yml
```

## Inventory-Integration

Füge SG3452X-Switches zur Inventory-Datei `generic_collection/inventory/production.yml` hinzu:

```yaml
all:
  children:
    tp_link_sg3452x:
      hosts:
        sg3452x-datacenter:
          ansible_host: 10.0.50.1
          location: "Datacenter Rack 5"
          vlans:
            - vlan_id: 10
              name: "Management"
              untagged_ports: [1]
              tagged_ports: [45, 46, 47, 48]
```

Erstelle auch die Datei `generic_collection/inventory/group_vars/tp_link_sg3452x.yml`:

```yaml
---
ansible_connection: local
switch_type: tp_link_sg3452x
library_path: "{{ playbook_dir }}/../../tp_link_sg3452x/library"
```

## Factory Reset IP

Default IP nach Factory-Reset: **192.168.0.1**  
Default Credentials: `admin` / `admin`

## Port-Anzahl Anpassung

Da der SG3452X 48 Ports hat (statt 10 beim SG3210), müssen die Playbooks die richtige Port-Range verwenden. Dies ist bereits in den angepassten Playbooks berücksichtigt:

```yaml
all_ports: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
            21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38,
            39, 40, 41, 42, 43, 44, 45, 46, 47, 48]
```

## Weiteres

Für weitere Details siehe Dokumentation im Hauptverzeichnis unter `docs/`.
