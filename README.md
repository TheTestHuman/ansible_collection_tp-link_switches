TP-Link Switch Ansible Collection
Ansible-Module und Playbooks zur Automatisierung von TP-Link Switches.
Unterstützte Switch-Typen
Typ
Modell
Protokoll
Status
Managed
SG3210
SSH + expect
✅ Produktionsreif
Easy Smart
SG108E
UDP (proprietär)
✅ Basis-Funktionalität
Projektstruktur
ansible_collection_tp-link_switches/
├── README.md                    # Diese Datei
├── docs/                        # Übergreifende Dokumentation
│   ├── sg3210-ssh-expect-solution.md
│   └── sg3210-cli-exploration.md
├── managed/                     # SG3210 Managed Switch
│   ├── README.md               # Detaillierte Doku
│   ├── library/                # Ansible-Module
│   ├── playbooks/              # Playbooks
│   ├── inventory/              # Inventory & Variablen
│   └── backups/                # Config-Backups
├── easy_smart/                  # SG108E Easy Smart Switch
│   ├── inventory/
│   ├── playbooks/
│   └── templates/
└── common/                      # Gemeinsame Ressourcen

Quick Start
Voraussetzungen
# Ansible installieren
sudo apt-get install ansible -y

# expect installieren (für Managed Switches)
sudo apt-get install expect -y

Managed Switch (SG3210)
cd managed/

# Vault-Passwort setzen
echo "dein-vault-passwort" > .vault_pass
chmod 600 .vault_pass

# Switch konfigurieren
ansible-playbook playbooks/production/configure-all-switches.yml --limit switch-sg3210-office -v

Easy Smart Switch (SG108E)
cd easy_smart/

# Switch konfigurieren (UDP-basiert, kein SSH)
ansible-playbook playbooks/configure-switch.yml -v

Dokumentation
Managed Switch (SG3210) - Vollständige Modul- und Playbook-Dokumentation
Warum expect? - Technische Hintergründe
CLI Exploration - Switch CLI-Befehle
Features
Managed Switch (SG3210)
Feature
Modul
Status
VLAN-Management
tp_link_batch_vlan_expect
✅
Port-Konfiguration
tp_link_batch_port_expect
✅
Link Aggregation (LAG)
tp_link_lag_expect
✅
Port Security
tp_link_port_security_expect
✅
Config Backup/Restore
tp_link_config_backup
✅
Initial Setup
tp_link_take_ownership
✅
Easy Smart Switch (SG108E)
Feature
Status
VLAN-Management
✅
Port-Konfiguration
✅
Initial Setup
✅
Entwicklung
Dieses Projekt entstand im Rahmen einer akademischen Arbeit zur Netzwerkautomatisierung mit Ansible.
Besonderheiten
Managed Switches (SG3210): Erfordern expect statt Standard-SSH-Bibliotheken aufgrund spezieller TTY-Anforderungen
Easy Smart Switches (SG108E): Nutzen ein proprietäres UDP-Protokoll (kein SSH/Telnet)
Erweiterbarkeit
Die Struktur ist für weitere Switch-Typen erweiterbar:
Neue Switch-Familie → Neuer Ordner (z.B. cisco/)
Gemeinsame Logik → common/ Ordner
Übergreifende Playbooks möglich
Lizenz
MIT License
Autor
Entwickelt als Forschungsprojekt zur Ansible-basierten Netzwerkautomatisierung.
