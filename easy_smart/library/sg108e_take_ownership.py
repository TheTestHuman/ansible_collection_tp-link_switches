#!/usr/bin/env python3
"""
TP-Link SG108E Easy Smart Switch - Take Ownership Module

Takes ownership of a factory-reset TP-Link Easy Smart Switch via UDP protocol.
Sets IP address, username, and password.

Based on: rgl.tp_link_easy_smart_switch collection
Protocol: UDP broadcast on ports 29808/29809

Requirements:
    - netifaces (pip install netifaces)
    - Switch must be factory-reset
    - Workstation must be in 192.168.0.x network

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

# Try to import netifaces
try:
    import netifaces
    HAS_NETIFACES = True
except ImportError:
    HAS_NETIFACES = False


DOCUMENTATION = '''
---
module: sg108e_take_ownership
short_description: Take ownership of TP-Link Easy Smart Switch
description:
    - Takes ownership of a factory-reset switch
    - Sets IP address, username, and password via UDP protocol
    - Switch must be factory-reset before using this module
options:
    switch_ip:
        description: Target IP address for the switch
        required: true
    switch_mac:
        description: MAC address of the switch (found on label)
        required: true
    username:
        description: New username (default admin will be renamed)
        required: false
        default: admin
    password:
        description: New password for the switch
        required: true
        no_log: true
    switch_suffix:
        description: Suffix for inventory name
        required: false
requirements:
    - netifaces
'''

EXAMPLES = '''
- name: Take ownership of SG108E
  sg108e_take_ownership:
    switch_ip: "10.0.10.50"
    switch_mac: "AA:BB:CC:DD:EE:FF"
    username: "admin"
    password: "neinnein"
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
    l = ports2list(ports)
    if l == []:
        out = 0
    else:
        for i in l:
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
        8705:  ('vlan',  'vlan'),
        8706:  ('pvid',  'pvid'),
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
# TAKE OWNERSHIP CLIENT
# =============================================================================

class SG108ETakeOwnershipClient:
    """Client for taking ownership of SG108E switches"""

    def __init__(self, switch_ip_address, switch_mac_address, username, password):
        self._username = username
        self._password = password
        self._switch_ip_address = switch_ip_address
        self._switch_mac_address = switch_mac_address
        
        # Get host network info
        (self._host_ip_address, self._host_ip_mask, self._host_mac_address) = self._get_host_address()
        (self._default_host_ip, self._default_host_mac) = self._get_default_host_address()
        
        self._network = None

    def _get_host_address(self):
        """Find host IP in same network as target switch IP"""
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
                switch_network = ip_network(f"{self._switch_ip_address}/{inet['netmask']}", False)
                if host_network == switch_network:
                    return (inet['addr'], inet['netmask'], addresses[netifaces.AF_LINK][0]['addr'])
        raise Exception(f'Could not find host IP in same network as switch {self._switch_ip_address}')

    def _get_default_host_address(self):
        """Find host IP in default 192.168.0.0/24 network"""
        default_network = ip_network('192.168.0.0/24')
        for interface in netifaces.interfaces():
            if interface == 'lo':
                continue
            addresses = netifaces.ifaddresses(interface)
            if netifaces.AF_INET not in addresses:
                continue
            if netifaces.AF_LINK not in addresses:
                continue
            for inet in addresses[netifaces.AF_INET]:
                network = ip_network(f"{inet['addr']}/{inet['netmask']}", False)
                if default_network == network:
                    return (inet['addr'], addresses[netifaces.AF_LINK][0]['addr'])
        raise Exception('Could not find host IP in default switch network 192.168.0.0/24')

    def get_config(self):
        """Get current switch configuration"""
        self._network = Network(self._default_host_ip, self._default_host_mac, self._switch_mac_address)
        try:
            _header, payload = self._network.query(Protocol.GET, [(Protocol.get_id('dhcp'), b'')])
            result = {}
            for p in payload:
                if p[1] == 'dhcp':
                    result['dhcp'] = p[2]
                if p[1] == 'ip_addr':
                    result['ip_addr'] = str(p[2])
                if p[1] == 'ip_mask':
                    result['ip_mask'] = str(p[2])
                if p[1] == 'gateway':
                    result['gateway'] = str(p[2])
            return result
        finally:
            self._network.close()

    def set_config(self, config):
        """Set switch configuration (credentials + IP)"""
        self._network = Network(self._default_host_ip, self._default_host_mac, self._switch_mac_address)
        try:
            default_username = 'admin'
            default_password = 'admin'
            
            # Set credentials
            set_payload = [
                (Protocol.get_id('password'), default_password.encode('ascii') + b'\x00'),
                (Protocol.get_id('new_username'), self._username.encode('ascii') + b'\x00'),
                (Protocol.get_id('new_password'), self._password.encode('ascii') + b'\x00'),
            ]
            _header, _payload = self._network.set(default_username, default_password, set_payload)
            
            if _header['op_code'] != 4 or _header['error_code'] != 0:
                raise Exception(f"Failed to set credentials (error_code={_header['error_code']}). Is switch factory-reset?")
            
            # Set IP configuration
            set_payload = [
                (Protocol.get_id('dhcp'), struct.pack('!?', config['dhcp'])),
                (Protocol.get_id('ip_addr'), ip_address(config['ip_addr']).packed),
                (Protocol.get_id('ip_mask'), ip_address(config['ip_mask']).packed),
                (Protocol.get_id('gateway'), ip_address(config['gateway']).packed),
            ]
            _header, _payload = self._network.set(self._username, self._password, set_payload)
            
            if _header.get('status_code', _header.get('error_code', 0)) != 0:
                raise Exception(f"Failed to set IP config (error_code={_header.get('error_code', 'unknown')})")
            
            return True
        finally:
            self._network.close()

    def take_ownership(self, dry_run=False):
        """Take ownership of the switch"""
        desired_config = {
            'dhcp': False,
            'ip_addr': self._switch_ip_address,
            'ip_mask': self._host_ip_mask,
            'gateway': self._host_ip_address,
        }
        
        actual_config = self.get_config()
        
        changed = (
            actual_config.get('dhcp') != desired_config['dhcp'] or
            actual_config.get('ip_addr') != desired_config['ip_addr'] or
            actual_config.get('ip_mask') != desired_config['ip_mask'] or
            actual_config.get('gateway') != desired_config['gateway']
        )
        
        if changed and not dry_run:
            self.set_config(desired_config)
        
        return changed, actual_config, desired_config


# =============================================================================
# ANSIBLE MODULE
# =============================================================================

def run_module():
    module_args = dict(
        switch_ip=dict(type='str', required=True),
        switch_mac=dict(type='str', required=True),
        username=dict(type='str', required=False, default='admin'),
        password=dict(type='str', required=True, no_log=True),
        switch_suffix=dict(type='str', required=False, default=''),
    )

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)

    if not HAS_NETIFACES:
        module.fail_json(msg="Missing required library: netifaces. Install with: pip install netifaces")

    result = dict(
        changed=False,
        message='',
        switch_ip=module.params['switch_ip'],
        switch_mac=module.params['switch_mac'],
        inventory_name='',
        reachable=False,
    )

    switch_ip = module.params['switch_ip']
    switch_mac = module.params['switch_mac']
    username = module.params['username']
    password = module.params['password']
    switch_suffix = module.params['switch_suffix']

    # Build inventory name
    if switch_suffix:
        result['inventory_name'] = f"sg108e-{switch_suffix}"
    else:
        result['inventory_name'] = f"sg108e-{switch_mac.replace(':', '')[-6:].lower()}"

    try:
        client = SG108ETakeOwnershipClient(switch_ip, switch_mac, username, password)
        
        changed, actual_config, desired_config = client.take_ownership(dry_run=module.check_mode)
        
        result['changed'] = changed
        result['reachable'] = True
        result['actual_config'] = actual_config
        result['desired_config'] = desired_config
        result['message'] = 'SUCCESS_TAKE_OWNERSHIP_COMPLETE'
        
        result['hardware_info'] = {
            'mac_address': switch_mac,
            'model': 'TL-SG108E',
        }

    except Exception as e:
        module.fail_json(msg=f'ERROR_TAKE_OWNERSHIP_FAILED: {str(e)}', **result)

    module.exit_json(**result)


if __name__ == '__main__':
    run_module()
