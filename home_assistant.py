import asyncio
import json

import teletask

from gmqtt import Client as MQTTClient
from gmqtt import constants as MQTTConst

client = None
discovery_prefix = 'homeassistant'
node_id = "teletask_1"                                # the id of the teletask device for mqtt topics
on_actuator = None                                      # callback that handles actuator messages for teletask
main_loop = None                                        # async loop
is_connected = False
wait_for_connected = None


def on_connect(client, flags, rc, properties):
    global is_connected
    print('Connected')
    is_connected = True
    if wait_for_connected:                              # could be that other part is still waiting for the connection to be established before continuing
        wait_for_connected.set()

def on_message(client, topic, payload, qos, properties):
    print('RECV MSG:', payload)
    if not on_actuator:
        return
    payload = payload.decode()
    topic_parts = topic.split('/')
    teletask_parts = topic_parts[3].split('_')
    if len(teletask_parts) < 3:
        print("Invalid teletask part: " + topic_parts[3])
    else:
        main_loop.create_task(on_actuator(teletask_parts[0], teletask_parts[1], teletask_parts[2], payload))


def on_disconnect(client, packet, exc=None):
    print('Disconnected')
    global is_connected
    is_connected = False


def on_subscribe(client, mid, qos, properties):
    subscriptions = client.get_subscriptions_by_mid(mid)
    for subscription, granted_qos in zip(subscriptions, qos):
        if granted_qos == 0:
            print('subscribed to topic: {}'.format(subscription.topic))
        else:
            print('failed to subscribe to topic: {}'.format(subscription.topic))

async def start(config, callback, loop):
    global client, discovery_prefix, on_actuator, node_id, main_loop
    print("starting home-assistant connection")
    on_actuator = callback
    main_loop = loop
    discovery_prefix = config['discovery_prefix']
    node_id = config['device_id']

    client = MQTTClient(config['client_id'])

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    client.on_subscribe = on_subscribe

    try:
        await client.connect(config['broker_host'])
        return True
    except Exception as e:
        print('{}'.format(e))
        return False


async def stop():
    """
    close the connection
    """
    global client
    if client:
        await client.disconnect()
        client = None


def build_asset_def(base_topic, asset, key, is_first):
    payload = {
        "~": base_topic,
        "name": asset['name'],
        "unique_id": key,
        "stat_t": "~/state",
        "dev": {
            "ids": ["teletask"]
        }
    }
    if is_first:
        payload['dev']['mf'] = "teletask"
        payload['dev']['mdl'] = "micros+"

    if asset['component'] == 'button':
        payload['command_topic'] = "~/exec"
    else:
        if asset['teletask_type'] not in ['flag', 'sensor']:
            payload['cmd_t'] = "~/set"
        if 'device_class' in asset:
            payload['device_class'] = asset['device_class']
        if 'unit_of_measurement' in asset:
            payload['unit_of_measurement'] = asset['unit_of_measurement']
        if asset['teletask_type'] == 'dimmer':
            payload['bri_cmd_t'] = '~/setbri'
            payload['bri_stat_t'] = '~/statebri'
            payload['on_command_type'] = 'brightness' # only send brigthness instruction don't include on/off
        if asset['component'] == 'cover':
            payload['position_topic'] = '~/pos'
            payload['set_position_topic'] = '~/setpos'
    return payload

def load_asset(asset, is_first):
    key = teletask.build_key_from_asset(asset)
    base_topic = '{}/{}/{}/{}'.format(discovery_prefix, asset['component'], node_id, key)
    config_topic = '{}/config'.format(base_topic)
    payload = build_asset_def(base_topic, asset, key, is_first)
    client.publish(config_topic, bytearray(json.dumps(payload), 'utf-8'), qos=1)

async def load_assets(items):
    """
    let home assistant know which sensors & actuators we have
    - wait until connected
    - send discovery topics
    - subscribe to actuator commands
    """ 
    global wait_for_connected
    if not client:
        raise Exception("home-assistant not connected")
    if not is_connected:
        wait_for_connected = asyncio.Event()                    # let the event handler know we want to get warned
        await wait_for_connected.wait()
        wait_for_connected = None
    print("sending discovery data to home assistant")
    has_covers = False
    is_first = True
    for asset in items:
        load_asset(asset, is_first)
        is_first = False
        is_cover = asset['component'] == 'cover'
        if is_cover:
            asset = {"name": "calibrate cover {}".format(asset['name']), "component": "button", "teletask_type": "calibrate", "central_unit": 1, "teletask_id": asset['teletask_id']}    
            load_asset(asset, is_first)
        has_covers = has_covers or is_cover
    if has_covers:
        asset = {"name": "calibrate covers", "component": "button", "teletask_type": "calibrate", "central_unit": 1, "teletask_id": -1}
        load_asset(asset, is_first)
        client.subscribe('{}/+/{}/+/exec'.format(discovery_prefix, node_id))
    # need to get messages sent to this device for all actuators
    client.subscribe('{}/+/{}/+/set'.format(discovery_prefix, node_id))
    client.subscribe('{}/+/{}/+/setbri'.format(discovery_prefix, node_id))
    if has_covers:
        client.subscribe('{}/+/{}/+/setpos'.format(discovery_prefix, node_id))


def get_value(asset, value, as_dimmer=False):
    """convert the value to something home assistant can work with
    """
    component = asset['component']
    result = None
    if component == 'light':
        if not as_dimmer:                               # when as dimmer, always use the actual value
            if value[0] == 0:                           # need to compare the value, not the array
                result = 'OFF'
            else:
                result = 'ON'
    elif component == 'cover':
        # print("values: {}".format(value))
        if value[1] == 0:
            result = 'stopped'
        elif value[0] == 2:
            result = 'closing'
        else:
            result = 'opening'
    elif component == 'sensor':                     # a single numeric value (temperature), convert it to a string for easy sending?
        result = '{}'.format(value)
    if result == None:
        result = value                              # return the full array cause mqtt publish wants a byte array
    else:
        result = bytearray(result, 'utf-8')
    return result

def send(asset, value):
    if not client:
        raise Exception("not connected")
    key = teletask.build_key_from_asset(asset)
    if asset['teletask_type'] == 'dimmer':
        to_send = get_value(asset, value, False)
        topic = '{}/{}/{}/{}/state'.format(discovery_prefix, asset['component'], node_id, key)
        print("publishing to: {}, value: {}".format(topic, to_send))
        client.publish(topic, to_send, qos=0)

        to_send = get_value(asset, value, True)
        topic = '{}/{}/{}/{}/statebri'.format(discovery_prefix, asset['component'], node_id, key)
        print("publishing to: {}, value: {}".format(topic, to_send))
        client.publish(topic, to_send, qos=0)
    else:
        to_send = get_value(asset, value)
        topic = '{}/{}/{}/{}/state'.format(discovery_prefix, asset['component'], node_id, key)
        print("publishing to: {}, value: {}".format(topic, to_send))
        client.publish(topic, to_send, qos=0)

def send_cover_pos(asset, value):
    """special function to send the current position of the cover to this specific topic.

    Args:
        asset (object): the asset to send the value for
        value (integer): position of the cover
    """
    if not client:
        raise Exception("not connected")
    key = teletask.build_key_from_asset(asset)
    topic = '{}/{}/{}/{}/pos'.format(discovery_prefix, asset['component'], node_id, key)
    print("publishing to: {}, value: {}".format(topic, value))
    client.publish(topic, value, qos=0)