# SG3210 CLI Exploration

## Zugang
```bash
# Telnet (aktuell)
telnet 10.0.10.1

# SSH (noch zu aktivieren)
ssh admin@10.0.10.1
```

## Login
- **User:** admin
- **Password:** neinnein (wurde beim ersten Login geändert)

## CLI-Befehle (zu erkunden)

### System-Informationen
# SG3210 CLI Exploration - Ergebnisse

## Switch Information
- **Model:** Omada 8-Port Gigabit L2+ Managed Switch with 2 SFP Slots
- **Hardware:** SG3210 3.20
- **Software:** 3.20.1 Build 20240115 Rel.72847
- **MAC:** BC-07-1D-8F-AD-50
- **CLI-Type:** Cisco-ähnlich

## CLI Modi
- **User Mode:** `SG3210>`
- **Privileged Mode:** `SG3210#` (enable - kein Passwort)
- **Config Mode:** `configure terminal`

## Port-Bezeichnungen
- Ports 1-8: `Gi1/0/1` bis `Gi1/0/8` (Copper)
- Ports 9-10: `Gi1/0/9` bis `Gi1/0/10` (SFP/Fiber)

## VLAN-Struktur (Default)
- VLAN 1 (System-VLAN): Alle Ports

## Wichtige Befehle

### VLAN erstellen
```
configure terminal
vlan 10
name Management
exit
```

### Port zu VLAN zuweisen
```
interface gigabitEthernet 1/0/2
switchport access vlan 10
exit
```

### Trunk-Port konfigurieren
```
interface gigabitEthernet 1/0/1
switchport mode trunk
switchport trunk allowed vlan add 10,20,30,40
exit
```

### Speichern
```
copy running-config startup-config
```

## Nächste Schritte
- [ ] Custom Ansible Module mit Telnet entwickeln
- [ ] VLAN-Management implementieren
- [ ] Port-Konfiguration implementieren
- [ ] IP-Adresse auf 10.0.10.1 ändern (Take Ownership)
