# teletask_bridge
A teletask to home-assistant bridge

This application allows you to take full control of your teletask setup through the home-assistant gateway. It registers your teletask unit as an mqtt device and adds all the sensors/actuators that you have defined in the config.

## installation

- download the app to your system:

```
mkdir telehob
cd telehob
git clone xxxx
```
- configure your system (see [below](#configuration))
- run the app: `python main.py`
- set up the application to auto start:
  - you can use launcher.sh: adjust the paths used in the file according to your own setup.
  - the 30 sec delay in the script allows for home-assistant to start up first, otherwise the script will run too soon and the devices won't be registered.
  - make the script executable `chmod 755 launcher.sh`
  - add to crontab: `sudo crontab -e`

## configuration
Auto discovery is used on the home-automation side to load all the assets. Teletask however doesn't support auto-discovery, so you will have to define the list yourself.
All config data is stored in the file `config.json`, located in the application folder. It requires the following sections:

- home_assistant: broker details
  - discovery_prefix: topic prefix used for auto-discovery. Usually `homeassistant`
  - client_id: identify this client with the broker, should be unique for each device
  - broker_host: name/ip address of the broker
  - device_id: identifier for this device in home-assistant
- teletask: all the details to connect to the teletask device
  - ip: the ip address of the teletask unit
  - port: the port number to connect to.
- assets: all the sensors and actuators that you would like to have registered in home-assistant.
  - name: label used in home-assistant
  - component: the mqtt component used to register the asset in home assistant. See [mqtt configuration](https://www.home-assistant.io/integrations/mqtt/#configure-mqtt-options) for more info.
  - teletask_type: the type of the component on the teletask side. Supported types are:
    - relay
    - dimmer
    - motor
    - locmood
    - timedmood
    - genmood
    - flag
    - sensor
    - process
    - regime
    - service
    - cond
  - teletask_id: the id number to identify the item in teletask. This can be found with the prosoft application of teletask.
