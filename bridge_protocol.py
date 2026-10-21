"""Small versioned contract between the external bridge and Rhino listener.

The added tag filters packets from old bridges without breaking the v0.3.2
listener (which ignores unknown extra fields). Not an authentication measure.
"""
BRIDGE_TAG = 'rhino_gamepad_v05'


def compatible(packet):
    return (isinstance(packet, dict) and packet.get('v') == 1
            and packet.get('bridge_tag') == BRIDGE_TAG)
