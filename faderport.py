# Copyright (c) 2021 Raphaël Doursenaud <rdoursenaud@free.fr>

import collections
from itertools import cycle, islice
from collections import namedtuple
from abc import ABC, abstractmethod
import time

import mido

Button = namedtuple('Button', ['name', 'press'])
Button.__doc__ = "FaderPort button details."
Button.name.__doc__ = "Button name, usually what's written on the physical button."
Button.press.__doc__ = "MIDI note sent when button is pressed and released and MIDI note to send to illuminate the button."

# These are the FaderPort buttons, specifically ordered to "snake" down from
# the top to the bottom. Changing the order will mess up the pattern :-(

BUTTONS = [
    Button(name='Solo', press=8),  # FIXME: lights
    Button(name='Mute', press=16),
    Button(name='Arm', press=0),
    Button(name='Shift', press=70),
    Button(name='Bypass', press=3),
    Button(name='Touch', press=77),
    Button(name='Write', press=75),
    Button(name='Read', press=74),
    Button(name='Prev', press=46),
    Button(name='Knob', press=32),
    Button(name='Next', press=47),
    Button(name='Link', press=5),
    Button(name='Pan', press=42),
    Button(name='Channel', press=54),
    Button(name='Scroll', press=56),
    Button(name='Master', press=58),
    Button(name='Click', press=59),
    Button(name='Section', press=60),
    Button(name='Marker', press=61),
    Button(name='Loop', press=86),
    Button(name='Rewind', press=91),
    Button(name='Forward', press=92),
    Button(name='Stop', press=93),
    Button(name='Play', press=94),
    Button(name='Record', press=95),
    Button(name='Pedal', press=102)
]

_button_from_name = {x.name: x for x in BUTTONS}
#_button_from_name["Rec Arm"] = _button_from_name["Rec"]  # Add an alias
_button_from_press = {x.press: x for x in BUTTONS}


def button_from_name(name: str) -> Button:
    """
    Given a button name return the corresponding Button
    :param name: The name of a button
    :return: a Button
    """
    return _button_from_name[name.title()]


def button_from_press(press: int) -> Button:
    """
    Given a button press value return the corresponding button
    :param press: The value emitted by a pressed button
    :return: a Button
    """
    return _button_from_press.get(press, None)


# characters maps characters to the indices of the buttons that will
# display that character (as a matrix) when lit.
CHARACTERS = {
    '0': (0, 1, 2, 3, 4, 7, 11, 14, 15, 16, 17, 18),
    '1': (1, 2, 4, 6, 13, 15, 16, 17, 18),
    '2': (1, 2, 4, 7, 10, 12, 15, 16, 17, 18),
    '3': (1, 2, 4, 7, 8, 10, 11, 14, 16, 17),
    '4': (2, 5, 8, 10, 11, 12, 13, 14, 18),
    '5': (1, 2, 4, 7, 8, 13, 15, 16, 17, 18),
    # FIXME
    '6': (0, 1, 2, 3, 4, 8, 10, 11, 14, 15, 16, 17, 18),
    '7': (0, 1, 2, 3, 7, 13, 16),
    '8': (0, 1, 2, 3, 5, 6, 12, 13, 15, 16, 17, 18),
    '9': (0, 1, 2, 3, 4, 7, 8, 10, 14, 15, 16, 17, 18),
    'A': (4, 5, 7, 10, 11, 12, 13, 14, 15, 18, 19, 23),
    'B': (4, 5, 6, 7, 10, 12, 13, 14, 15, 18, 20, 21, 22, 23),
    'C': (4, 5, 7, 10, 14, 15, 18, 20, 21, 22),
    'D': (4, 5, 6, 7, 10, 11, 14, 15, 18, 20, 21, 22, 23),
    'E': (4, 5, 6, 7, 13, 14, 15, 20, 21, 22, 23),
    'F': (4, 5, 6, 7, 13, 14, 15, 23)
}


class FaderPort(ABC):
    """
    An abstract class to interface with a Presonus FaderPort device.

    The Presonus FaderPort is a USB MIDI controller that features a
    motorized fader, an endless rotary controller and a bunch of buttons.
    This class will handle the basic interfacing to the device. You
    write a concrete subclass to implement your application specific
    requirements.

    This subclass must implement the following methods:

    * `on_button` — Called when button is pressed or released,
    * `on_close` — Called when MIDI port is about  to close,
    * `on_fader` — Called when fader is moved,
    * `on_fader_touch` — Called when fader is touched or released,
    * `on_open` — Called when MIDI port has opened,
    * `on_rotary` — Called when the Pan control is rotated.

    The `fader` property allows you to read or set the fader position
    on a scale of 0 to 1023.

    You can turn the button lights on and off individually using
    `light_on` and `light_off`.

    You can display hexadecimal characters (0-9, A-F) using `char_on`.
    This will use the button LEDs in a dot matrix style.
    (Extending this to the a full alphanumeric character set is an
    exercise left to the reader).

    There some methods for 'fancy' display effects, because why not?
    Check out: `countdown`, `snake`, `blink` and `chase`

    **IMPORTANT NOTE** - There is a 'feature' in the FaderPort that can
    cause you some problems. If the 'Off' button is lit the fader will
    not send value updates when it's moved.
    """

    def __init__(self):
        self.inport = None
        self.outport = None
        self._fader = -8192
        self._msb = 0

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def open(self, number=0):
        """
        Open the FaderPort and register a callback so we can send and
        receive MIDI messages.
        :param number: 0 unless you've got more than one FaderPort attached.
                       In which case 0 is the first, 1 is the second etc
                       I only have access to a single device so I can't
                       actually test this.
        """
        self.inport = mido.open_input(find_faderport_input_name(number))
        self.outport = mido.open_output(find_faderport_output_name(number))
        #self.outport.send(mido.Message.from_bytes([0x91, 0, 0x64]))  # A reset message???
        time.sleep(0.01)
        self.inport.callback = self._message_callback
        self.on_open()

    def close(self):
        self.on_close()
        self.inport.callback = None
        self.fader = -8192
        self.all_off()
        self.outport.reset()
        self.inport.close()
        self.outport.close()

    @abstractmethod
    def on_open(self):
        """Called after the FaderPort has been opened."""
        pass

    @abstractmethod
    def on_close(self):
        """Called when the FaderPort is closing."""
        pass

    def _message_callback(self, msg):
        """Callback function to handle incoming MIDI messages."""
        # DEBUG
        #print('Message:', msg)

        # FADER
        if msg.type == 'pitchwheel':
            self._fader = msg.pitch
            self.on_fader(self._fader)

        # BUTTONS
        elif msg.type == 'note_on':
            # FADER TOUCH
            if msg.note == 104:
                self.on_fader_touch(msg.velocity != 0)
            else:
                button = button_from_press(msg.note)
                if button:
                    self.on_button(button, msg.velocity != 0)
                else:
                    print('Button not found:', msg.note)

        # KNOB
        elif msg.type == 'control_change' and msg.control == 16:
            self.on_rotary(-1 if msg.value > 64 else 1)  # TODO: handle multiple clicks

        else:
            print('Unhandled:', msg)

    @abstractmethod
    def on_rotary(self, direction: int):
        """
        Called when the FaderPort "Pan" control is changed.
        :param direction:  1 if clockwise, -1 if anti-clockwise
        """
        pass

    @abstractmethod
    def on_button(self, button: Button, state: bool):
        """
        Called when a FaderPort button is pressed and released.
        :param button: The Button in question
        :param state:  True if pressed, False when released.
        """
        pass

    @abstractmethod
    def on_fader_touch(self, state: bool):
        """
        Called when the fader is touched and when it is released.
        :param state: True if touched, False when released.
        """
        pass

    @abstractmethod
    def on_fader(self, value: int):
        """
        Called when the Fader has been moved.
        :param value: The new fader value.
        """
        pass

    @property
    def fader(self) -> int:
        """"Returns the position of the Fader in the range 0-1023"""
        return self._fader

    @fader.setter
    def fader(self, value: int):
        """Move the fader to a new position in the range 0 to 1023."""

        self._fader = -8192 if value < -8192 else 8191 if value > 8191 else value
        self.outport.send(mido.Message('pitchwheel',
                                       pitch=self._fader))

    def light_on(self, button: Button):
        """Turn the light on for the given Button.

        NOTE! If you turn the "Off" button light on, the fader won't
        report value updates when it's moved."""
        self.outport.send(mido.Message('note_on', note=button.press, velocity=127))

    def light_off(self, button: Button):
        """Turn the light off for the given Button"""
        self.outport.send(mido.Message('note_on', note=button.press, velocity=0))

    def all_off(self):
        """Turn all the button lights off."""
        for button in BUTTONS:
            self.light_off(button)

    def all_on(self):
        """Turn all the button lights on.

        NOTE! The fader will not report value changes while the "Off"
        button is lit."""
        for button in BUTTONS:
            self.light_on(button)

    def snake(self, duration: float = 0.03):
        """
        Turn the button lights on then off in a snakelike sequence.
        NOTE! Does not remember prior state of lights and will finish
        with all lights off.
        :param duration: The duration to hold each individual button.
        """
        for button in BUTTONS:
            self.light_on(button)
            time.sleep(duration)

        for button in reversed(BUTTONS):
            self.light_off(button)
            time.sleep(duration)

    def blink(self, interval: float = 0.2, n: int = 3):
        """
        Blink all the lights on and off at once.
        NOTE! Does not remember prior state of lights and will finish
        with all lights off.
        :param interval: The length in seconds of an ON/OFF cycle
        :param n: How many times to cycle ON and OFF
        :return:
        """
        for i in range(n):
            self.all_on()
            time.sleep(interval / 2)
            self.all_off()
            time.sleep(interval / 2)

    def char_on(self, c):
        """
        Use button lights (as matrix) to display a hex character.
        :param c: String containing one of 0-9,A-F
        """
        if c.upper() in CHARACTERS:
            for i in CHARACTERS[c.upper()]:
                self.light_on(BUTTONS[i])

    def countdown(self, interval: float = 0.5):
        """
        Display a numeric countdown from 5
        :param interval: The interval in seconds for each number.
        """
        for c in '9876543210':
            self.char_on(c)
            time.sleep(interval * 0.66667)
            self.all_off()
            time.sleep(interval * 0.33333)

    def chase(self, duration: float = 0.08, num_lights: int = 2, ticks: int = 20):
        """
        Display an animated light chaser pattern
        Chase will last ticks * duration seconds
        :param duration: How long each chase step will last in seconds
        :param num_lights: How many lights in the chase (1 to 4)
        :param ticks: How many chase steps.
        """
        seq = [
            button_from_name('Solo'),
            button_from_name('Mute'),
            button_from_name('Arm'),
            button_from_name('Shift'),
            button_from_name('Read'),
            button_from_name('Scroll'),
            button_from_name('Marker'),
            button_from_name('Section'),
            button_from_name('Click'),
            button_from_name('Master'),
            button_from_name('Link'),
            button_from_name('Bypass'),
        ]

        num_lights = num_lights if num_lights in [1, 2, 3, 4] else 2

        its = [cycle(seq) for _ in range(num_lights)]
        for i, it in enumerate(its):
            if i:
                consume(it, i * (len(seq) // num_lights))

        for x in range(ticks):
            for it in its:
                button = next(it)
                self.light_on(button)
            time.sleep(duration)
            self.all_off()


def find_faderport_input_name(number=0):
    """
    Find the MIDI input name for a connected FaderPort.

    NOTE! Untested for more than one FaderPort attached.
    :param number: 0 unless you've got more than one FaderPort attached.
                   In which case 0 is the first, 1 is the second etc
    :return: Port name or None
    """
    ins = [i for i in mido.get_input_names() if i.lower().startswith('presonus fp2')]
    if 0 <= number < len(ins):
        return ins[number]
    else:
        return None


def find_faderport_output_name(number=0):
    """
    Find the MIDI output name for a connected FaderPort.

    NOTE! Untested for more than one FaderPort attached.
    :param number: 0 unless you've got more than one FaderPort attached.
                   In which case 0 is the first, 1 is the second etc
    :return: Port name or None
    """
    outs = [i for i in mido.get_output_names() if i.lower().startswith('presonus fp2')]
    if 0 <= number < len(outs):
        return outs[number]
    else:
        return None


class TestFaderPort(FaderPort):
    """
    A class for testing the FaderPort functionality and demonstrating
    some of the possibilities.
    """

    def __init__(self):
        super().__init__()
        self._shift = False
        self.cycling = False
        self.should_exit = False

    @property
    def shift(self):
        return self._shift

    def on_open(self):
        print('FaderPort opened!!')

    def on_close(self):
        print('FaderPort closing...')

    def on_rotary(self, direction):
        print(f"Pan turned {'clockwise' if direction > 0 else 'anti-clockwise'}.")
        if self.shift:
            self.fader += direction * 32 * 10

    def on_button(self, button, state):
        print(f"Button: {button.name} {'pressed' if state else 'released'}")
        if button.name == 'Shift':
            self._shift = not self._shift
        if button.name == 'Mute' and not state:
            self.should_exit = True
        if not self.cycling:
            if state:
                self.light_on(button)
            else:
                self.light_off(button)

    def on_fader_touch(self, state):
        print(f"Fader: {'touched' if state else 'released'}")

    def on_fader(self, value):
        print(f"Fader: {self.fader}")


def consume(iterator, n):  # Copied consume From the itertool docs
    """Advance the iterator n-steps ahead. If n is none, consume entirely."""
    # Use functions that consume iterators at C speed.
    if n is None:
        # feed the entire iterator into a zero-length deque
        collections.deque(iterator, maxlen=0)
    else:
        # advance to the empty slice starting at position n
        next(islice(iterator, n, n), None)


def test():
    with TestFaderPort() as f:
        f.countdown()
        f.fader = 8191
        f.snake()
        f.fader = 4095
        f.blink()
        f.fader = -4096
        f.chase(num_lights=3)
        f.fader = -8192
        print('Try the buttons, the rotary and the fader. The "Mute" '
              'button will exit.')
        while not f.should_exit:
            time.sleep(1)


if __name__ == '__main__':
    test()
