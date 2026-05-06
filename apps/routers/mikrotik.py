import routeros_api
from apps.settings_app.models import RouterSettings


def get_connection(router):
    settings = RouterSettings.get_settings()
    try:
        connection = routeros_api.RouterOsApiPool(
            host=router.host,
            username=router.username,
            password=router.password,
            port=router.api_port,
            plaintext_login=True,
        )
        api = connection.get_api()
        return api, connection
    except Exception as e:
        raise ConnectionError(f"Cannot connect to {router.host}: {str(e)}")


def test_connection(host, username, password, port=8728):
    try:
        pool = routeros_api.RouterOsApiPool(
            host=host,
            username=username,
            password=password,
            port=int(port),
            plaintext_login=True,
        )
        api = pool.get_api()
        identity = api.get_resource('/system/identity').get()
        pool.disconnect()
        name = identity[0].get('name', 'Unknown') if identity else 'Unknown'
        return True, name
    except Exception as e:
        return False, str(e)


def get_interfaces(router):
    api, conn = get_connection(router)
    try:
        resource = api.get_resource('/interface')
        ifaces = resource.get()
        conn.disconnect()
        return ifaces
    except Exception as e:
        conn.disconnect()
        raise RuntimeError(f"Failed to get interfaces: {str(e)}")


def get_interface_traffic(router, interface_name):
    api, conn = get_connection(router)
    try:
        monitor = api.get_resource('/interface')
        result = monitor.call('monitor-traffic', {
            'interface': interface_name,
            'once': '',
        })
        conn.disconnect()
        if result:
            return result[0]
        return {}
    except Exception as e:
        conn.disconnect()
        raise RuntimeError(f"Failed to get traffic for {interface_name}: {str(e)}")


def get_ppp_active(router, include_stats=False):
    api, conn = get_connection(router)
    try:
        resource = api.get_resource('/ppp/active')
        if include_stats:
            try:
                sessions = resource.call('print', {'stats': ''})
            except Exception:
                sessions = resource.get()
            if not sessions:
                sessions = resource.get()
        else:
            sessions = resource.get()
        conn.disconnect()
        return sessions
    except Exception as e:
        conn.disconnect()
        raise RuntimeError(f"Failed to get PPP active sessions: {str(e)}")


def get_pppoe_interface_stats(router):
    api, conn = get_connection(router)
    try:
        resource = api.get_resource('/interface')
        rows = resource.call('print', {'stats': ''})
        conn.disconnect()
        stats = {}
        for row in rows:
            if row.get('type') != 'pppoe-in':
                continue
            iface_name = row.get('name', '')
            if not (iface_name.startswith('<pppoe-') and iface_name.endswith('>')):
                continue
            username = iface_name[len('<pppoe-'):-1].strip()
            if not username:
                continue
            stats[username] = row
        return stats
    except Exception as e:
        conn.disconnect()
        raise RuntimeError(f"Failed to get PPPoE interface stats: {str(e)}")


def get_ppp_secrets(router):
    api, conn = get_connection(router)
    try:
        resource = api.get_resource('/ppp/secret')
        secrets = resource.get()
        conn.disconnect()
        return secrets
    except Exception as e:
        conn.disconnect()
        raise RuntimeError(f"Failed to get PPP secrets: {str(e)}")


def _disconnect_safely(conn):
    try:
        conn.disconnect()
    except Exception:
        pass


def _set_disabled_by_lookup(router, resource_path, lookups, disabled, label):
    lookup_items = [(key, value) for key, value in lookups if value not in (None, '')]
    if not lookup_items:
        return False, f"Missing lookup data for {label}."

    api, conn = get_connection(router)
    try:
        resource = api.get_resource(resource_path)
        records = []
        matched_key = ''
        matched_value = ''

        for key, value in lookup_items:
            try:
                records = resource.get(**{key: str(value)})
            except Exception:
                records = []
            if records:
                matched_key = key
                matched_value = value
                break

        if not records:
            lookup_text = ', '.join(f"{key}={value}" for key, value in lookup_items)
            return False, f"No {label} found on router for {lookup_text}."

        record = records[0]
        record_id = record.get('id') or record.get('.id')
        if not record_id:
            return False, f"{label} matched by {matched_key}={matched_value} has no RouterOS id."

        resource.set(id=record_id, disabled='yes' if disabled else 'no')
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        _disconnect_safely(conn)


def _remove_by_lookup(router, resource_path, lookups, label, missing_ok=False):
    lookup_items = [(key, value) for key, value in lookups if value not in (None, '')]
    if not lookup_items:
        return False, f"Missing lookup data for {label}."

    api, conn = get_connection(router)
    try:
        resource = api.get_resource(resource_path)
        records = []
        matched_key = ''
        matched_value = ''

        for key, value in lookup_items:
            try:
                records = resource.get(**{key: str(value)})
            except Exception:
                records = []
            if records:
                matched_key = key
                matched_value = value
                break

        if not records:
            if missing_ok:
                return True, None
            lookup_text = ', '.join(f"{key}={value}" for key, value in lookup_items)
            return False, f"No {label} found on router for {lookup_text}."

        record = records[0]
        record_id = record.get('id') or record.get('.id')
        if not record_id:
            return False, f"{label} matched by {matched_key}={matched_value} has no RouterOS id."

        resource.remove(id=record_id)
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        _disconnect_safely(conn)


def set_ppp_secret_disabled(router, username, disabled=True):
    return _set_disabled_by_lookup(
        router,
        '/ppp/secret',
        [('name', username)],
        disabled,
        'PPP secret',
    )


def set_hotspot_user_disabled(router, username, disabled=True):
    return _set_disabled_by_lookup(
        router,
        '/ip/hotspot/user',
        [('name', username)],
        disabled,
        'Hotspot user',
    )


def set_dhcp_lease_disabled(router, username='', mac_address='', ip_address=None, disabled=True):
    return _set_disabled_by_lookup(
        router,
        '/ip/dhcp-server/lease',
        [
            ('mac-address', mac_address),
            ('address', ip_address),
            ('comment', username),
            ('host-name', username),
        ],
        disabled,
        'DHCP lease',
    )


def remove_ppp_active_session(router, username):
    return _remove_by_lookup(
        router,
        '/ppp/active',
        [('name', username)],
        'PPP active session',
        missing_ok=True,
    )


def remove_hotspot_active_session(router, username):
    return _remove_by_lookup(
        router,
        '/ip/hotspot/active',
        [('user', username)],
        'Hotspot active session',
        missing_ok=True,
    )


def remove_dhcp_lease(router, username='', mac_address='', ip_address=None):
    return _remove_by_lookup(
        router,
        '/ip/dhcp-server/lease',
        [
            ('mac-address', mac_address),
            ('address', ip_address),
            ('comment', username),
            ('host-name', username),
        ],
        'DHCP lease',
        missing_ok=True,
    )


def add_ppp_secret(router, username, password, profile='default', service='pppoe', comment=''):
    api, conn = get_connection(router)
    try:
        resource = api.get_resource('/ppp/secret')
        resource.add(
            name=username,
            password=password,
            profile=profile,
            service=service,
            comment=comment,
        )
        conn.disconnect()
        return True, 'PPP secret added.'
    except Exception as e:
        conn.disconnect()
        return False, str(e)


def get_system_resource(router):
    api, conn = get_connection(router)
    try:
        resource = api.get_resource('/system/resource')
        data = resource.get()
        conn.disconnect()
        return data[0] if data else {}
    except Exception as e:
        conn.disconnect()
        raise RuntimeError(f"Failed to get system resource: {str(e)}")


def get_system_identity(router):
    api, conn = get_connection(router)
    try:
        resource = api.get_resource('/system/identity')
        data = resource.get()
        conn.disconnect()
        return data[0].get('name', '') if data else ''
    except Exception as e:
        conn.disconnect()
        raise RuntimeError(f"Failed to get identity: {str(e)}")
