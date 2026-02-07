# =============================================================================
# Cisco Catalyst 2900 XL - Python Module
# =============================================================================
# Dieser Ordner enthält die Cisco-spezifischen Ansible-Module.
#
# Geplante Module:
#   - cisco_initial_setup.py    : Take-Ownership (Passwort, SSH aktivieren)
#   - cisco_change_ip.py        : IP-Adresse ändern
#   - cisco_vlan.py             : VLAN-Konfiguration
#   - cisco_port.py             : Port-Konfiguration
#   - cisco_config_backup.py    : Backup/Restore
#
# Diese Module nutzen SSH + IOS CLI (kein Expect wie bei TP-Link,
# da Cisco ein standardisiertes CLI hat).
# =============================================================================
