# Ansible_Collection_TP-Link_Switches

## start
Ansible Collection für TP-Link Easy Smart Switch Management mit flexibler VLAN-Konfiguration.


## Features

- **Automatisches Switch-Setup:** Take-Ownership via Ansible
- **VLAN-Management:** Flexible VLAN-Konfiguration per Playbook
- **Multi-Switch Support:** Skalierbar für beliebig viele Switches
- **Template-basiert:** Automatische Anpassung an verschiedene Port-Anzahlen (8, 10, 16 Ports)
- **GitLab-Integration:** Versionskontrolle und Dokumentation

## Voraussetzungen

- Ubuntu 20.04+ (oder andere Linux-Distribution)
- Ansible 2.9+
- Python 3.x
- TP-Link Easy Smart Switch (getestet mit TL-SG108E)
- Netzwerk-Zugang zum Switch (192.168.0.x)

## 🔧 Installation

### 1. Ansible Collection installieren
```bash
# Python-Abhängigkeiten
sudo apt-get install -y python3-netifaces

# Ansible Collection
ansible-galaxy collection install rgl.tp_link_easy_smart_switch
```

### 2. Repository klonen
```bash
git clone https://git.ide3.de/dein-username/ansible_collection_tp-link_switches.git
cd ansible_collection_tp-link_switches
```

### 3. Ansible Vault einrichten
```bash
# Vault-Passwort erstellen
echo "dein-vault-passwort" > .vault_pass
chmod 600 .vault_pass

# Vault-Datei entschlüsseln (falls vorhanden)
ansible-vault decrypt inventory/group_vars/vault.yml
```

## 🎯 Verwendung

### Ersten Switch übernehmen (Take Ownership)

**Voraussetzung:** Switch muss im Factory-Reset-Zustand sein (Reset-Button 10 Sekunden halten)
```bash
# Testlauf
ansible-playbook -i inventory/production.yml take-ownership.yml --check -v

# Ausführen
ansible-playbook -i inventory/production.yml take-ownership.yml -v
```

### VLANs konfigurieren
```bash
# Testlauf (Dry-Run)
ansible-playbook -i inventory/production.yml configure-vlans.yml --check -v

# Ausführen
ansible-playbook -i inventory/production.yml configure-vlans.yml -v

# Nur einen bestimmten Switch
ansible-playbook -i inventory/production.yml configure-vlans.yml --limit switch-sg108 -v
```

## 📁 Projektstruktur
.
├── inventory/
│   ├── production.yml              # Hauptinventory mit allen Switches
│   ├── group_vars/
│   │   ├── all.yml                 # Gemeinsame Variablen
│   │   └── vault.yml               # Verschlüsselte Passwörter (Ansible Vault)
│   └── host_vars/
│       ├── switch-sg108.yml        # Switch-spezifische Konfiguration
│       ├── switch-sg110.yml        # Weitere Switches...
│       └── switch-sg116.yml
├── templates/
│   ├── port_config.j2              # Template für Port-Konfiguration
│   └── vlan_config.j2              # Template für VLAN-Konfiguration
├── configure-vlans.yml             # Hauptplaybook für VLAN-Management
├── take-ownership.yml              # Playbook für Switch-Übernahme
├── README.md                       # Diese Datei
└── .gitignore                      # Git-Ignore-Regeln

