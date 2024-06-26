import argparse
import traceback
from datetime import datetime
from pprint import pformat, pprint
from time import sleep
from typing import Any, Dict

import requests
from PyTado.interface import Tado

MAX_RETRIES = 3


def send_healthcheck_ping(
    success: bool = True,
    payload: dict = {},
    retries: int = 0,
) -> None:
    if retries < MAX_RETRIES:
        if success:
            try:
                requests.get(args.healthcheck)
            except Exception:
                retries = retries + 1
                print(
                    f"An error occurred while pinging healthcheck - retrying ({retries}/{MAX_RETRIES})..."
                )
                sleep(0.1)
                send_healthcheck_ping(
                    success=success,
                    payload=payload,
                    retries=retries,
                )
        else:
            try:
                requests.post(
                    url=f"{args.healthcheck}/fail",
                    json=payload,
                )
            except Exception:
                retries = retries + 1
                print(
                    f"An error occurred while pinging healthcheck. - retrying ({retries}/{MAX_RETRIES})..."
                )
                sleep(0.1)
                send_healthcheck_ping(
                    success=success,
                    payload=payload,
                    retries=retries,
                )
    else:
        print("Max retries exceeded. Skipping healthcheck ping.")


arg_parser = argparse.ArgumentParser()

arg_parser.add_argument("-u", "--username", help="Your Tado username (normally your email address)")
arg_parser.add_argument("-p", "--password", help="Your Tado password")
arg_parser.add_argument(
    "--healthcheck", help="The healthcheck URL used to send heartbeat HTTP requests."
)

args = arg_parser.parse_args()

t = Tado(args.username, args.password)

mobile_devices = None
home_state = None
devices = None
zones = None

devices = t.get_devices()
zones = t.get_zones()

previous_device_states: Dict[str, Any] = {}

while True:
    try:
        mobile_devices = t.get_mobile_devices()
        home_state = t.get_home_state()

        datetime_now = datetime.now().isoformat()

        print(f"\n===== {datetime_now} ({home_state['presence']}) =====")

        is_home = False
        current_home_state = home_state["presence"]
        with open("log.txt", "a+") as log_file:
            for device in mobile_devices:
                try:
                    device_id = device["id"]
                    tracking_enabled = device["settings"]["geoTrackingEnabled"]
                    at_home = device["location"]["atHome"] if tracking_enabled else False
                    location_stale = device["location"]["stale"] if tracking_enabled else False

                    # Print device status, and set is_home if device is at home.
                    if all([at_home, tracking_enabled, not location_stale]):
                        is_home = True
                        print(f"Device '{device['name']}' at home.")
                    elif not tracking_enabled:
                        print(f"Device '{device['name']}' has tracking disabled.")
                    elif location_stale:
                        print(f"Device '{device['name']}' has a stale location.")
                    else:
                        print(f"Device '{device['name']}' is NOT at home.")

                    # Log to file if device location has changed from last check
                    if (
                        device_id in previous_device_states.keys()
                        and device["settings"]["geoTrackingEnabled"]
                    ):
                        if (
                            device["location"]["atHome"]
                            != previous_device_states[device_id]["location"]["atHome"]
                        ):
                            previous_location = (
                                "HOME"
                                if previous_device_states[device_id]["location"]["atHome"]
                                else "AWAY"
                            )
                            current_location = "HOME" if device["location"]["atHome"] else "AWAY"

                            log_file.write(
                                f"{datetime_now}: '{device['name']}' went from {previous_location} to {current_location}.\n"
                            )

                    # Update previous device state
                    previous_device_states[device_id] = device

                    # Ping healthcheck endpoint
                    send_healthcheck_ping(success=True)
                except KeyError as err:
                    print("Error while getting location of device. Device info:")
                    pprint(device)
                    print(f"\nError: {err}")
                    log_file.write(
                        f"{datetime_now}: An error occurred while getting the location of a device.\n\tDevice info: {device}\n\tError: {err}\n\n"
                    )
                    send_healthcheck_ping(
                        success=False,
                        payload=dict(
                            home_state=home_state if home_state else None,
                            devices=devices if devices else None,
                            exception_name=type(err).__name__,
                            mobile_devices=mobile_devices if mobile_devices else None,
                            previous_device_states=previous_device_states
                            if previous_device_states
                            else None,
                            stacktrace=traceback.format_exc(),
                            zones=zones if zones else None,
                        ),
                    )

            if is_home and current_home_state == "AWAY":
                t.set_home()
                print("Setting status to HOME.")
                log_file.write(f"{datetime_now}: Status changed to HOME.\n")
            elif not is_home and current_home_state == "HOME":
                t.set_away()
                print("Setting status to AWAY.")
                log_file.write(f"{datetime_now}: Status changed to AWAY.\n")

        print("=============================================")
    except Exception as err:
        send_healthcheck_ping(
            success=False,
            payload=dict(
                devices=devices if devices else None,
                exception_name=type(err).__name__,
                previous_device_states=previous_device_states if previous_device_states else None,
                stacktrace=traceback.format_exc(),
                zones=zones if zones else None,
            ),
        )
        with open("log.txt", "a+") as log_file:
            log_file.write(f"ERROR LOG: {traceback.format_exc()}")
        body = f"""An exception occurred in the Tado app on your Raspberry Pi. Check the logs for more details.

Exception: {err}

Mobile devices:
{pformat(mobile_devices)}

Home state:
{pformat(home_state)}
"""
    sleep(30)
