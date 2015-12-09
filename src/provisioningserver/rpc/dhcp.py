# Copyright 2014-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""RPC helpers relating to DHCP."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = [
    "configure",
    "create_host_maps",
    "DHCPv4Server",
    "DHCPv6Server",
    "remove_host_maps",
]

import os
import time

from provisioningserver.dhcp import (
    DHCPv4Server,
    DHCPv6Server,
)
from provisioningserver.dhcp.config import get_config
from provisioningserver.dhcp.omshell import Omshell
from provisioningserver.drivers.service import (
    SERVICE_STATE,
    ServiceRegistry,
)
from provisioningserver.logger import get_maas_logger
from provisioningserver.rpc.exceptions import (
    CannotConfigureDHCP,
    CannotCreateHostMap,
    CannotRemoveHostMap,
)
from provisioningserver.service_monitor import (
    service_monitor,
    ServiceActionError,
)
from provisioningserver.utils.fs import (
    sudo_delete_file,
    sudo_write_file,
)
from provisioningserver.utils.shell import ExternalProcessError
from provisioningserver.utils.twisted import synchronous


maaslog = get_maas_logger("dhcp")


@synchronous
def configure(server, subnet_configs):
    """Configure the DHCPv6/DHCPv4 server, and restart it as appropriate.

    :param server: A `DHCPServer` instance.
    :param subnet_configs: List of dicts with subnet parameters for each
        subnet for which the DHCP server should serve DHCP. If no subnets
        are defined, the DHCP server will be stopped.
    """
    stopping = len(subnet_configs) == 0

    if stopping:
        if os.path.exists(server.config_filename):
            sudo_delete_file(server.config_filename)

        service = ServiceRegistry.get_item(server.dhcp_service)
        service.off()
        try:
            service_monitor.ensure_service(server.dhcp_service)
        except ServiceActionError as e:
            # Error is already logged by the service monitor, nothing to
            # log for this exception.
            raise CannotConfigureDHCP(
                "%s server failed to stop: %s" % (
                    server.descriptive_name, e))
        except Exception as e:
            maaslog.error(
                "%s server failed to stop: %s",
                server.descriptive_name, e)
            raise CannotConfigureDHCP(
                "%s server failed to stop: %s" % (
                    server.descriptive_name, e))
    else:
        dhcpd_config = get_config(
            server.template_basename, omapi_key=server.omapi_key,
            dhcp_subnets=subnet_configs)
        interfaces = {subnet['interface'] for subnet in subnet_configs}
        interfaces_config = ' '.join(sorted(interfaces))
        try:
            sudo_write_file(server.config_filename, dhcpd_config)
            sudo_write_file(server.interfaces_filename, interfaces_config)
        except ExternalProcessError as e:
            # ExternalProcessError.__unicode__ contains a generic failure
            # message as well as the command and its error output. On the
            # other hand, ExternalProcessError.output_as_unicode contains just
            # the error output which is probably the best information on what
            # went wrong. Log the full error information, but keep the
            # exception message short and to the point.
            maaslog.error(
                "Could not rewrite %s server configuration (for network "
                "interfaces %s): %s", server.descriptive_name,
                interfaces_config, unicode(e))
            raise CannotConfigureDHCP(
                "Could not rewrite %s server configuration: %s" % (
                    server.descriptive_name, e.output_as_unicode))

        service = ServiceRegistry.get_item(server.dhcp_service)
        service.on()
        try:
            service_monitor.restart_service(server.dhcp_service)
        except ServiceActionError as e:
            # Error is already logged by the service monitor, nothing to
            # log for this exception.
            raise CannotConfigureDHCP(
                "%s server failed to restart: %s" % (
                    server.descriptive_name, e))
        except Exception as e:
            maaslog.error(
                "%s server failed to restart (for network interfaces "
                "%s): %s", server.descriptive_name, interfaces_config, e)
            raise CannotConfigureDHCP(
                "%s server failed to restart: %s" % (
                    server.descriptive_name, e))


def _try_omshell_connection():
    """Try to connect to the DHCP server using Omshell.

    Tries a maximum of 3 times for a total of 1.5 seconds.
    """
    omshell = Omshell(
        server_address='127.0.0.1', shared_key="")
    for _ in range(3):
        connectable = omshell.try_connection()
        if connectable:
            return True
        else:
            # Not able to connect. Wait half a second and
            # try again.
            time.sleep(0.5)
    return False


def _is_dhcpv4_managed_and_active(exception):
    """Ensure that the DHCPv4 server is accessible (if necessary), and return
    its status.

    Returns True if the DHCPv4 server is accessible and should be accessible.
    Returns False if the DHCPv4 server is not accessible, and should not be
    accessible.
    Raise `exception` if the DHCP server should be accessible, but cannot
    be started.

    :return:bool
    """
    service = ServiceRegistry.get_item("dhcp4")
    if service.is_on():
        if service_monitor.get_service_state("dhcp4") != SERVICE_STATE.ON:
            try:
                service_monitor.ensure_service("dhcp4")
                if not _try_omshell_connection():
                    raise exception(
                        "DHCPv4 server started but was unable to connect "
                        "to omshell.")
                else:
                    return True
            except ServiceActionError as e:
                # Error is already logged by the service monitor, nothing to
                # log for this exception.
                raise exception("DHCPv4 server failed to start: %s" % e)
            except Exception as e:
                error_msg = "DHCPv4 server failed to start: %s" % e
                maaslog.error(error_msg)
                raise exception(error_msg)
        else:
            # Service should be on and is already on, nothing needs to be done.
            return True
    else:
        # This is not an error; it just needs to be distinguished here so it
        # can be handled differently.
        return False


@synchronous
def create_host_maps(mappings, shared_key):
    """Create DHCP host maps for the given mappings.

    :param mappings: A list of dicts containing ``ip_address`` and
        ``mac_address`` keys.
    :param shared_key: The key used to access the DHCP server via OMAPI.
    """
    if not _is_dhcpv4_managed_and_active(CannotCreateHostMap):
        # This will raise if DHCP is offline, but should be online.
        # If the server is offline *and* should be offline, we'll get False
        # back, which means this is a no-op.
        return

    # See bug 1039362 regarding server_address.
    omshell = Omshell(server_address='127.0.0.1', shared_key=shared_key)
    for mapping in mappings:
        ip_address = mapping["ip_address"]
        mac_address = mapping["mac_address"]
        try:
            omshell.create(ip_address, mac_address)
        except ExternalProcessError as e:
            maaslog.error(
                "Could not create host map for %s with address %s: %s",
                mac_address, ip_address, unicode(e))
            if 'not connected.' in e.output_as_unicode:
                raise CannotCreateHostMap(
                    "The DHCP server could not be reached.")
            else:
                raise CannotCreateHostMap("%s -> %s: %s" % (
                    mac_address, ip_address, e.output_as_unicode))


@synchronous
def remove_host_maps(identifiers, shared_key):
    """Remove DHCP host maps for the given IP addresses.

    Additionally, this will ensure that any lease present for the MAC
    address(es) supplied is also forcefully expired.  Generally, host
    maps don't create leases unless the host map is inside the dynamic
    range, however this is still safe to call and can be called to
    guarantee that any IP address is left expired regardless of whether
    it's in the dynamic range or not.

    :param mac_addresses: A list of MAC addresses.
    :param shared_key: The key used to access the DHCP server via OMAPI.
    """
    if not _is_dhcpv4_managed_and_active(CannotRemoveHostMap):
        # This will raise if DHCP is offline, but should be online.
        # If the server is offline *and* should be offline, we'll get False
        # back, which means this is a no-op.
        return

    # See bug 1039362 regarding server_address.
    omshell = Omshell(server_address='127.0.0.1', shared_key=shared_key)
    for identifier in identifiers:
        try:
            # Note: identifiers can be either MAC addresses or IP addresses;
            # the region will send us a set of both, due to backward
            # compatibility issues (MAAS 1.8 used the IP address as the
            # identifier; now we use the MAC.)
            omshell.remove(identifier)
            omshell.nullify_lease(identifier)
        except ExternalProcessError as e:
            maaslog.error(
                "Could not remove host map for %s: %s.",
                identifier, unicode(e))
            if 'not connected.' in e.output_as_unicode:
                raise CannotRemoveHostMap(
                    "The DHCP server could not be reached.")
            else:
                raise CannotRemoveHostMap("%s: %s." % (
                    identifier, e.output_as_unicode))
