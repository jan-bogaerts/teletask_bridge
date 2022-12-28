import asyncio
import math
import teletask_const as const

reader = None                   # streams for reading & writing
writer = None
waiting_for_ack = None          # when assigned, a asyncio.Event that indicates the set_actuator is waiting for an ack
keep_alive_task = None          # task that runs making certain that the connection is kept open

is_stopped = False              # flag gets set when we need to go out of the reader loop

stop_signal = None                     # signal that helps us stop the reader loop
on_event = None                 # callback for main, when we receive a message from teletaslk and it needs to be dispatched


def build_key(unit, type, nr):
    return '{}_{}_{}'.format(unit, type, nr)

def build_key_from_asset(asset):
    return '{}_{}_{}'.format(asset['central_unit'], asset['teletask_type'], asset['teletask_id'])

def function_to_teletask_type(value):
    """converts a number value found from a teletask packet to a string for the function
    Args:
        value (number): the teletask type
    """
    if value == const.FNC_RELAY:
        return 'relay'
    elif value == const.FNC_DIMMER:
        return 'dimmer'
    elif value == const.FNC_MOTORFNC:
        return 'motor'
    elif value == const.FNC_LOCMOOD:
        return 'locmood'
    elif value == const.FNC_TIMEDMOOD:
        return 'timedmood'
    elif value == const.FNC_GENMOOD:
        return 'genmood'
    elif value == const.FNC_FLAG:
        return 'flag'
    elif value == const.FNC_SENSOR:
        return 'sensor'
    elif value == const.FNC_PROCES:
        return 'process'
    elif value == const.FNC_REGIME:
        return 'regime'
    elif value == const.FNC_SERVICE:
        return 'service'
    elif value == const.FNC_COND:
        return 'cond'
    else:
        raise Exception("unknown value in config: {}".format(value))


def teletask_type_to_function(value):
    """converts the string value found in json to the number for the function
    Args:
        value (string): the teletask type
    """
    value = value.lower()
    if value == 'relay':
        return const.FNC_RELAY
    elif value == 'dimmer':
        return const.FNC_DIMMER
    elif value == 'motor':
        return const.FNC_MOTORFNC
    elif value == 'locmood':
        return const.FNC_LOCMOOD
    elif value == 'timedmood':
        return const.FNC_TIMEDMOOD
    elif value == 'genmood':
        return const.FNC_GENMOOD
    elif value == 'flag':
        return const.FNC_FLAG
    elif value == 'sensor':
        return const.FNC_SENSOR
    elif value == 'process':
        return const.FNC_PROCES
    elif value == 'regime':
        return const.FNC_REGIME
    elif value == 'service':
        return const.FNC_SERVICE
    elif value == 'cond':
        return const.FNC_COND
    else:
        raise Exception("unknown value in config: {}".format(value))


async def start(config, STOP, callback):
    """start the connection with the teletask machine
    Args:
        config (json object): {"ip": "string", "port": number}
        STOP (asyncIO signal) so we can monitor when the application needs to be stopped
        callback (async func) called when events arrive and need to be processed
    """
    global reader, writer, stop_signal, on_event, keep_alive_task
    print("starting teletask connection")
    try:
        stop_signal = STOP
        on_event = callback
        reader, writer = await asyncio.open_connection(config['ip'], config['port'])
        loop = asyncio.get_event_loop()
        keep_alive_task = loop.create_task(run_keep_alive())
        return True
    except Exception as e:
        print('error: {}'.format(e));
        return False


async def run_keep_alive():
    while True:
        await asyncio.sleep(15)
        if not waiting_for_ack:                         # if alraedy trying to send something, no need for a ping
            await send([const.COMMAND_KEEP_ALIVE])



async def stop():
    """close the connection
    """
    print('Close the teletask connection')
    global is_stopped
    keep_alive_task.cancel()
    is_stopped = True
    writer.close()
    await writer.wait_closed()
    print('teletask closed')


def get_checksum(msg):
    value = 0
    for byte in msg:                              # dont include the last byte of the body, that's the checksum value
        value += byte
    return value  % 256

def verify_checksum(msg):
    """checks if the checksum is correct for the message
    Args:
        msg (bytearray): list of bytes that were read
    """
    value = get_checksum(msg[:-1])
    if value != msg[-1]:
        raise Exception("checksum failed")


def convert_sensor(msg):
    value = round(int.from_bytes(msg[6:8], "big") / 10 - 273, 2)
    # target = int.from_bytes(msg[8:10], "big")
    # day = int.from_bytes(msg[10:12], "big")
    # night = int.from_bytes(msg[12:14], "big")
    # result = [value, target, day, night]
    return value


async def process_message(msg):
    """checks the incomming message and dispatches it as needed
    Args:
        msg (bytearray): list of bytes that were read
    """
    if not on_event:
        print("internal error: no event callback")
        return
    if msg[0] == const.COMMAND_REPORT:
        unit = msg[1]
        type = function_to_teletask_type(msg[2])
        nr = int.from_bytes(msg[3:5], "big")
        values = None
        if msg[2] == const.FNC_MOTORFNC:
            values = [msg[6], msg[7]]
        elif msg[2] == const.FNC_SENSOR:
            values = convert_sensor(msg)
        else:
            values = [msg[6]]
        await on_event(unit, type, nr, values)



async def read_block(nr_bytes):
    """blocks until something is read or stop has been set
    Args:
        nr_bytes (number): nr of bytes to read
    Returns:
        byte_array: list of bytes read or None
    """
    read_task = asyncio.create_task(reader.read(nr_bytes))
    stop_task = asyncio.create_task(stop_signal.wait())
    pending = (read_task, stop_task)
    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
    if stop_task in done:
        await stop()
        return None
    else:
        value = await done.pop()
        results = []
        for x in value:
            results.append(x)
        # print('Received: {}'.format(results))
        return results


async def read_messages():
    global waiting_for_ack
    while True:
        bytes = await read_block(100)
        if not bytes or len(bytes) == 0:
            return None
        else:
            curPos = 0
            msgs = []
            while curPos < len(bytes):
                if bytes[0] == const.COMMAND_ACK and waiting_for_ack:
                    waiting_for_ack.set()
                    waiting_for_ack = None
                    curPos += 1
                elif bytes[curPos] != 0x02:                               # incorrect start of message
                    curPos += 1
                else:
                    length = bytes[curPos + 1]
                    msgs.append(bytes[curPos:curPos+length+1])
                    curPos += length + 1
            if len(msgs) > 0:
                return msgs

async def read():
    """reads and dispatches the messages as needed.
    """
    while not is_stopped:
        try:
            msgs = await read_messages();                       # get all possible messages received in 1 read 
            if not msgs:                                      # streamreader has been closed
                break
            for msg in msgs:
                verify_checksum(msg)
                body = msg[1:]
                print(f'Received: {body!r}')
                await process_message(body[1:])
        except Exception as ex:
            print(ex)


async def send(msg):
    global waiting_for_ack
    if waiting_for_ack:                                             # if there is a previous write action, wait till it's done
        await asyncio.wait_for(waiting_for_ack.wait(), 2.0) 
    body = [0x02, 0x00] + msg
    body[1] = len(body)
    body.append(get_checksum(body))
    print(f'Send: {body!r}')
    waiting_for_ack = asyncio.Event()
    writer.write(bytearray(body))
    await writer.drain()
    try:
        await asyncio.wait_for(waiting_for_ack.wait(), 1.0)           # need to havea  response in time, otherwise, we regard it as lost
    except asyncio.TimeoutError:
        print('message ack timed out')
    waiting_for_ack = None


def value_to_number(value):
    if value == 'ON':
        return const.SET_ON
    elif value == 'OFF':
        return const.SET_OFF
    elif value == 'OPEN':
        return const.SET_MTRUP
    elif value == 'STOP':
        return const.SET_MTRSTOP
    elif value == 'CLOSE':
        return const.SET_MTRDOWN
    elif  value.isnumeric() == True:
        return int(value)
    else:
        print("error: invalid value: {}, can't convert".format(value))

def split_2_bytes(value):
    low = value % 255
    high = math.trunc(value / 255)
    return low, high

async def set_actuator(asset, value):
    """sends an actuator command to the specified asset

    Args:
        asset (object): the asset definition
        value (number): value to send
    """
    print("teletask send value {} to {}".format(value, asset['name']))
    fnc = teletask_type_to_function(asset['teletask_type'])
    teletask_id_low, teletask_id_high = split_2_bytes(asset['teletask_id'])
    value = value_to_number(value)
    if not value == None:
        msg = [const.COMMAND_SET, asset['central_unit'], fnc, teletask_id_high, teletask_id_low, value]
        await send(msg)
    

async def load_assets(items):
    if not writer:
        raise Exception("teletask not connected")
    # start monitoring all the functions of teletask so we can receive
    # events
    to_monitor = [const.FNC_RELAY, const.FNC_DIMMER, const.FNC_MOTORFNC, 
        const.FNC_LOCMOOD, const.FNC_TIMEDMOOD, const.FNC_FLAG, const.FNC_SENSOR,
        const.FNC_PROCES, const.FNC_REGIME, const.FNC_SERVICE, const.FNC_MESSAGE,
        const.FNC_COND]
    print("start logging teletask events")
    for function in to_monitor:
        msg = [const.COMMAND_LOG, function, const.SET_ON]
        await send(msg)
    # request the current values so home-assistant is up to date.
    print("request teletask states")
    covers = []
    for asset in items:
        if asset['component'] == 'cover':
            covers.append(asset)
        fnc = teletask_type_to_function(asset['teletask_type'])
        teletask_id_low, teletask_id_high = split_2_bytes(asset['teletask_id'])
        msg = [const.COMMAND_GET, asset['central_unit'], fnc, teletask_id_high, teletask_id_low]
        await send(msg)
