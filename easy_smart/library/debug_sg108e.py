#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from sg108e_vlan import SG108ESwitchClient, get_host_address_for_switch

switch_ip = "10.0.10.2"
switch_mac = "8C:86:DD:AD:91:82"

host_ip, host_mac = get_host_address_for_switch(switch_ip)
client = SG108ESwitchClient(host_ip, host_mac, switch_mac, "admin", "jajajaja")

print("Erstelle VLAN 20...")
client.set_vlans([{
    'vlan_id': 20,
    'name': 'TestVLAN',
    'member_ports': [1, 5, 6],
    'tagged_ports': [1],
}])

print("\nVLANs nach Erstellung:")
for v in client.get_vlans():
    print(f"  VLAN {v['vlan_id']}: {v['name']}")

print("\n=== Simuliere Modul-Ablauf ===")

print("Step 1: Setze PVIDs...")
client.set_pvids([
    {'port': 5, 'pvid': 21},
    {'port': 6, 'pvid': 21},
])

print("Step 2: Keine VLANs zu erstellen/updaten")

print("Step 3: Lösche VLAN 20...")
client.set_vlans([{
    'vlan_id': 20,
    'name': '',
    'member_ports': [],
    'tagged_ports': [],
}])

print("\n=== VLANs nach Modul-Simulation ===")
for v in client.get_vlans():
    print(f"  VLAN {v['vlan_id']}: {v['name']} - Members: {v['member_ports']}")

client.close()
