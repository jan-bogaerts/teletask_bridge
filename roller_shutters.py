import asyncio
import json
import os
import time

import teletask

COVER_DATA = None
is_calibrating = False                      # flag that keeps track if we are calibrating or not

def load_config():
    """load the data

    Args:
        items (list): asset items
    """
    global COVER_DATA
    print('load cover configs')
    if not os.path.exists('covers.json'):
        print("no cover configs found, resetting to empty")
        COVER_DATA = {}
        return
    with open('covers.json', 'r') as file:
        COVER_DATA = json.load(file)
        print("found cover data: {}".format(json.dumps(COVER_DATA)))


def save_config():
    print("saving the new config")
    with open('covers.json', 'w') as file:
        json.dump(COVER_DATA, file, indent=4)

async def calibrate(items, overwrite=True):
    """measures the timing of all the items in the list

    Args:
        items (lsit): asset items
    """
    global is_calibrating, COVER_DATA
    is_calibrating = True
    try:
        print("beginning calibration")
        if overwrite:
            COVER_DATA = {}
        to_wait_for = []
        for cover in items:
            key = teletask.build_key_from_asset(cover)
            new_cover = {
                'wait_for': asyncio.Event(),
                'move_start_at': time.time()
            }
            COVER_DATA[key] = new_cover
            to_wait_for.append(new_cover['wait_for'].wait())
            print("preparing cover {} for calibration".format(key))
            await teletask.set_actuator(cover, 'OPEN')          # first make certain that the cover is fully opened before starting to measure.
            await asyncio.sleep(2.1)                            # wait a little bit (just a little longer than the ack-timeout to be save) before starting the next cover so that the electric system doesn't have too many issssues
        print("waiting for calibration to complete")
        done, pending = await asyncio.wait(to_wait_for)         # wait until all covers have reported being done with the calibration
        print("calibration done")
        save_config()
    finally:
        is_calibrating = False

def calculate_pos(cover, is_closing):
    """cover has stopped moving, so calculate the duration of the movement and adjust
    the current position accordingly

    Args:
        cover (object): cover data
        is_closing (bool): was the cover closing or opening
    Returns: if a new value is calculated, this is returned
    """
    if 'move_start_at' in cover:                                        # the end event actually comes 2 times, looks like an update in it's own position value (bad), so we need to skip this
        duration = time.time() - cover['move_start_at']
        total_time = cover['duration_down'] if is_closing else cover['duration_up']
        change = 100 / total_time * duration                     # percentage that the cover moved
        change = round(change)                                          # keep it in the integer range
        new_value = cover['position']
        if is_closing:
            new_value -= change
        else:
            new_value += change
        if new_value < 0:                                               # make certain we stay within the limit
            new_value = 0
        if new_value > 100:
            new_value = 100
        cover['position'] = new_value
        del cover['move_start_at']                                      # value no longer needed
        save_config()
        return new_value

async def handle_cover_event(key, asset, values):
    """called by main wheneve teletask has reported a new cover event

    Args:
        key (string): the key that identifies the asset
        asset (object): the cover config data
        values (list): byte values received from teletask
    Returns: if a new cover value is calculated, this is returned
    """
    direction_up = values[0] == 1
    moving = not (values[1] == 0)
    print("received cover event: is_up={} - moving={}".format(direction_up, moving))
    if not key in COVER_DATA:
        print('event for uncalibrated cover: {}, skipping'.format(asset['name']))
        return
    cover = COVER_DATA[key]
    if moving:                                                          # movement started, only record if didn't come from us (to get timing best)
        if not 'move_start_at' in cover:                                # sometimes, we get the even slowly, so when possible, store it when the command is sent
            cover['move_start_at'] = time.time()
            print("move started at: {}".format(cover['move_start_at']))
        else: 
            print("move start event received at: {}, original: {}".format(time.time(), cover['move_start_at']))
    elif not is_calibrating:
        return calculate_pos(cover, values[0] == 2)
    else:                                                # movement stopped
        if direction_up == True:                                        # cover fully open
            if 'duration_down' in cover:                                # calibration is done for going up, process fully done for this cover
                cover['duration_up'] = time.time() - cover['move_start_at']
                print("total cover duration up: {} for {}".format(cover['duration_up'], asset['name']))
                del cover['move_start_at']                              # value no longer needed
                cover['position'] = 100                                 # cover is now fully closed, so set position to 0
                cover['wait_for'].set()
                del cover['wait_for']
            else:                                                       # cover open after start of calibration. we can start closing it to begin the full measurement
                print("closing cover to start measuring")
                cover['move_start_at'] = time.time()
                await teletask.set_actuator(asset, 'CLOSE')
        elif not 'duration_down' in cover:                              # cover is fully closed, calibration going down is done. we get this event 2 times, so skip the second.
            cover['duration_down'] = time.time() - cover['move_start_at']
            print("total cover duration down: {} for {}".format(cover['duration_down'], asset['name']))
            cover['position'] = 0                                       # cover is now fully closed, so set position to 0
            await asyncio.sleep(2.1)                                    # give some time to let the motor rest. Don't overburden the electric system (just a little longer than the ack-timeout to be save)
            cover['move_start_at'] = time.time()                        # to make certain that we have this, could mis it (if didn't get ack in time for set_actuator)
            await teletask.set_actuator(asset, 'OPEN')

async def move_to(key, asset, value):
    """moves the cover to the specified position

    Args:
        asset (object): the cover to change the position of
        value (integer): the absolute position to move to
    """
    if not key in COVER_DATA:
        print('move cover request for uncalibrated cover: {}, skipping'.format(asset['name']))
        return
    
    cover = COVER_DATA[key]
    current_pos = int(cover['position'])                                # safety: make certain we compare numbers
    if current_pos == value:
        print('move cover request for {} to {} already there'.format(asset['name'], value))
        return
    print("moving cover {} to {}".format(asset['name'], value))
    dif = abs(value - current_pos)
    cover['move_start_at'] = time.time()
    if value > current_pos:
        move_duration = cover['duration_up'] / 100 * dif
        await teletask.set_actuator(asset, 'OPEN')
    else:
        move_duration = cover['duration_down'] / 100 * dif
        await  teletask.set_actuator(asset, 'CLOSE')
    await asyncio.sleep(move_duration)
    await  teletask.set_actuator(asset, 'STOP')
    cover['position'] = value
    save_config()