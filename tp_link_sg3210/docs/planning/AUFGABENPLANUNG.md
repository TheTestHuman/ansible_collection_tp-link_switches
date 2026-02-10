# Ansible TP-Link Switch Automation - Aufgabenplanung

**Projektstand:** Tag 5 abgeschlossen, Tag 6 begonnen  
**Erstellt:** 25. Januar 2025

---

## Kurzfassung (für Git Commit)

```
Tag 6 begonnen - Aufgabenplanung erstellt

Status:
- Check-Modul (tp_link_check_vlan_expect.py): Timeout gefixt, aber Parsing 
  funktioniert nicht zuverlässig → zurückgestellt
- Neuer Ansatz: Replace/Add-Modus statt Idempotenz-Check

Nächste Schritte:
- Paket 1: VLAN-Modul mit replace/add Modus
- Paket 2: Port-Modul mit replace/add Modus
- Paket 3: Haupt-Playbook Integration
- Paket 4: Error Handling
- Paket 5: Multi-Switch & LAG
- Paket 6: Performance-Optimierung
- Paket 7: Backup-Modul & Default-Config
- Paket 8: Dokumentation (Installation, Flags, Nutzung)
- Paket 9: GitLab Best Practices Review (mit Context7)
- Paket 10: Ansible-Abstraktionsebene (Collection-Struktur)

Offene Fragen:
- VLAN-Löschbefehle manuell testen (no vlan X)
- Port-Befehle verifizieren
```

---

## Paket 1: VLAN-Modul mit Replace/Add-Modus (~2 Stunden)

**Ziel:** `tp_link_batch_vlan_expect.py` funktioniert zuverlässig mit zwei Modi

### Aufgaben:
1. [ ] Manuelle SSH-Session: VLAN-Löschbefehle dokumentieren
   - `no vlan 10` testen
   - Reihenfolge bei mehreren VLANs prüfen
   - Fehlermeldungen notieren (z.B. "VLAN in use")
   
2. [ ] Modul `tp_link_batch_vlan_expect.py` erweitern:
   - Parameter `mode`: `replace` oder `add`
   - Parameter `protected_vlans`: Liste (default: `[1]`)
   - Bei `mode: replace`: Alle VLANs außer protected löschen, dann neu erstellen
   - Bei `mode: add`: VLANs nur hinzufügen
   
3. [ ] Testen mit Office-Switch:
   ```bash
   ansible switch-sg3210-office -m tp_link_batch_vlan_expect \
     -a "host=10.0.10.1 username=admin password=neinnein vlans='[{id: 10, name: Test}]' mode=replace"
   ```

4. [ ] Git commit: "Paket 1: VLAN-Modul mit replace/add Modus"

---

## Paket 2: Port-Modul mit Replace/Add-Modus (~2 Stunden)

**Ziel:** `tp_link_batch_port_expect.py` funktioniert zuverlässig

### Aufgaben:
1. [ ] Manuelle SSH-Session: Port-Befehle dokumentieren
   - Trunk-Port Befehle
   - Access-Port Befehle
   - "Clear all VLANs from port" Befehl verifizieren
   
2. [ ] Modul `tp_link_batch_port_expect.py` prüfen/erweitern:
   - Parameter `mode`: `replace` oder `add`
   - Parameter `clear_existing`: true/false
   - Robustes Expect-Script (wie bei VLAN-Modul)
   
3. [ ] Testen mit Office-Switch:
   ```bash
   ansible switch-sg3210-office -m tp_link_batch_port_expect \
     -a "host=10.0.10.1 username=admin password=neinnein port_config='{...}' mode=replace"
   ```

4. [ ] Git commit: "Paket 2: Port-Modul mit replace/add Modus"

---

## Paket 3: Haupt-Playbook Integration (~2 Stunden)

**Ziel:** `configure-all-switches.yml` nutzt die neuen Modi

### Aufgaben:
1. [ ] Playbook-Variablen hinzufügen:
   ```yaml
   vars:
     vlan_mode: "replace"  # oder "add"
     port_mode: "replace"
     protected_vlans: [1]
   ```

2. [ ] Tasks anpassen für neue Parameter

3. [ ] Vollständiger Test auf Office-Switch:
   ```bash
   ansible-playbook playbooks/production/configure-all-switches.yml \
     --limit switch-sg3210-office -v
   ```

4. [ ] Laufzeit messen und dokumentieren

5. [ ] Git commit: "Paket 3: Haupt-Playbook mit Modi-Integration"

---

## Paket 4: Error Handling & Validierung (~2 Stunden)

**Ziel:** Robuste Fehlerbehandlung in allen Modulen

### Aufgaben:
1. [ ] Expect-Timeouts standardisieren:
   - Expect-Script: 60 Sekunden
   - Subprocess: 90 Sekunden
   
2. [ ] Fehlerszenarien behandeln:
   - Switch nicht erreichbar
   - Falsches Passwort
   - VLAN in use (kann nicht gelöscht werden)
   - Unerwartete Prompts
   
3. [ ] Aussagekräftige Fehlermeldungen:
   ```python
   module.fail_json(msg="VLAN 10 konnte nicht gelöscht werden: in use on port 3")
   ```

4. [ ] Post-Config Validierung (optional):
   - Nach Konfiguration: `show vlan` ausführen
   - Prüfen ob erwartete VLANs existieren

5. [ ] Git commit: "Paket 4: Error Handling verbessert"

---

## Paket 5: Weitere Switches & LAG (~2 Stunden)

**Ziel:** Warehouse und Lab Switches konfigurierbar (wenn erreichbar)

### Aufgaben:
1. [ ] Erreichbarkeit prüfen:
   ```bash
   ping -c 3 10.0.10.2  # Warehouse
   ping -c 3 10.0.10.3  # Lab
   ```

2. [ ] Falls erreichbar: Test-Playbook ausführen

3. [ ] LAG-Modul (`tp_link_lag_expect.py`) testen:
   ```bash
   ansible-playbook playbooks/configure-lag.yml --limit switch-sg3210-office
   ```

4. [ ] Multi-Switch Playbook-Run (alle erreichbaren):
   ```bash
   ansible-playbook playbooks/production/configure-all-switches.yml
   ```

5. [ ] Git commit: "Paket 5: Multi-Switch und LAG getestet"

---

## Paket 6: Performance-Optimierung (~2 Stunden)

**Ziel:** Laufzeit von ~10 Minuten auf <3 Minuten reduzieren

### Aufgaben:
1. [ ] Aktuelle Laufzeit messen und dokumentieren

2. [ ] Optimierungen identifizieren:
   - Weniger SSH-Sessions (alles in einer Session?)
   - Nur einmal `copy running-config startup-config`
   - Parallele Ausführung bei mehreren Switches?
   
3. [ ] "All-in-One" Modul evaluieren:
   - VLANs + Ports + Save in einem Expect-Script
   - Tradeoff: Flexibilität vs. Performance
   
4. [ ] Optimierungen implementieren

5. [ ] Neue Laufzeit messen und vergleichen

6. [ ] Git commit: "Paket 6: Performance optimiert"

---

## Paket 7: Backup-Modul & Default-Konfiguration (~2 Stunden)

**Ziel:** Zuverlässiges Backup und Default-Config für neue Switches

### Aufgaben:
1. [ ] `tp_link_config_backup.py` verbessern:
   - Robustes Expect-Script (wie bei anderen Modulen)
   - Timeout erhöhen
   - Fehlerbehandlung verbessern
   - Backup-Datei mit Timestamp und Switch-Name
   
2. [ ] `tp_link_tftp_backup.py` prüfen und ggf. fixen

3. [ ] Default-Konfiguration erstellen:
   - Basis-Config für SG3210 (ohne Take-Ownership)
   - Standard-VLANs
   - Standard-Port-Layout
   - Als YAML-Template speichern
   
4. [ ] Playbook `restore-default-config.yml` erstellen:
   - Lädt Default-Config auf Switch
   - Für Reset/Neuinstallation

5. [ ] Backup-Playbook testen:
   ```bash
   ansible-playbook playbooks/config-backup.yml --limit switch-sg3210-office
   ```

6. [ ] Git commit: "Paket 7: Backup-Modul verbessert + Default-Config"

---

## Paket 8: Dokumentation (~2 Stunden)

**Ziel:** Vollständige Anleitung für Installation und Nutzung

### Aufgaben:
1. [ ] **INSTALL.md** erstellen:
   - Systemvoraussetzungen (expect, ansible, python)
   - Git clone Anleitung
   - Ansible-Konfiguration
   - Vault-Setup
   - Erste Schritte / Quick Start
   
2. [ ] **USAGE.md** erstellen:
   - Alle verfügbaren Playbooks auflisten
   - **Flag-Dokumentation** für jedes Playbook:
     ```bash
     # configure-all-switches.yml
     --limit <host>      # Nur bestimmten Switch
     --tags vlans        # Nur VLANs konfigurieren
     --tags ports        # Nur Ports konfigurieren
     -e "vlan_mode=add"  # Add statt Replace
     -e "port_mode=add"  # Add statt Replace
     -v / -vv / -vvv     # Verbosity
     --check             # Dry-Run (wenn implementiert)
     ```
   - Beispiel-Workflows
   
3. [ ] **README.md** aktualisieren:
   - Projekt-Übersicht
   - Links zu INSTALL.md und USAGE.md
   - Architektur-Diagramm (ASCII)
   
4. [ ] Modul-Docstrings vervollständigen

5. [ ] Git commit: "Paket 8: Dokumentation (INSTALL.md, USAGE.md)"

---

## Paket 9: GitLab Best Practices Review (~2 Stunden)

**Ziel:** Code-Qualität nach Ansible-Standards prüfen

### Aufgaben:
1. [ ] Context7 MCP-Server einrichten (neuer Chat)

2. [ ] Ansible Best Practices recherchieren:
   - Ansible-lint Regeln
   - Collection-Struktur
   - Naming Conventions
   - Variable Precedence
   
3. [ ] Code-Review durchführen:
   - Playbook-Struktur
   - Inventory-Organisation
   - Modul-Design
   - Fehlerbehandlung
   
4. [ ] Issues/TODOs dokumentieren

5. [ ] Quick-Fixes direkt umsetzen

6. [ ] Git commit: "Paket 9: Best Practices Review"

---

## Paket 10: Ansible-Abstraktionsebene (~2-4 Stunden)

**Ziel:** Projekt als echte Ansible Collection strukturieren

### Aufgaben:
1. [ ] Collection-Struktur evaluieren:
   ```
   collections/
   └── ansible_collections/
       └── meine_firma/
           └── tp_link_managed/
               ├── galaxy.yml
               ├── plugins/
               │   └── modules/
               │       ├── tp_link_vlan.py
               │       ├── tp_link_port.py
               │       └── tp_link_backup.py
               ├── roles/
               │   ├── base_config/
               │   ├── vlan_config/
               │   └── port_config/
               └── playbooks/
   ```

2. [ ] Module in Collection verschieben

3. [ ] Roles erstellen:
   - `base_config` - Grundkonfiguration
   - `vlan_config` - VLAN-Setup
   - `port_config` - Port-Setup
   - `backup` - Backup-Funktionen

4. [ ] galaxy.yml erstellen

5. [ ] Lokale Installation testen:
   ```bash
   ansible-galaxy collection install ./collections/ansible_collections/meine_firma/tp_link_managed
   ```

6. [ ] Git commit: "Paket 10: Collection-Struktur"

---

## Zusammenfassung

| Paket | Fokus | Geschätzte Zeit |
|-------|-------|-----------------|
| 1 | VLAN-Modul replace/add | ~2h |
| 2 | Port-Modul replace/add | ~2h |
| 3 | Haupt-Playbook Integration | ~2h |
| 4 | Error Handling | ~2h |
| 5 | Multi-Switch & LAG | ~2h |
| 6 | Performance | ~2h |
| 7 | Backup-Modul & Default-Config | ~2h |
| 8 | Dokumentation (INSTALL, USAGE, Flags) | ~2h |
| 9 | GitLab Best Practices Review (Context7) | ~2h |
| 10 | Ansible-Abstraktionsebene (Collection) | ~2-4h |

**Gesamt:** ~20-22 Stunden (10 Pakete)

---

## Priorisierung

**Hoch (Kernfunktionalität):**
- Paket 1-3: Module funktionsfähig machen

**Mittel (Stabilität):**
- Paket 4-6: Error Handling, Multi-Switch, Performance

**Nice-to-have (Professionalisierung):**
- Paket 7-10: Backup, Doku, Best Practices, Collection

---

## Notizen

- **Nächstes Paket:** Paket 1 (VLAN-Modul)
- **Voraussetzung:** Manuelle SSH-Tests für VLAN-Löschbefehle
- **Check-Modul:** Vorerst zurückgestellt (Parsing zu komplex)
- **Context7:** Für Paket 9 neuen Chat mit MCP-Server starten

---

## Git Commit für heute

```bash
cd ~/ansible_collection_tp-link_switches/managed
git add .
git commit -m "Tag 6: Aufgabenplanung erstellt

- Check-Modul Timeout gefixt (funktioniert, aber Parsing fehlerhaft)
- Neuer Ansatz: Replace/Add-Modus statt Idempotenz
- Aufgabenplanung in 10 Paketen à ~2h erstellt
- Nächster Schritt: VLAN-Löschbefehle manuell testen"
git push origin main
```

---
*Letzte Aktualisierung: 25. Januar 2025*
