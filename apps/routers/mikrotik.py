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
