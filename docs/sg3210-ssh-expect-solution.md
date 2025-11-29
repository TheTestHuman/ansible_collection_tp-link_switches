# SG3210 SSH & Expect Solution

## Problem-Zusammenfassung

### Das ursprüngliche Problem

Bei der Automatisierung des TP-Link SG3210 Managed Switch via Telnet/SSH traten massive Probleme auf:

**Symptom:**
- Python-Bibliotheken (`telnetlib`, `paramiko`, `netmiko`, `pexpect`) empfingen nur **Echo** der gesendeten Befehle
- **Keine Prompts** (`SG3210>`, `SG3210#`) wurden zurückgesendet
- **Keine Command-Outputs** (z.B. von `show vlan`)
- Befehle wurden **nicht ausgeführt** (VLANs nicht erstellt)

**Beispiel-Output bei Python/Paramiko:**

Send: enable Receive: enable # ← Nur Echo, kein Prompt!
Send: show vlan Receive: show vlan # ← Nur Echo, keine VLAN-Liste!
### Versuchte Lösungen (alle fehlgeschlagen)

#### 1. Telnet mit telnetlib
```python
import telnetlib
tn = telnetlib.Telnet("192.168.0.1")
# Problem: Nur Echo, keine Prompts
```

**Fehler:** `KeyError: 'status_code'` - Switch antwortet nicht auf UDP-Protokoll

#### 2. Telnet mit pexpect + TERM=vt100
```python
os.environ['TERM'] = 'vt100'
child = pexpect.spawn('telnet 192.168.0.1')
# Problem: Immer noch nur Echo
```

**Fehler:** Auch mit `TERM=vt100` keine echten Outputs

#### 3. SSH mit paramiko
```python
import paramiko
shell = client.invoke_shell(term='vt100')
# Problem: Gleiches Echo-Problem wie bei Telnet
```

**Fehler:** `buffer: b'enable'` - kein Prompt nach Befehlen

#### 4. SSH mit netmiko
```python
from netmiko import ConnectHandler
device = {'device_type': 'cisco_ios', ...}
# Problem: Findet Prompts nicht
```

**Fehler:** `Pattern not detected: '(\\#|>)' in output`

#### 5. SSH mit pexpect
```python
child = pexpect.spawn('ssh admin@192.168.0.1')
# Problem: Gleiches wie bei Telnet
```

**Fehler:** Timeout beim Warten auf Prompts

### Root Cause Analysis

**Das fundamentale Problem:**

Der TP-Link SG3210 Switch hat **spezielle TTY/PTY-Anforderungen**, die von Standard-Python-Bibliotheken nicht erfüllt werden:

1. **Terminal Emulation:** Der Switch erwartet ein **echtes Terminal** (TTY), nicht nur eine Socket-Verbindung
2. **PTY Allocation:** Python-Bibliotheken allokieren PTY anders als eine manuelle SSH/Telnet-Session
3. **Terminal Type:** Selbst mit `TERM=vt100` werden die TTY-Flags nicht korrekt gesetzt
4. **Buffer Handling:** Der Switch sendet Outputs nur wenn bestimmte TTY-Modi aktiv sind

**Beweis - Manuelle Session funktioniert:**
```bash
$ TERM=vt100 telnet 192.168.0.1
User: admin
Password:
SG3210>enable
SG3210#show vlan    # ← Hier kommt die VLAN-Liste!
```

### Die Lösung: expect (Shell-Tool)

**Warum `expect` funktioniert:**

`expect` ist ein **eigenständiges Shell-Tool** (nicht Python-Bibliothek), das speziell für **interaktive CLI-Automatisierung** entwickelt wurde:

1. ✅ **Echtes PTY/TTY:** Erstellt ein vollwertiges Pseudo-Terminal
2. ✅ **Korrekte Terminal-Flags:** Setzt alle notwendigen TTY-Modi automatisch
3. ✅ **Pattern-Matching:** Robustes Warten auf Prompts via Regex
4. ✅ **Bewährt seit 1990:** Speziell für genau solche Probleme entwickelt

**Beispiel expect-Script:**
```tcl
#!/usr/bin/expect -f
spawn ssh admin@192.168.0.1
expect "password:"
send "neinnein\r"
expect "SG3210>"
send "enable\r"
expect "SG3210#"
send "show vlan\r"
expect "SG3210#"
# → Funktioniert perfekt!
```

### Implementierung in Ansible

Wir haben Ansible-Module entwickelt, die **expect-Scripte generieren und ausführen**:

**Module:**
- `tp_link_ssh_vlan_expect.py` - VLAN-Management
- `tp_link_ssh_port_expect.py` - Port-Konfiguration

**Architektur:**

Ansible Playbook ↓ Python Modul (generiert expect-Script) ↓ Expect (führt Script aus mit echtem PTY) ↓ SSH-Verbindung zum Switch ↓ ✓ VLANs werden erstellt! 

### Lessons Learned

1. **Nicht alle Network-Devices sind gleich:** TP-Link SG3210 hat spezielle Anforderungen
2. **TTY/PTY matters:** Terminal-Emulation ist komplex, Python-Bibliotheken können nicht alles
3. **expect ist King:** Für interaktive CLI-Automatisierung unschlagbar
4. **Alte Tools sind nicht veraltet:** `expect` (1990) schlägt moderne Python-Libs bei diesem Problem

### Warum nicht direkt expect statt Ansible?

**Ansible-Wrapper hat Vorteile:**
- ✅ Idempotenz-Checks möglich
- ✅ Inventory-Management
- ✅ Gruppierung von Switches
- ✅ Wiederverwendbare Playbooks
- ✅ Logging und Reporting

### Vergleich: Manuell vs Python vs expect

| Methode | Prompts | Outputs | VLANs erstellt |
|---------|---------|---------|----------------|
| Manuell SSH/Telnet | ✅ | ✅ | ✅ |
| Python (telnetlib) | ❌ | ❌ | ❌ |
| Python (paramiko) | ❌ | ❌ | ❌ |
| Python (netmiko) | ❌ | ❌ | ❌ |
| Python (pexpect) | ❌ | ❌ | ❌ |
| **expect (Shell)** | ✅ | ✅ | ✅ |

### Alternative Lösungen (nicht getestet)

Andere mögliche Ansätze für die Zukunft:

1. **SNMP:** TP-Link Switches unterstützen SNMP - könnte für Read-Only-Operations verwendet werden
2. **Web-Scraping:** Web-Interface automatisieren (fragil, nicht empfohlen)
3. **REST API:** Neuere TP-Link Switches haben möglicherweise APIs (SG3210 nicht)
4. **Firmware-Update:** Eventuell behebt neuere Firmware die TTY-Probleme (riskant)

### Fazit

Für den TP-Link SG3210 ist **expect die einzige zuverlässige Lösung** für CLI-Automatisierung via SSH/Telnet.

Die Kombination aus **Ansible + expect** bietet:
- ✅ Funktionsfähige Automatisierung
- ✅ Wiederverwendbare Playbooks
- ✅ Inventory-Management
- ✅ Idempotenz
- ✅ Robustheit

**Empfehlung:** Bei anderen Managed Switches erst mit netmiko versuchen, bei TTY-Problemen direkt auf expect umsteigen.
