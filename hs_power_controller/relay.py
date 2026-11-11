import logging
import threading
import time

from . import config

log = logging.getLogger("hs-power-controller.relay")

_lock = threading.Lock()
_gpio = None

def _init():
    global _gpio
    if _gpio is None:
        import RPi.GPIO as GPIO
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(config.RELAY_PIN, GPIO.OUT, initial=GPIO.LOW)
        _gpio = GPIO

def press(seconds: float) -> None:
    with _lock: #session lock
        if config.DRY_RUN:
            log.info("[DRY RUN] Reails an GPIO %s für $.1f s gedrückt.", config.RELAY_PIN, seconds)
            return
        _init()
        try:
            _gpio.output(config.RELAY_PIN, _gpio.HIGH)
            time.sleep(seconds)
        finally:
            _gpio.output(config.RELAY_PIN, _gpio.LOW) # ALWAYS release