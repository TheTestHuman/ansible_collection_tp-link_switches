# Ansible Collection - Multi-Vendor Switch Automation

⚠️ **DEVELOPMENT PREVIEW** - This collection is currently under active development as part of an academic thesis. APIs and functionality may change. Use at your own risk.

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

### System Packages

Update system:
```bash
sudo apt update
```

```bash
sudo apt upgrade -y
```

Install Git:
```bash
sudo apt install git -y
```

Install Python:
```bash
sudo apt install python3 python3-pip -y
```

Install Ansible:
```bash
sudo apt install ansible -y
```

Install Expect (required for TP-Link Managed Switches):
```bash
sudo apt install expect -y
```

### Python Packages

Install netifaces (required for SG108E only):
```bash
pip3 install netifaces --break-system-packages
```

## Installation

Clone the repository:
```bash
git clone https://github.com/TheTestHuman/ansible_collection_tp-link_switches.git
```

Change to project directory:
```bash
cd ansible_collection_tp-link_switches
```

Verify the structure:
```bash
ls -la
```

Change to generic_collection:
```bash
cd generic_collection
```

## Quick Start

### 1. Configure Inventory

View the inventory template:
```bash
cat inventory/production_blank.yml
```

Copy production inventory:
```bash
cp inventory/production_blank.yml inventory/production.yml
```

Copy vault template:
```bash
cp inventory/vault_blank.yml inventory/vault.yml
```

View vault structure:
```bash
cat inventory/vault.yml
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

### 2. Encrypt Vault (Recommended)

Encrypt the vault file:
```bash
ansible-vault encrypt inventory/vault.yml
```

Edit encrypted vault:
```bash
ansible-vault edit inventory/vault.yml
```

Decrypt vault (required before take-ownership):
```bash
ansible-vault decrypt inventory/vault.yml
```

Re-encrypt after take-ownership:
```bash
ansible-vault encrypt inventory/vault.yml
```

### 3. Take Ownership (Factory-Default Switch)

For a new switch in factory state:

TP-Link SG3210:
```bash
ansible-playbook playbooks/take-ownership-sg3210.yml
```

TP-Link SG3452X:
```bash
ansible-playbook playbooks/take-ownership-sg3452x.yml
```

TP-Link SG108E:
```bash
ansible-playbook playbooks/take-ownership-sg108e.yml
```

Cisco C2924 (requires console pre-configuration):
```bash
ansible-playbook playbooks/take-ownership-cisco.yml
```

**Note:** If vault is encrypted during take-ownership, the playbook will add the switch to `production.yml` and display instructions for manually adding the password to the vault.

### 4. Configure VLANs

With encrypted vault, use `--ask-vault-pass`:

SG3210:
```bash
ansible-playbook playbooks/configure-vlans-sg3210.yml --ask-vault-pass
```

SG3452X:
```bash
ansible-playbook playbooks/configure-vlans-sg3452x.yml --ask-vault-pass
```

SG108E:
```bash
ansible-playbook playbooks/configure-vlans-sg108e.yml --ask-vault-pass
```

Cisco:
```bash
ansible-playbook playbooks/configure-vlans-cisco.yml --ask-vault-pass
```

### 5. Additional Features (Managed Switches Only)

Link Aggregation (LAG):
```bash
ansible-playbook playbooks/configure-lag-sg3210.yml --ask-vault-pass
```

```bash
ansible-playbook playbooks/configure-lag-sg3452x.yml --ask-vault-pass
```

Port Security:
```bash
ansible-playbook playbooks/configure-port-security-sg3210.yml --ask-vault-pass
```

```bash
ansible-playbook playbooks/configure-port-security-sg3452x.yml --ask-vault-pass
```

Backup Configuration:
```bash
ansible-playbook playbooks/backup-sg3210.yml --ask-vault-pass
```

## Project Structure

```
ansible_collection_tp-link_switches/
├── generic_collection/          # Unified playbook layer
│   ├── playbooks/               # All playbooks (switch-type suffix)
│   ├── library/                 # Shared modules (inventory_manager)
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
│   └── library/                 # Python modules (SSH/Expect + SFP)
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
- **Idempotent:** Only applies changes when configuration differs

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

### TP-Link SG3210 (SSH/Expect)

| Module | Description | Idempotent |
|--------|-------------|------------|
| sg3210_initial_setup | Initial setup via Telnet | - |
| sg3210_change_ip | Change management IP | - |
| sg3210_batch_vlan_expect | VLAN configuration (add/replace) | ✅ |
| sg3210_lag_expect | Link Aggregation (LACP/static) | ✅ |
| sg3210_port_security_expect | Port Security with MAC limiting | ✅ |
| sg3210_config_backup | Backup/Restore (4 actions) | - |

### TP-Link SG3452X (SSH/Expect)

| Module | Description | Idempotent |
|--------|-------------|------------|
| sg3452x_initial_setup | Initial setup via Telnet | - |
| sg3452x_change_ip | Change management IP | - |
| sg3452x_batch_vlan_expect | VLAN configuration (add/replace) | ✅ |
| sg3452x_lag_expect | Link Aggregation (LACP/static) | ✅ |
| sg3452x_port_security_expect | Port Security with MAC limiting | ✅ |
| sg3452x_config_backup | Backup/Restore (4 actions) | - |

**Note:** SG3452X modules support SFP+ ports 49-52 (ten-gigabitEthernet interface type).

### Shared Module

| Module | Description | Idempotent |
|--------|-------------|------------|
| inventory_manager | Inventory and vault updates | ✅ |

### TP-Link SG108E (UDP)

| Module | Description | Idempotent |
|--------|-------------|------------|
| sg108e_take_ownership | Set password and IP via UDP | - |
| sg108e_vlan | VLAN configuration with delete support | - |

### Cisco C2924 (Telnet)

| Module | Description | Idempotent |
|--------|-------------|------------|
| cisco_take_ownership | Read hardware info | - |
| cisco_vlan | VLAN creation and port assignment | - |
| cisco_telnet_connection | Shared Telnet class | - |

## Idempotency

All VLAN, LAG, and Port Security modules for SG3210 and SG3452X are **idempotent**:

- First run: `changed=true` (configuration applied)
- Second run: `changed=false` (no changes needed)

This is achieved by:
1. Fetching current configuration via `show running-config`
2. Parsing the output to extract current state
3. Comparing with desired state
4. Only applying changes if differences exist

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

### Password Management

Encrypt vault for production:
```bash
ansible-vault encrypt inventory/vault.yml
```

Run playbooks with vault password:
```bash
ansible-playbook playbooks/configure-vlans-sg3210.yml --ask-vault-pass
```

**Important:** Never store passwords in playbooks or production.yml.

### Vault Workflow for Take-Ownership

Since Ansible Vault cannot be written to programmatically when encrypted:

1. **Option A:** Decrypt vault before take-ownership
   ```bash
   ansible-vault decrypt inventory/vault.yml
   ansible-playbook playbooks/take-ownership-sg3210.yml
   ansible-vault encrypt inventory/vault.yml
   ```

2. **Option B:** Add password manually after take-ownership
   ```bash
   ansible-playbook playbooks/take-ownership-sg3210.yml
   # Follow the displayed instructions
   ansible-vault edit inventory/vault.yml
   # Add: switch-name: "password"
   ```

### Protocol Security

- SSH used for TP-Link Managed after initial setup
- Telnet only for Cisco (no SSH support) and initial TP-Link setup
- UDP communication (SG108E) is unencrypted - use isolated network

### Out-of-Band Access

- Always maintain console access for recovery
- Network automation can lock you out if misconfigured

## Troubleshooting

### SSH Connection Timeout (SG3210/SG3452X)

Verify connectivity:
```bash
ping 10.0.10.1
```

Test SSH connection:
```bash
ssh admin@10.0.10.1
```

### UDP No Response (SG108E)

Check you're in same L2 segment. Verify MAC address matches switch label.

Check netifaces is installed:
```bash
python3 -c "import netifaces; print('OK')"
```

### Telnet Connection Refused (Cisco)

Cisco requires console pre-configuration.

Connect via serial:
```bash
sudo minicom -D /dev/ttyUSB0 -b 9600
```

### Module Not Found

Verify library path in ansible.cfg:
```bash
cat ansible.cfg | grep library
```

Should show:
```
library = ./library:../tp_link_sg3210/library:../tp_link_sg3452x/library:...
```

## Development

This project was developed as part of an academic thesis on network automation.

**Key Findings:**
- Standard Python SSH libraries (paramiko, netmiko) fail with TP-Link Managed switches
- Expect-based PTY emulation required for stable CLI interaction
- Protocol abstraction enables unified management of heterogeneous networks
- Idempotency requires parsing switch-specific running-config output

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

This collection includes code derived from [rgl/ansible-collection-tp-link-easy-smart-switch](https://github.com/rgl/ansible-collection-tp-link-easy-smart-switch) which is also licensed under GPL-3.0.

## Author

Developed as a research project on Ansible-based network automation.
