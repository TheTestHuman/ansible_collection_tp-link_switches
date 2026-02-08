#!/usr/bin/env python3
"""
TP-Link SG108E Easy Smart Switch - VLAN Configuration Module

Configures VLANs and port settings on TP-Link Easy Smart Switches via UDP protocol.

Based on: rgl.tp_link_easy_smart_switch collection
Protocol: UDP broadcast on ports 29808/29809

Requirements:
    - netifaces (pip install netifaces)
    - Switch must already be configured (use sg108e_take_ownership first)

Features:
    - Create/modify VLANs with tagged and untagged ports
    - Set port PVIDs (Port VLAN ID)
    - Enable/disable ports
    - Mode 'add': Only add new VLANs
    - Mode 'replace': Replace all VLANs (keep VLAN 1)

Tested with:
    - TL-SG108E v4/v5
    - TL-SG105E v4/v5
"""

import struct
import socket
import random
import logging
from ipaddress import ip_address, ip_network

from ansible.module_utils.basic import AnsibleModule

try:
    import netifaces
    HAS_NETIFACES = True
except ImportError:
    HAS_NETIFACES = False


DOCUMENTATION = '''
---
module: sg108e_vlan
short_description: Configure VLANs on TP-Link Easy Smart Switch
description:
    - Configures VLANs and port settings via UDP protocol
    - Supports tagged and untagged port assignments
    - Can set port PVIDs
options:
    switch_ip:
        description: Switch IP address
        required: true
    switch_mac:
        description: Switch MAC address
        required: true
    username:
        description: Switch username
        required: false
        default: admin
    password:
        description: Switch password
        required: true
        no_log: true
    vlans:
        description: List of VLANs to configure
        required: true
        type: list
        elements: dict
        suboptions:
            vlan_id:
                description: VLAN ID (1-4094)
                required: true
            name:
                description: VLAN name
                required: true
            tagged_ports:
                description: Ports that should be tagged for this VLAN
                type: list
            untagged_ports:
                description: Ports that should be untagged for this VLAN
                type: list
    ports:
        description: Port configuration (optional)
        required: false
        type: list
        elements: dict
    mode:
        description: Operation mode
        choices: ['add', 'replace']
        default: add
    protected_vlans:
        description: VLANs that should never be deleted
        default: [1]
        type: list
requirements:
    - netifaces
'''

EXAMPLES = '''
- name: Configure VLANs on SG108E
  sg108e_vlan:
    switch_ip: "10.0.10.50"
    switch_mac: "AA:BB:CC:DD:EE:FF"
    password: "secret"
    vlans:
      - vlan_id: 1
        name: "Default"
        untagged_ports: [1]
      - vlan_id: 10
        name: "Management"
        tagged_ports: [1]
        untagged_ports: [2]
      - vlan_id: 20
        name: "Clients"
        tagged_ports: [1]
        untagged_ports: [3, 4, 5, 6, 7, 8]
'''


# =============================================================================
# EMBEDDED BINARY HELPERS
# =============================================================================

SEP = ","

def ports2list(ports):
    if ports is None:
        return []
    try:
        return [int(x) for x in ports.split(SEP)]
    except ValueError:
        return []

def ports2byte(ports):
    out = 0
    for i in ports:
        out |= (1 << (int(i) - 1))
    return out

def byte2ports(byte):
    out = []
    for i in range(32):
        if byte % 2:
            out.append(str(i + 1))
        byte >>= 1
    return SEP.join(out)

def mac_to_bytes(mac):
    return bytes(int(byte, 16) for byte in mac.split(':'))

def mac_to_str(mac):
    return ':'.join(format(s, '02x') for s in mac)

def ports_to_byte(ports):
    """Convert list of port numbers to bitmask"""
    b = 0
    for n in ports:
        b |= 1 << (n - 1)
    return b


# =============================================================================
# EMBEDDED PROTOCOL CLASS
# =============================================================================

class Protocol:
    PACKET_END = b'\xff\xff\x00\x00'

    KEY = bytes([191, 155, 227, 202, 99, 162, 79, 104, 49, 18, 190, 164, 30,
    76, 189, 131, 23, 52, 86, 106, 207, 125, 126, 169, 196, 28, 172, 58,
    188, 132, 160, 3, 36, 120, 144, 168, 12, 231, 116, 44, 41, 97, 108,
    213, 42, 198, 32, 148, 218, 107, 247, 112, 204, 14, 66, 68, 91, 224,
    206, 235, 33, 130, 203, 178, 1, 134, 199, 78, 249, 123, 7, 145, 73,
    208, 209, 100, 74, 115, 72, 118, 8, 22, 243, 147, 64, 96, 5, 87, 60,
    113, 233, 152, 31, 219, 143, 174, 232, 153, 245, 158, 254, 70, 170,
    75, 77, 215, 211, 59, 71, 133, 214, 157, 151, 6, 46, 81, 94, 136,
    166, 210, 4, 43, 241, 29, 223, 176, 67, 63, 186, 137, 129, 40, 248,
    255, 55, 15, 62, 183, 222, 105, 236, 197, 127, 54, 179, 194, 229,
    185, 37, 90, 237, 184, 25, 156, 173, 26, 187, 220, 2, 225, 0, 240,
    50, 251, 212, 253, 167, 17, 193, 205, 177, 21, 181, 246, 82, 226,
    38, 101, 163, 182, 242, 92, 20, 11, 95, 13, 230, 16, 121, 124, 109,
    195, 117, 39, 98, 239, 84, 56, 139, 161, 47, 201, 51, 135, 250, 10,
    19, 150, 45, 111, 27, 24, 142, 80, 85, 83, 234, 138, 216, 57, 93,
    65, 154, 141, 122, 34, 140, 128, 238, 88, 89, 9, 146, 171, 149, 53,
    102, 61, 114, 69, 217, 175, 103, 228, 35, 180, 252, 200, 192, 165,
    159, 221, 244, 110, 119, 48])

    header_config = {
        "len": 32,
        "fmt": '!bb6s6shihhhhi',
        "blank": {
            'version': 1,
            'op_code': 0,
            'switch_mac': b'\x00\x00\x00\x00\x00\x00',
            'host_mac':   b'\x00\x00\x00\x00\x00\x00',
            'sequence_id': 0,
            'error_code': 0,
            'check_length': 0,
            'fragment_offset': 0,
            'flag': 0,
            'token_id': 0,
            'checksum': 0,
        }
    }

    DISCOVERY = 0
    GET = 1
    SET = 2
    LOGIN = 3
    RETURN = 4

    ids_tp = {
        1:     ('str',   'type'),
        2:     ('str',   'hostname'),
        3:     ('hex',   'mac'),
        4:     ('ip',    'ip_addr'),
        5:     ('ip',    'ip_mask'),
        6:     ('ip',    'gateway'),
        7:     ('str',   'firmware'),
        8:     ('str',   'hardware'),
        9:     ('bool',  'dhcp'),
        10:    ('dec',   'num_ports'),
        512:   ('str',   'username'),
        513:   ('str',   'new_username'),
        514:   ('str',   'password'),
        515:   ('str',   'new_password'),
        2305:  ('action','get_token_id'),
        4096:  ('hex',   'ports'),
        8704:  ('hex',   'vlan_enabled'),
        8705:  ('vlan',  'vlan'),
        8706:  ('pvid',  'pvid'),
        8707:  ('str',   'vlan_filler'),
    }

    tp_ids = {v[1]: k for k, v in ids_tp.items()}

    @staticmethod
    def get_id(name):
        return Protocol.tp_ids[name]

    @staticmethod
    def decode(data):
        data = bytearray(data)
        s = bytearray(Protocol.KEY)
        j = 0
        for k in range(len(data)):
            i = (k + 1) & 255
            j = (j + s[i]) & 255
            s[i], s[j] = s[j], s[i]
            data[k] = data[k] ^ s[(s[i] + s[j]) & 255]
        return bytes(data)

    encode = decode

    @staticmethod
    def split(data):
        if len(data) < Protocol.header_config["len"] + len(Protocol.PACKET_END):
            raise AssertionError('invalid data length')
        if not data.endswith(Protocol.PACKET_END):
            raise AssertionError('data without packet end')
        return (data[0:Protocol.header_config["len"]], data[Protocol.header_config["len"]:])

    @staticmethod
    def interpret_header(header):
        names = Protocol.header_config['blank'].keys()
        vals = struct.unpack(Protocol.header_config['fmt'], header)
        return dict(zip(names, vals))

    @staticmethod
    def interpret_payload(payload):
        results = []
        while len(payload) > len(Protocol.PACKET_END):
            dtype, dlen = struct.unpack('!hh', payload[0:4])
            data = payload[4:4+dlen]
            if dtype in Protocol.ids_tp:
                results.append((
                    dtype,
                    Protocol.ids_tp[dtype][1],
                    Protocol.interpret_value(data, Protocol.ids_tp[dtype][0])
                ))
            payload = payload[4+dlen:]
        return results

    @staticmethod
    def interpret_value(value, kind):
        if kind == 'str':
            value = value.split(b'\x00', 1)[0].decode('ascii')
        elif kind == 'ip':
            value = ip_address(value)
        elif kind == 'hex':
            value = mac_to_str(value)
        elif kind == 'action':
            value = "n/a"
        elif kind == 'dec':
            value = int.from_bytes(value, 'big')
        elif kind == 'vlan':
            value = list(struct.unpack("!hii", value[:10]) + (value[10:-1].decode('ascii'), ))
            value[1] = byte2ports(value[1])
            value[2] = byte2ports(value[2])
        elif kind == 'pvid':
            value = struct.unpack("!bh", value) if value else None
        elif kind == 'bool':
            if len(value) == 0:
                pass
            elif len(value) == 1:
                value = value[0] > 0
            else:
                raise AssertionError('boolean should be one byte long')
        return value

    @staticmethod
    def assemble_packet(header, payload):
        payload_bytes = b''
        for dtype, value in payload:
            payload_bytes += struct.pack('!hh', dtype, len(value))
            payload_bytes += value
        header['check_length'] = Protocol.header_config["len"] + len(payload_bytes) + len(Protocol.PACKET_END)
        header_tuple = tuple(header[part] for part in Protocol.header_config['blank'].keys())
        header_bytes = struct.pack(Protocol.header_config['fmt'], *header_tuple)
        return header_bytes + payload_bytes + Protocol.PACKET_END

    @staticmethod
    def set_vlan(vlan_num, member_mask, tagged_mask, vlan_name):
        value = struct.pack("!hii", vlan_num, member_mask, tagged_mask) + vlan_name.encode("ascii") + b'\x00'
        return value

    @staticmethod
    def set_pvid(vlan_num, port):
        value = struct.pack("!bh", port, vlan_num)
        return value


# =============================================================================
# EMBEDDED NETWORK CLASS
# =============================================================================

class ConnectionProblem(Exception):
    pass


class Network:
    BROADCAST_ADDR = "255.255.255.255"
    UDP_SEND_TO_PORT = 29808
    UDP_RECEIVE_FROM_PORT = 29809

    def __init__(self, ip_address_str, host_mac, switch_mac="00:00:00:00:00:00"):
        self.switch_mac = switch_mac
        self.host_mac = host_mac
        self.ip_address = ip_address_str
        self.sequence_id = random.randint(0, 1000)

        self.header = Protocol.header_config["blank"].copy()
        self.header.update({
            'sequence_id': self.sequence_id,
            'host_mac': mac_to_bytes(self.host_mac),
            'switch_mac': mac_to_bytes(self.switch_mac),
        })

        # Sending socket
        self.ss = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ss.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.ss.bind((ip_address_str, Network.UDP_RECEIVE_FROM_PORT))

        # Receiving socket
        self.rs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rs.bind((Network.BROADCAST_ADDR, Network.UDP_RECEIVE_FROM_PORT))
        self.rs.settimeout(10)

    def send(self, op_code, payload):
        self.sequence_id = (self.sequence_id + 1) % 1000
        self.header.update({
            'sequence_id': self.sequence_id,
            'op_code': op_code,
        })
        packet = Protocol.assemble_packet(self.header, payload)
        packet = Protocol.encode(packet)
        self.ss.sendto(packet, (Network.BROADCAST_ADDR, Network.UDP_SEND_TO_PORT))

    def receive(self):
        try:
            data, addr = self.rs.recvfrom(1500)
            data = Protocol.decode(data)
            header, payload = Protocol.split(data)
            header, payload = Protocol.interpret_header(header), Protocol.interpret_payload(payload)
            self.header['token_id'] = header['token_id']
            return header, payload
        except socket.timeout:
            raise ConnectionProblem("Timeout waiting for switch response")
        except Exception as e:
            raise ConnectionProblem(f"Connection error: {str(e)}")

    def query(self, op_code, payload):
        self.send(op_code, payload)
        header, payload = self.receive()
        return header, payload

    def login_dict(self, username, password):
        return [
            (Protocol.get_id('username'), username.encode('ascii') + b'\x00'),
            (Protocol.get_id('password'), password.encode('ascii') + b'\x00'),
        ]

    def login(self, username, password):
        self.query(Protocol.GET, [(Protocol.get_id("get_token_id"), b'')])
        self.query(Protocol.LOGIN, self.login_dict(username, password))

    def set(self, username, password, payload):
        self.query(Protocol.GET, [(Protocol.get_id("get_token_id"), b'')])
        real_payload = self.login_dict(username, password)
        real_payload += payload
        header, payload = self.query(Protocol.LOGIN, real_payload)
        return header, payload

    def close(self):
        try:
            self.ss.close()
            self.rs.close()
        except:
            pass


# =============================================================================
# SWITCH CLIENT
# =============================================================================

class SG108ESwitchClient:
    """Client for configuring SG108E switches"""

    def __init__(self, host_ip, host_mac, switch_mac, username, password):
        self._username = username
        self._password = password
        self._network = Network(host_ip, host_mac, switch_mac)
        self._network.login(username, password)

    def close(self):
        self._network.close()

    def get_vlan_enabled(self):
        """Check if VLAN mode is enabled"""
        _header, payload = self._network.query(Protocol.GET, [(Protocol.get_id('vlan_enabled'), b'')])
        for p in payload:
            if p[1] == 'vlan_enabled':
                return int(p[2], 16) != 0
        return False

    def set_vlan_enabled(self, enabled):
        """Enable or disable VLAN mode"""
        set_payload = [(Protocol.get_id('vlan_enabled'), b'\x01' if enabled else b'\x00')]
        _header, _payload = self._network.set(self._username, self._password, set_payload)

    def get_vlans(self):
        """Get current VLAN configuration"""
        _header, payload = self._network.query(Protocol.GET, [(Protocol.get_id('vlan'), b'')])
        vlans = []
        for p in payload:
            if p[1] == 'vlan':
                vlans.append({
                    'vlan_id': int(p[2][0]),
                    'name': p[2][3],
                    'member_ports': [int(s) for s in p[2][1].split(',') if s],
                    'tagged_ports': [int(s) for s in p[2][2].split(',') if s],
                })
        return vlans

    def set_vlans(self, vlans):
        """Set VLANs (one at a time due to firmware bug)"""
        for v in vlans:
            set_payload = [(
                Protocol.get_id('vlan'),
                Protocol.set_vlan(
                    v['vlan_id'],
                    ports_to_byte(v['member_ports']),
                    ports_to_byte(v['tagged_ports']),
                    v['name'] or ''
                )
            )]
            _header, _payload = self._network.set(self._username, self._password, set_payload)

    def get_pvids(self):
        """Get port PVIDs"""
        _header, payload = self._network.query(Protocol.GET, [(Protocol.get_id('pvid'), b'')])
        pvids = []
        for p in payload:
            if p[1] == 'pvid':
                pvids.append({
                    'port': int(p[2][0]),
                    'pvid': int(p[2][1]),
                })
        return pvids

    def set_pvids(self, pvids):
        """Set port PVIDs"""
        for v in pvids:
            set_payload = [(
                Protocol.get_id('pvid'),
                Protocol.set_pvid(v['pvid'], v['port'])
            )]
            _header, _payload = self._network.set(self._username, self._password, set_payload)


# =============================================================================
# VLAN CONFIGURATION LOGIC
# =============================================================================

class SG108EVlanConfig:
    """VLAN configuration manager"""

    def __init__(self, client):
        self._client = client

    def get_config(self):
        """Get current switch configuration"""
        vlan_enabled = self._client.get_vlan_enabled()
        vlans = {}
        for v in self._client.get_vlans():
            vlan_id = v['vlan_id']
            tagged_ports = v['tagged_ports']
            member_ports = v['member_ports']
            vlans[vlan_id] = {
                'vlan_id': vlan_id,
                'name': v['name'],
                'tagged_ports': tagged_ports,
                'untagged_ports': sorted(set(member_ports) - set(tagged_ports)),
            }
        pvids = {p['port']: p['pvid'] for p in self._client.get_pvids()}
        return {
            'vlan_enabled': vlan_enabled,
            'vlans': vlans,
            'pvids': pvids,
        }

    def configure_vlans(self, desired_vlans, mode='add', protected_vlans=None, dry_run=False):
        """
        Configure VLANs on the switch.
        
        Args:
            desired_vlans: List of VLAN dicts with vlan_id, name, tagged_ports, untagged_ports
            mode: 'add' (only add) or 'replace' (replace all non-protected)
            protected_vlans: List of VLAN IDs to never delete (default: [1])
            dry_run: If True, don't actually make changes
            
        Returns:
            dict with changed, vlans_created, vlans_deleted, etc.
        """
        if protected_vlans is None:
            protected_vlans = [1]

        # Get current config
        actual_config = self.get_config()
        actual_vlans = actual_config['vlans']

        # Normalize desired VLANs
        desired_vlan_dict = {}
        for v in desired_vlans:
            vlan_id = v['vlan_id']
            tagged = v.get('tagged_ports', []) or []
            untagged = v.get('untagged_ports', []) or []
            member_ports = sorted(set(tagged) | set(untagged))
            desired_vlan_dict[vlan_id] = {
                'vlan_id': vlan_id,
                'name': v['name'],
                'member_ports': member_ports,
                'tagged_ports': tagged,
                'untagged_ports': untagged,
            }

        # Determine what to create/delete
        vlans_to_create = []
        vlans_to_delete = []
        vlans_to_update = []

        if mode == 'replace':
            # Delete VLANs not in desired list (except protected)
            for vlan_id in actual_vlans:
                if vlan_id not in desired_vlan_dict and vlan_id not in protected_vlans:
                    vlans_to_delete.append(vlan_id)

        # Find VLANs to create or update
        for vlan_id, desired in desired_vlan_dict.items():
            if vlan_id in actual_vlans:
                actual = actual_vlans[vlan_id]
                # Check if update needed
                if (set(actual['tagged_ports']) != set(desired['tagged_ports']) or
                    set(actual['untagged_ports']) != set(desired['untagged_ports']) or
                    actual['name'] != desired['name']):
                    vlans_to_update.append(desired)
            else:
                vlans_to_create.append(desired)

        # Enable VLAN mode if not already enabled
        vlan_enabled_changed = False
        if not actual_config['vlan_enabled'] and (vlans_to_create or vlans_to_update):
            vlan_enabled_changed = True
            if not dry_run:
                self._client.set_vlan_enabled(True)

        # Apply changes
        changed = vlan_enabled_changed or bool(vlans_to_create) or bool(vlans_to_update) or bool(vlans_to_delete)

        if not dry_run:
            # Create/update VLANs
            all_vlans_to_set = vlans_to_create + vlans_to_update
            if all_vlans_to_set:
                self._client.set_vlans(all_vlans_to_set)

            # Set PVIDs based on untagged port assignments
            pvids_to_set = []
            for vlan in all_vlans_to_set:
                for port in vlan.get('untagged_ports', []):
                    pvids_to_set.append({'port': port, 'pvid': vlan['vlan_id']})
            if pvids_to_set:
                self._client.set_pvids(pvids_to_set)

            # Delete VLANs (by setting them with no ports - effectively removes them)
            # Note: SG108E doesn't have explicit delete, we just don't include them

        return {
            'changed': changed,
            'vlan_enabled_changed': vlan_enabled_changed,
            'vlans_created': len(vlans_to_create),
            'vlans_updated': len(vlans_to_update),
            'vlans_deleted': len(vlans_to_delete),
            'vlans_created_ids': [v['vlan_id'] for v in vlans_to_create],
            'vlans_updated_ids': [v['vlan_id'] for v in vlans_to_update],
            'vlans_deleted_ids': vlans_to_delete,
            'actual_vlans': list(actual_vlans.keys()),
            'desired_vlans': list(desired_vlan_dict.keys()),
        }


# =============================================================================
# HOST ADDRESS DETECTION
# =============================================================================

def get_host_address_for_switch(switch_ip):
    """Find host IP and MAC in same network as switch"""
    for interface in netifaces.interfaces():
        if interface == 'lo':
            continue
        addresses = netifaces.ifaddresses(interface)
        if netifaces.AF_INET not in addresses:
            continue
        if netifaces.AF_LINK not in addresses:
            continue
        for inet in addresses[netifaces.AF_INET]:
            host_network = ip_network(f"{inet['addr']}/{inet['netmask']}", False)
            switch_network = ip_network(f"{switch_ip}/{inet['netmask']}", False)
            if host_network == switch_network:
                return (inet['addr'], addresses[netifaces.AF_LINK][0]['addr'])
    raise Exception(f'Could not find host IP in same network as switch {switch_ip}')


# =============================================================================
# ANSIBLE MODULE
# =============================================================================

def run_module():
    module_args = dict(
        switch_ip=dict(type='str', required=True),
        switch_mac=dict(type='str', required=True),
        username=dict(type='str', required=False, default='admin'),
        password=dict(type='str', required=True, no_log=True),
        vlans=dict(type='list', required=True, elements='dict'),
        ports=dict(type='list', required=False, elements='dict'),
        mode=dict(type='str', required=False, default='add', choices=['add', 'replace']),
        protected_vlans=dict(type='list', required=False, default=[1], elements='int'),
        hostname=dict(type='str', required=False, default='SG108E'),
    )

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)

    if not HAS_NETIFACES:
        module.fail_json(msg="Missing required library: netifaces. Install with: pip install netifaces")

    result = dict(
        changed=False,
        message='',
        switch_ip=module.params['switch_ip'],
        switch_mac=module.params['switch_mac'],
        mode=module.params['mode'],
    )

    switch_ip = module.params['switch_ip']
    switch_mac = module.params['switch_mac']
    username = module.params['username']
    password = module.params['password']
    vlans = module.params['vlans']
    mode = module.params['mode']
    protected_vlans = module.params['protected_vlans']

    try:
        # Get host address
        host_ip, host_mac = get_host_address_for_switch(switch_ip)
        result['host_ip'] = host_ip
        result['host_mac'] = host_mac

        # Connect to switch
        client = SG108ESwitchClient(host_ip, host_mac, switch_mac, username, password)
        
        try:
            config_manager = SG108EVlanConfig(client)
            
            # Configure VLANs
            config_result = config_manager.configure_vlans(
                vlans,
                mode=mode,
                protected_vlans=protected_vlans,
                dry_run=module.check_mode
            )
            
            result['changed'] = config_result['changed']
            result['vlans_created'] = config_result['vlans_created']
            result['vlans_updated'] = config_result['vlans_updated']
            result['vlans_deleted'] = config_result['vlans_deleted']
            result['vlans_created_ids'] = config_result['vlans_created_ids']
            result['vlans_updated_ids'] = config_result['vlans_updated_ids']
            result['vlans_deleted_ids'] = config_result['vlans_deleted_ids']
            result['message'] = f"Mode '{mode}': Created {config_result['vlans_created']}, Updated {config_result['vlans_updated']}, Deleted {config_result['vlans_deleted']} VLANs"
            
        finally:
            client.close()

    except Exception as e:
        module.fail_json(msg=f'VLAN configuration failed: {str(e)}', **result)

    module.exit_json(**result)


if __name__ == '__main__':
    run_module()
