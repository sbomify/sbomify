"""Checks on addresses sbomify connects to when a user chose the host."""

import ipaddress

# Public IPv6 unicast is all allocated from this block. Outside it, is_global
# still passes NAT64 and site-local addresses, which lead into private networks.
IPV6_GLOBAL_UNICAST = ipaddress.IPv6Network("2000::/3")


def is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether a connection to this address stays on the public internet."""
    # is_global also passes multicast.
    return address.is_global and not address.is_multicast and (address.version == 4 or address in IPV6_GLOBAL_UNICAST)
