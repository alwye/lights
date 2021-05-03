import network
from machine import Pin
from umqtt.robust import MQTTClient
from ujson import loads
import time
import neopixel
from random import getrandbits
import ustruct as struct
import config as c

# LED config
commands_on_repeat = ['loop', 'loop_random', 'loop_strobing', 'loop_rainbow']

# Disable access point mode
ap = network.WLAN(network.AP_IF)
ap.active(False)

# Enable the station mode
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(c.WLAN_SSID, c.WLAN_PASS)

np = neopixel.NeoPixel(machine.Pin(c.DATA_PIN), c.LED_N, bpp=c.LED_BPP)

while not wlan.isconnected():
    time.sleep(0.1)


def split_sleep(ms):
    sleep_threshold = 500
    if read_mqtt_inline() is True:
        return True
    if ms < sleep_threshold:
        time.sleep_ms(ms)
    else:
        while ms > 0:
            if read_mqtt_inline() is True:
                return True
            ms = ms - sleep_threshold
            time.sleep_ms(sleep_threshold)


def _recv_len():
    mqtt_client.sock.setblocking(False)
    n = 0
    sh = 0
    while 1:
        b = mqtt_client.sock.read(1)[0]
        n |= (b & 0x7f) << sh
        if not b & 0x80:
            return n
        sh += 7


def read_mqtt_inline():
    global _topic, _message
    mqtt_client.sock.setblocking(False)
    res = mqtt_client.sock.read(1)
    mqtt_client.sock.setblocking(True)
    if res is None:
        return None
    if res == b"":
        raise OSError(-1)
    if res == b"\xd0":  # PINGRESP
        sz = mqtt_client.sock.read(1)[0]
        assert sz == 0
        return None
    op = res[0]
    if op & 0xf0 != 0x30:
        return None
    sz = _recv_len()
    topic_len = mqtt_client.sock.read(2)
    topic_len = (topic_len[0] << 8) | topic_len[1]
    topic = mqtt_client.sock.read(topic_len)
    sz -= topic_len + 2
    if op & 6:
        pid = mqtt_client.sock.read(2)
        pid = pid[0] << 8 | pid[1]
        sz -= 2
    msg = mqtt_client.sock.read(sz)

    _topic = topic
    _message = msg

    if op & 6 == 2:
        pkt = bytearray(b"\x40\x02\0\0")
        struct.pack_into("!H", pkt, 2, pid)
        mqtt_client.sock.write(pkt)
    elif op & 6 == 4:
        assert 0

    return True


def clear():
    np.fill((0, 0, 0, 0))
    np.write()


def cmd_fill(r, g, b, w):
    np.fill((r, g, b, w))
    np.write()


def cmd_loop_strobing(palette, delay):
    """
    palette = [{r,g,b,w},{r,g,b,w},...]
    :param palette:
    :param delay:
    :return:
    """
    for colour in palette:
        palette_tuple = (colour['r'],
                         colour['g'],
                         colour['b'],
                         colour['w'])
        np.fill(palette_tuple)
        np.write()
        if split_sleep(delay) is True:
            return


def cmd_loop(palette, delay):
    """
    palette = [{r,g,b,w},{r,g,b,w},...]
    :param palette:
    :param delay:
    :return:
    """

    for colour in palette:
        for led_i in range(c.LED_N):
            palette_tuple = (colour['r'],
                             colour['g'],
                             colour['b'],
                             colour['w'])
            np[led_i] = palette_tuple
            np.write()
            if split_sleep(delay) is True:
                return


def cmd_loop_rainbow(delay):
    """

    :param delay:
    :return:
    """

    ch_max = 150
    colours = [ch_max, 0, 0]

    main_ch = 0
    while True:
        if colours[main_ch] == ch_max:
            prev_ch = main_ch - 1
            if colours[prev_ch] > 0:
                colours[prev_ch] = colours[prev_ch] - 1
            elif colours[main_ch] == ch_max:
                main_ch = (main_ch + 1) % 3
        else:
            colours[main_ch] = colours[main_ch] + 1

        np.fill((colours[0], colours[1], colours[2], 0))
        np.write()

        time.sleep_ms(delay)


def cmd_loop_random(max_brightness, delay):
    # max_ch_intensity = floor(max_brightness / 4)
    for led_i in range(c.LED_N):
        # np.buf[4:] = np.buf[0:led_n*4 - 5]

        for i in range(c.LED_N - 1, 0, -1):
            np[i] = np[i - 1]

        colour = (getrandbits(6),
                  getrandbits(6),
                  getrandbits(6),
                  0)
        np[0] = colour
        np.write()
        if split_sleep(delay) is True:
            return


def cmd_handler(topic, message):
    global _topic, _message, _command
    _topic = topic
    _message = message
    try:
        message = loads(message)
        print(message)
        _command = message['command']
        if _command == 'fill':
            cmd_fill(r=message['args']['r'],
                     g=message['args']['g'],
                     b=message['args']['b'],
                     w=message['args']['w'])
        elif _command == 'loop':
            cmd_loop(palette=message['args']['palette'],
                     delay=message['args']['delay'])
        elif _command == 'loop_random':
            cmd_loop_random(max_brightness=message['args']['max_brightness'],
                            delay=message['args']['delay'])
        elif _command == 'loop_strobing':
            cmd_loop_strobing(palette=message['args']['palette'],
                              delay=message['args']['delay'])
        elif _command == 'loop_rainbow':
            cmd_loop_rainbow(delay=message['args']['delay'])
    except ValueError:
        print('invalid json')


_topic = ""
_message = ""
_command = ""
mqtt_client = MQTTClient(client_id=c.MQTT_CLIENT_ID,
                         server=c.MQTT_HOST,
                         port=c.MQTT_PORT,
                         user=c.MQTT_USER,
                         password=c.MQTT_PASS)
mqtt_client.set_callback(cmd_handler)

if not mqtt_client.connect(clean_session=True):
    mqtt_client.subscribe(c.MQTT_TOPIC)

while 1 and _command != 'stop':
    if mqtt_client.check_msg() is None:
        if _command in commands_on_repeat:
            cmd_handler(_topic, _message)
