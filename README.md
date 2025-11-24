# TP-Link Switch Management with Ansible

Ansible-basiertes Management für TP-Link Switches - sowohl Easy Smart als auch Managed Switches.

## 🏗️ Projekt-Struktur

### Easy Smart Switches (SG108E)
- **Verzeichnis:** `easy_smart/`
- **Collection:** rgl.tp_link_easy_smart_switch
- **Protokoll:** UDP (29808/29809)
- **Status:** ✅ Produktiv

### Managed Switches (SG3210)  
- **Verzeichnis:** `managed/`
- **Module:** Custom (in Entwicklung)
- **Protokoll:** SSH/Telnet + CLI
- **Status:** 🚧 In Entwicklung

## 📋 Quick Start

### Easy Smart Switch (SG108E)
```bash
cd easy_smart
ansible-playbook -i inventory/production.yml playbooks/configure-vlans.yml
```

### Managed Switch (SG3210)
```bash
cd managed
# CLI exploration und Module-Entwicklung läuft
```

## 📚 Dokumentation

Siehe `docs/` für detaillierte Informationen:
- [Switch-Typen Übersicht](docs/README.md)
- [SG3210 CLI Exploration](docs/sg3210-cli-exploration.md)

## 🚀 Roadmap

- [x] Easy Smart Switches (SG108E) vollständig automatisiert
- [ ] SG3210 CLI erkunden und dokumentieren
- [ ] Custom Ansible Module für SG3210 entwickeln
- [ ] Playbooks für Managed Switches erstellen
- [ ] SSH-Zugang für SG3210 aktivieren
- [ ] Beide Switch-Typen parallel betreiben

## 🔧 Installation

Siehe jeweilige README in den Unterverzeichnissen:
- `easy_smart/README.md`
- `managed/README.md`
