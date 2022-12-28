import asyncio
import signal
import home_assistant as HA
import teletask
import config as Config
import roller_shutters as RS
import platform

STOP = asyncio.Event()
assets_dict = {}                            # provides a mapping between teletask-ids and loaded assets. allows us to see if we are really monitoring an event or not (teletask just sends everything)


def ask_exit(*args):
    print("stop called, closing down")
    STOP.set()


async def handle_teletask_event(unit, type, nr, values):
    """called when a teletask message arrived
        Teletask sends 
    Args:
        unit (nr): the nr of the unit
        type (string) the teletask function / type
        nr (number) the asset number
        values (array) the values that were reported 
    """
    key = teletask.build_key(unit, type, nr)
    if key in assets_dict:
        asset = assets_dict[key]
        cover_value = None
        HA.send(asset, values)
        if asset['component'] == 'cover':
            cover_value = await RS.handle_cover_event(key, asset, values)
        if cover_value:
            HA.send_cover_pos(asset, cover_value)


async def calibrate_covers():
    """looks up the list of assets that are used as covers and records the timing for each.
    """
    covers = [value for key, value in assets_dict.items() if value['component'] == 'cover']
    await RS.calibrate(covers)
    for cover in covers:                        # need to let home-assistant know that all covers are closed now
        HA.send_cover_pos(cover, 0)
    

async def calibrate_cover(id):
    id = int(id)
    covers = [value for key, value in assets_dict.items() if value['component'] == 'cover' and value['teletask_id'] == id]
    if len(covers) == 1:
        await RS.calibrate(covers, False)
        HA.send_cover_pos(covers[0], 0)

async def handle_actuator(unit, type, nr, value):
    try:
        key = teletask.build_key(unit, type, nr)
        if key in assets_dict:
            asset = assets_dict[key]
            value = value
            if asset['component'] == 'cover' and value.isnumeric():
                await RS.move_to(key, asset, int(value))
                HA.send_cover_pos(asset, value)
            else:
                await teletask.set_actuator(asset, value)
        elif key == '1_calibrate_-1':
            await calibrate_covers()
        elif key.startswith('1_calibrate_'):
            await calibrate_cover(key[12:])
    except Exception as e:
        print('{}'.format(e))


async def load_assets(items):
    """prepares everything for the assets

    Args:
        items (array): list of assets to create a bridge for
    """
    print("start loading assets")
    for asset in items:                                                     # build the dict so we can use it as a filter on the data coming from teletask
        key = teletask.build_key_from_asset(asset)
        assets_dict[key] = asset
    await HA.load_assets(items)
    await teletask.load_assets(items)
    for key, value in RS.COVER_DATA.items():
        HA.send_cover_pos(assets_dict[key], value['position'])

async def main(loop):
    """
    main loop
    """
    config = Config.load()
    if not config:                                          # something went wrong loading the config, don't continue, exit the app
        return
    RS.load_config()
    started = await HA.start(config['home_assistant'], handle_actuator, loop)
    if not started:
        print('HA not started, stopping')
        return
    started = await teletask.start(config['teletask'], STOP, handle_teletask_event)
    if not started:
        print('teletask not started, stopping')
        return
    asyncio.create_task(load_assets(config['assets']))      # do soon, give teletask read a change to start
    await teletask.read()                                   # blocks until stop has been set
    await HA.stop()
    RS.save_config()                                        # make certain that the latest cover positions is saved.
    # teletask is already stopped through th stop signal


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    if platform.system() == 'Windows':
        signal.signal(signal.SIGINT, ask_exit)
        signal.signal(signal.SIGTERM, ask_exit)
    else:
        loop.add_signal_handler(signal.SIGINT, ask_exit)
        loop.add_signal_handler(signal.SIGTERM, ask_exit)
    loop.run_until_complete(main(loop))
    loop.close()

