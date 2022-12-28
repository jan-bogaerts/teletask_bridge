import json
import os

def validate_ha_section(section):
    """validates the home assistant config section

    Args:
        section (json object): the config part for ha
    """
    is_ok = True
    if not "discovery_prefix" in section:
        is_ok = False
        print("missing discovery_prefix field in home_assistant section")
    if not "client_id" in section:
        is_ok = False
        print("missing client_id field in home_assistant section")
    if not "broker_host" in section:
        is_ok = False
        print("missing broker_host field in home_assistant section")
    if not "device_id" in section:
        is_ok = False
        print("missing device_id field in home_assistant section")
    return is_ok


def validate_teletask_section(section):
    """validates the teletask config part

    Args:
        section (json object): teletask specific config data
    """
    is_ok = True
    if not "ip" in section:
        is_ok = False
        print("missing ip field in teletask section")
    if not "port" in section:
        is_ok = False
        print("missing port field in teletask section")
    return is_ok


def validate_assets_section(section):
    """validates the assets config part

    Args:
        section (json array): assets specific config data
    """
    is_ok = True
    count = 1
    for asset in section:
        name = '{}'.format(count)
        if not "name" in asset:
            is_ok = False
            print("missing name field in asset section, {}".format(name))
        else:
            name = '{}.{}'.format(count, asset['name'])
        if not "component" in asset:
            is_ok = False
            print("missing component field in asset section, {}".format(name))
        if not "teletask_type" in asset:
            is_ok = False
            print("missing teletask_type field in asset section, {}".format(name))
        if not "central_unit" in asset:
            is_ok = False
            print("missing central_unit field in asset section, {}".format(name))
        if not "teletask_id" in asset:
            is_ok = False
            print("missing teletask_id field in asset section, {}".format(name))
        count += 1
    return is_ok


def validate_config(config):
    """checks the json config to see if all the required fields
        are present
    Args:
        config (json object): the config data
    """
    is_ok = True
    if not "home_assistant" in config:
        is_ok = False
        print("missing home_assistant section")
    else: 
        is_ok = validate_ha_section(config['home_assistant'])
    if not "teletask" in config:
        is_ok = False
        print("missing teletask section")
    else: 
        is_ok &= validate_teletask_section(config['teletask'])
    if not "assets" in config:
        is_ok = False
        print("missing assets section")
    else: 
        is_ok &= validate_assets_section(config['assets'])
    return is_ok


def load():
    """loads the config
    """
    print("loading config")
    if not os.path.exists('config.json'):
        print("no config found")
        return None
    with open('config.json', encoding='utf-8') as file:
        data = json.load(file)
        print("found config {}".format(json.dumps(data)))
        if not validate_config(data):
            return None
        return data

