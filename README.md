# Ansible Collection - Multi-Vendor Switch Automation

[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)

Ansible Collection for managing TP-Link and Cisco switches with unified playbook structure.

## Credits & Inspiration

This collection is based on and inspired by:
- **Rui Lopes** - [ansible-collection-tp-link-easy-smart-switch](https://github.com/rgl/ansible-collection-tp-link-easy-smart-switch)

The SG108E UDP protocol implementation is derived from rgl's work. This collection extends the concept to multiple switch types and vendors using a unified architecture.

---

**NB** This collection was developed as part of an academic research project on network automation.

This collection configures multiple switch types through a unified interface while abstracting protocol differences:

| Switch | Protocol | Port | Status |
|--------|----------|------|--------|
| TP-Link SG3210 | SSH + Expect | 22 | ✅ Production-ready |
| TP-Link SG3452X | SSH + Expect | 22 | ✅ Production-ready |
| TP-Link SG108E | UDP Broadcast | 29808/29809 | ✅ Production-ready |
| Cisco C2924 | Telnet | 23 | ✅ Basic functionality |

## Requirements

**Operating System:** Ubuntu 24.04 LTS (or newer)

**System packages:**
```bash
sudo apt-get update
sudo apt-get install -y git ansible expect python3-pip
```

**Python packages (for SG108E only):**
```bash
pip3 install netifaces --break-system-packages
```

## Installation

Clone the repository:
```bash
git clone https://github.com/TheTestHuman/ansible_collection_tp-link_switches.git
cd ansible_collection_tp-link_switches/generic_collection
```

Verify the structure:
```bash
ls -la
# Should show: playbooks/, inventory/, templates/, ansible.cfg
```

## Quick Start

### 1. Configure Inventory

Copy and edit the inventory templates:
```bash
cp inventory/production_blank.yml inventory/production.yml
cp inventory/vault_blank.yml inventory/vault.yml
```

Edit `inventory/production.yml` with your switch details:
```yaml
all:
  hosts:
    sg3210-office:
      ansible_host: 10.0.10.1
      switch_type: tp_link_sg3210
      switch_mac: "AA:BB:CC:DD:EE:FF"
```

Edit `inventory/vault.yml` with passwords:
```yaml
vault_default_password: "your_password"
vault_passwords:
  sg3210-office: "switch_specific_password"
```

### 2. Take Ownership (Factory-Default Switch)

For a new switch in factory state:
```bash
# TP-Link Managed (SG3210/SG3452X)
ansible-playbook playbooks/take-ownership-sg3210.yml

# TP-Link Easy Smart (SG108E)
ansible-playbook playbooks/take-ownership-sg108e.yml

# Cisco C2924 (requires console pre-configuration)
ansible-playbook playbooks/take-ownership-cisco.yml
```

### 3. Configure VLANs
```bash
# Select switch type
ansible-playbook playbooks/configure-vlans-sg3210.yml
ansible-playbook playbooks/configure-vlans-sg3452x.yml
ansible-playbook playbooks/configure-vlans-sg108e.yml
ansible-playbook playbooks/configure-vlans-cisco.yml
```

### 4. Additional Features (Managed Switches Only)
```bash
# Link Aggregation
ansible-playbook playbooks/configure-lag-sg3210.yml

# Port Security
ansible-playbook playbooks/configure-port-security-sg3210.yml

# Backup/Restore
ansible-playbook playbooks/backup-sg3210.yml
```

## Project Structure

```
ansible_collection_tp-link_switches/
├── generic_collection/          # Unified playbook layer
│   ├── playbooks/               # All playbooks (switch-type suffix)
│   ├── inventory/               # Central inventory
│   │   ├── production.yml       # Switch definitions
│   │   ├── vault.yml            # Passwords (encrypt with ansible-vault)
│   │   └── group_vars/          # Type-specific defaults
│   ├── templates/               # Default configurations
│   │   ├── default_sg3210.yml
│   │   ├── default_sg3452x.yml
│   │   ├── default_sg108e.yml
│   │   └── default_c2924.yml
│   └── ansible.cfg              # Library path configuration
├── tp_link_sg3210/
│   └── library/                 # Python modules (SSH/Expect)
├── tp_link_sg3452x/
│   └── library/                 # Python modules (SSH/Expect)
├── tp_link_sg108e/
│   └── library/                 # Python modules (UDP)
├── cisco/
│   └── library/                 # Python modules (Telnet)
└── docs/                        # Documentation
```

## Architecture

### 3-Layer Model

**Layer 3 - Playbooks (Hardware-agnostic):**
- Unified YAML structure for all switch types
- Interactive prompts for switch selection
- Automatic inventory updates

**Layer 2 - Modules (Switch-specific):**
- Python modules in separate library directories
- Handles CLI syntax differences
- Input validation per device type

**Layer 1 - Protocols (Hardware-specific):**
- UDP socket communication (SG108E)
- Expect scripts via subprocess (SG3210/SG3452X)
- telnetlib connections (Cisco C2924)

### Unified Template Structure

All switch types use identical YAML structure:
```yaml
vlans:
  - vlan_id: 10
    name: "Management"
    tagged_ports: [1]
    untagged_ports: [2]
  - vlan_id: 20
    name: "Clients"
    tagged_ports: [1]
    untagged_ports: [3, 4, 5, 6, 7, 8]
```

## Available Modules

### TP-Link SG3210/SG3452X (SSH/Expect)

| Module | Description |
|--------|-------------|
| tp_link_initial_setup | Initial setup via Telnet |
| tp_link_change_ip | Change management IP |
| tp_link_batch_vlan_expect | VLAN configuration (add/replace) |
| tp_link_lag_expect | Link Aggregation (LACP/static) |
| tp_link_port_security_expect | Port Security with MAC limiting |
| tp_link_config_backup | Backup/Restore (4 actions) |
| inventory_manager | Inventory updates |

### TP-Link SG108E (UDP)

| Module | Description |
|--------|-------------|
| sg108e_take_ownership | Set password and IP via UDP |
| sg108e_vlan | VLAN configuration with delete support |
| inventory_manager | Inventory updates |

### Cisco C2924 (Telnet)

| Module | Description |
|--------|-------------|
| cisco_take_ownership | Read hardware info |
| cisco_vlan | VLAN creation and port assignment |
| cisco_telnet_connection | Shared Telnet class |

## Network Requirements

### TP-Link Managed Switches (Factory Default)

Your workstation needs dual IP addresses:
```yaml
# Example netplan configuration
network:
  version: 2
  ethernets:
    eth0:
      addresses:
        - 192.168.0.100/24  # Factory network (192.168.0.1)
        - 10.0.10.100/24    # Production network
```

### TP-Link Easy Smart (SG108E)

- Workstation must be in same Layer-2 segment (UDP broadcast)
- Requires MAC address from switch label
- Uses ports 29808/29809

### Cisco C2924

- Requires console pre-configuration (IP, password, telnet enable)
- No SSH support on IOS 12.0
- Use only in secured management VLAN

## Security Considerations

**Password Management:**
- Use Ansible Vault for production: `ansible-vault encrypt inventory/vault.yml`
- Never store passwords in playbooks or production.yml

**Protocol Security:**
- SSH used for TP-Link Managed after initial setup
- Telnet only for Cisco (no SSH support) and initial TP-Link setup
- UDP communication (SG108E) is unencrypted - use isolated network

**Out-of-Band Access:**
- Always maintain console access for recovery
- Network automation can lock you out if misconfigured

## Troubleshooting

### SSH Connection Timeout (SG3210/SG3452X)
```bash
# Verify connectivity
ping 10.0.10.1
ssh admin@10.0.10.1
```

### UDP No Response (SG108E)
```bash
# Check you're in same L2 segment
# Verify MAC address matches switch label
# Check netifaces is installed
python3 -c "import netifaces; print('OK')"
```

### Telnet Connection Refused (Cisco)
```bash
# Cisco requires console pre-configuration
# Connect via serial: sudo minicom -D /dev/ttyUSB0 -b 9600
```

## Development

This project was developed as part of an academic thesis on network automation.

**Key Findings:**
- Standard Python SSH libraries (paramiko, netmiko) fail with TP-Link Managed switches
- Expect-based PTY emulation required for stable CLI interaction
- Protocol abstraction enables unified management of heterogeneous networks

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

This collection includes code derived from [rgl/ansible-collection-tp-link-easy-smart-switch](https://github.com/rgl/ansible-collection-tp-link-easy-smart-switch) which is also licensed under GPL-3.0.

## Author

Developed as a research project on Ansible-based network automation.
