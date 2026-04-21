# Step 03 - routers app

## Status: DONE

---

## What Was Built

### New Files

| File | Purpose |
|------|---------|
| apps/routers/models.py | Router, RouterInterface, InterfaceTrafficSnapshot models |
| apps/routers/mikrotik.py | MikroTik API service (connect, test, interfaces, traffic, PPP) |
| apps/routers/services.py | Business logic: sync_interfaces, get_live_traffic |
| apps/routers/forms.py | RouterForm, RouterCoordinatesForm, InterfaceLabelForm |
| apps/routers/views.py | All router and interface views |
| apps/routers/urls.py | URL routes |
| apps/routers/serializers.py | DRF serializers |
| apps/routers/api_views.py | DRF API views |
| apps/routers/api_urls.py | /api/v1/routers/ routes |
| apps/routers/migrations/0001_initial.py | Auto-generated migration |
| templates/routers/list.html | Router cards grid |
| templates/routers/add.html | Add router with JS test connection |
| templates/routers/detail.html | Port UI, sessions, VLANs, bridges, tunnels |
| templates/routers/interface_detail.html | Live traffic + label editor |
| templates/routers/partials/traffic_widget.html | HTMX partial: RX/TX widget |
| templates/routers/edit.html | Edit router form |
| templates/routers/confirm_delete.html | Soft delete confirmation |
| templates/routers/coordinates.html | Lat/lng update form |

---

## Models

### Router
- name, host, username, password, api_port
- description, location, latitude, longitude
- status: online / offline / unknown
- last_seen, is_active (soft delete)

### RouterInterface
- Linked to Router via FK
- iface_type: ether, vlan, bridge, pppoe-in, wg, zerotier, loopback, other
- role: uplink, olt, libreqos, libreqos_mgmt, wifi, pppoe, dhcp, management, client, pisowifi, other
- label: admin-set custom name
- is_running, is_slave, is_dynamic (pulled from MikroTik flags)
- unique_together: (router, name)
- display_name property: returns label if set, else name
- is_physical property: True if iface_type == ether
- is_session property: True if iface_type == pppoe-in

### InterfaceTrafficSnapshot
- Linked to RouterInterface
- rx_bits_per_second, tx_bits_per_second
- rx_packets_per_second, tx_packets_per_second
- rx_mbps, tx_mbps properties (computed)

---

## MikroTik API Functions (mikrotik.py)

| Function | What it does |
|----------|-------------|
| test_connection() | Test before save, returns (ok, identity_name) |
| get_connection() | Returns (api, connection_pool) |
| get_interfaces() | Pull all interfaces via /interface |
| get_interface_traffic() | monitor-traffic once for one interface |
| get_ppp_active() | Pull /ppp/active sessions |
| get_ppp_secrets() | Pull /ppp/secret list |
| add_ppp_secret() | Add PPP secret to router |
| get_system_resource() | CPU, memory, uptime |
| get_system_identity() | Router name |

---

## Key Behaviors

- Test connection is required before saving a new router (Save button disabled until test passes)
- Sync interfaces: pulls all from MikroTik, updates MikroTik-owned fields, never overwrites label/role/comment
- If router is unreachable during sync: status set to offline
- Physical ports shown as clickable cards in detail view
- PPPoE sessions, VLANs, bridges, tunnels shown in separate panels
- Live traffic uses HTMX hx-trigger="load, every 10s" polling
- Soft delete: is_active=False, never hard delete

---

## URL Routes

| URL | View | Name |
|-----|------|------|
| /routers/ | router_list | router-list |
| /routers/add/ | router_add | router-add |
| /routers/{pk}/ | router_detail | router-detail |
| /routers/{pk}/edit/ | router_edit | router-edit |
| /routers/{pk}/delete/ | router_delete | router-delete |
| /routers/{pk}/sync/ | router_sync | router-sync |
| /routers/{pk}/coordinates/ | router_coordinates | router-coordinates |
| /routers/{pk}/interfaces/{id}/ | interface_detail | interface-detail |
| /routers/{pk}/interfaces/{id}/traffic/ | interface_traffic_poll | interface-traffic-poll |
| /routers/test-connection/ | test_connection_view | router-test-connection |

## API Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| GET/POST | /api/v1/routers/ | List / create routers |
| GET/PATCH/DELETE | /api/v1/routers/{pk}/ | Router detail |
| POST | /api/v1/routers/{pk}/sync/ | Sync interfaces |
| GET | /api/v1/routers/{pk}/interfaces/ | List interfaces |
| GET | /api/v1/routers/{pk}/interfaces/{id}/traffic/ | Live traffic JSON |
| POST | /api/v1/routers/test-connection/ | Test connection |

---

## Next Step
Step 04: subscribers app - sync from MikroTik, admin management, client portal OTP
