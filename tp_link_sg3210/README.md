TP-Link SG3210 Managed Switch - Ansible Module
Ansible-Module zur Automatisierung von TP-Link SG3210 Managed Switches via SSH.
Übersicht
Diese Module nutzen expect statt Standard-Python-SSH-Bibliotheken, da der SG3210 spezielle TTY-Anforderungen hat. Siehe Dokumentation für technische Details.
Voraussetzungen
# expect installieren
sudo apt-get install expect -y

# SSH auf dem Switch aktivieren (Web-Interface)
# System Tools → User Config → SSH: Enable

Module
tp_link_batch_vlan_expect
Batch-VLAN-Konfiguration mit replace oder add Modus.
Parameter:
Parameter
Erforderlich
Default
Beschreibung
host
✅
-
Switch IP-Adresse
username
✅
-
SSH Username
password
✅
-
SSH Passwort
vlans
✅
-
Liste von VLANs [{id: 10, name: "Name"}, ...]
hostname
❌
SG3210
CLI Prompt Hostname
mode
❌
add
add oder replace
protected_vlans
❌
[1]
VLANs die nie gelöscht werden
Modi:
add: Fügt VLANs hinzu (keine Löschung)
replace: Löscht alle existierenden VLANs (außer protected), dann erstellt neue
Beispiel:
- tp_link_batch_vlan_expect:
    host: "{{ ansible_host }}"
    username: "{{ vault_switch_user }}"
    password: "{{ vault_switch_password }}"
    vlans:
      - id: 10
        name: "Management"
      - id: 20
        name: "Clients"
    mode: "replace"
    protected_vlans: [1]


tp_link_batch_port_expect
Batch-Port-Konfiguration (Trunk/Access) in einer SSH-Session.
Parameter:
Parameter
Erforderlich
Default
Beschreibung
host
✅
-
Switch IP-Adresse
username
✅
-
SSH Username
password
✅
-
SSH Passwort
hostname
❌
SG3210
CLI Prompt Hostname
trunk_ports
❌
[]
Liste von Trunk-Ports
access_ports
❌
[]
Liste [{port: 2, vlan: 10}, ...]
trunk_vlans
❌
[]
VLANs für Trunk-Ports
mode
❌
add
add oder replace
Beispiel:
- tp_link_batch_port_expect:
    host: "{{ ansible_host }}"
    username: "{{ vault_switch_user }}"
    password: "{{ vault_switch_password }}"
    trunk_ports: [1]
    trunk_vlans: [1, 10, 20, 30, 40]
    access_ports:
      - { port: 2, vlan: 10 }
      - { port: 3, vlan: 20 }
      - { port: 4, vlan: 20 }
    mode: "replace"


tp_link_lag_expect
Link Aggregation Group (LAG/Port-Channel) Konfiguration.
Parameter:
Parameter
Erforderlich
Default
Beschreibung
host
✅
-
Switch IP-Adresse
username
✅
-
SSH Username
password
✅
-
SSH Passwort
hostname
❌
SG3210
CLI Prompt Hostname
lag_id
✅
-
LAG ID (1-8)
ports
✅
-
Liste von Ports für LAG
lacp_mode
❌
active
active, passive, on
state
❌
present
present oder absent
Beispiel:
# LAG erstellen
- tp_link_lag_expect:
    host: "{{ ansible_host }}"
    username: "{{ vault_switch_user }}"
    password: "{{ vault_switch_password }}"
    lag_id: 1
    ports: [9, 10]
    lacp_mode: "active"
    state: "present"

# LAG entfernen
- tp_link_lag_expect:
    host: "{{ ansible_host }}"
    username: "{{ vault_switch_user }}"
    password: "{{ vault_switch_password }}"
    lag_id: 1
    ports: [9, 10]
    state: "absent"


tp_link_config_backup
Configuration Backup und Restore.
Parameter:
Parameter
Erforderlich
Default
Beschreibung
host
✅
-
Switch IP-Adresse
username
✅
-
SSH Username
password
✅
-
SSH Passwort
hostname
❌
SG3210
CLI Prompt Hostname
action
✅
-
Siehe Aktionen unten
backup_dir
❌
./backups
Verzeichnis für lokale Backups
backup_file
❌
auto
Dateiname für Backup
config_file
❌
-
Pfad zur Config-Datei (für restore_local)
Aktionen:
Aktion
Beschreibung
backup_switch
running-config → backup-config auf Switch
backup_local
running-config als Datei herunterladen
restore_switch
backup-config → startup-config (⚠️ Reboot nötig!)
restore_local
Config-Datei hochladen und anwenden
Beispiele:
# Backup auf Switch
- tp_link_config_backup:
    host: "{{ ansible_host }}"
    username: "{{ vault_switch_user }}"
    password: "{{ vault_switch_password }}"
    action: "backup_switch"

# Backup lokal speichern
- tp_link_config_backup:
    host: "{{ ansible_host }}"
    username: "{{ vault_switch_user }}"
    password: "{{ vault_switch_password }}"
    action: "backup_local"
    backup_dir: "/home/user/backups"

# Restore vom Switch-Backup
- tp_link_config_backup:
    host: "{{ ansible_host }}"
    username: "{{ vault_switch_user }}"
    password: "{{ vault_switch_password }}"
    action: "restore_switch"

⚠️ Bekannte Einschränkungen:
restore_switch: Erfordert Reboot um wirksam zu werden
restore_local: Fügt Config additiv hinzu, löscht keine bestehenden Einstellungen

Playbooks
Production Playbooks
Playbook
Beschreibung
playbooks/production/configure-all-switches.yml
Vollständige Switch-Konfiguration
Verwendung:
# Alle Switches konfigurieren
ansible-playbook playbooks/production/configure-all-switches.yml -v

# Einzelner Switch
ansible-playbook playbooks/production/configure-all-switches.yml --limit switch-sg3210-office -v

# Mit explizitem Modus
ansible-playbook playbooks/production/configure-all-switches.yml -e "vlan_mode=add port_mode=add" -v

Maintenance Playbooks
Playbook
Beschreibung
playbooks/maintenance/backup-switches.yml
Backup/Restore Operationen
Verwendung:
# Backup lokal speichern
ansible-playbook playbooks/maintenance/backup-switches.yml -e "backup_action=backup_local" -v

# Backup auf Switch
ansible-playbook playbooks/maintenance/backup-switches.yml -e "backup_action=backup_switch" -v

# Restore vom Switch-Backup
ansible-playbook playbooks/maintenance/backup-switches.yml -e "backup_action=restore_switch" -v

# Restore von lokaler Datei
ansible-playbook playbooks/maintenance/backup-switches.yml \
  -e "backup_action=restore_local" \
  -e "config_file=/absoluter/pfad/zur/config.cfg" -v


Inventory-Struktur
inventory/
├── production.yml              # Hosts-Definition
└── group_vars/
    └── all/
        ├── main.yml            # Allgemeine Variablen (VLANs, etc.)
        └── vault.yml           # Verschlüsselte Credentials

production.yml
all:
  children:
    managed_switches:
      hosts:
        switch-sg3210-office:
          ansible_host: 10.0.10.1
          location: "Office"
          cli:
            hostname: "SG3210"

group_vars/all/main.yml
common_vlans:
  - id: 1
    name: "System-VLAN"
  - id: 10
    name: "Management"
  - id: 20
    name: "Clients"

protected_vlans: [1]

group_vars/all/vault.yml (verschlüsselt)
vault_switch_user: "admin"
vault_switch_password: "geheim"
vault_tftp_server: "10.0.10.10"


Error Handling
Alle Module haben robustes Error Handling mit deutschen Fehlermeldungen:
Fehler
Meldung
Host nicht erreichbar
"Verbindung fehlgeschlagen: Host nicht erreichbar"
Falsches Passwort
"Authentifizierung fehlgeschlagen: Falscher Benutzername oder Passwort"
SSH-Port zu
"Verbindung abgelehnt: SSH-Port nicht offen"
Timeout
"Verbindungs-Timeout: Host antwortet nicht"
Beispiel-Output bei Fehler:
fatal: [switch-sg3210-office]: FAILED!
  msg: 'VLAN-Konfiguration fehlgeschlagen: Verbindung fehlgeschlagen: Host nicht erreichbar'
  host: 10.0.10.99
  return_code: 1


Troubleshooting
SSH-Verbindungsprobleme
# Manuell testen
ssh -o PubkeyAuthentication=no admin@10.0.10.1

# Verbose Ansible
ansible-playbook playbook.yml -vvv

expect nicht gefunden
sudo apt-get install expect -y
which expect  # Sollte /usr/bin/expect zeigen

Timeout-Probleme
Die Module haben optimierte Timeouts:
SSH ConnectTimeout: 10s
Expect Timeout: 30s
Gesamt-Timeout: 180s
Bei langsamen Netzwerken können diese in den Modulen angepasst werden.

Dateiübersicht
managed/
├── ansible.cfg                 # Ansible-Konfiguration
├── library/                    # Module
│   ├── tp_link_batch_vlan_expect.py
│   ├── tp_link_batch_port_expect.py
│   ├── tp_link_lag_expect.py
│   ├── tp_link_config_backup.py
│   ├── tp_link_port_security_expect.py
│   ├── tp_link_take_ownership.py
│   └── ...
├── playbooks/
│   ├── production/
│   │   └── configure-all-switches.yml
│   ├── maintenance/
│   │   └── backup-switches.yml
│   └── deprecated/             # Alte Playbooks
├── inventory/
│   ├── production.yml
│   └── group_vars/all/
├── backups/                    # Config-Backups
└── docs/planning/              # Planungsdokumente

