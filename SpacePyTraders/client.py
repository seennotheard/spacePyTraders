from asyncio.format_helpers import extract_stack
import requests
import logging
import time
from SpacePyTraders import models
from dataclasses import dataclass, field
import warnings
from ratelimit import limits, sleep_and_retry
import json

URL = "https://api.spacetraders.io/"
V2_URL = "https://api.spacetraders.io/v2/"
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(thread)d - %(message)s', level=logging.INFO)


# Custom Exceptions
# ------------------------------------------
@dataclass
class ThrottleException(Exception):
    data: field(default_factory=dict)
    message: str = "Throttle limit was reached. Pausing to wait for throttle"


@dataclass
class ServerException(Exception):
    data: field(default_factory=dict)
    message: str = "Server Error. Pausing before trying again"


@dataclass
class TooManyTriesException(Exception):
    message: str = "Has failed too many times to make API call. "


@sleep_and_retry
@limits(calls=2, period=1.2)
def make_request(method, url, headers, params):
    """Checks which method to use and then makes the actual request to Space Traders API

    Parameters:
        method (str): The HTTP method to use
        url (str): The URL of the request
        headers (dict): the request headers holding the Auth
        params (dict): parameters of the request

    Returns:
        Request: Returns the request

    Exceptions:
        Exception: Invalid method - must be GET, POST, PUT or DELETE
    """
    # Convert params into proper JSON data
    # params = None if params is None else json.dumps(params)
    # Define the different HTTP methods
    if method == "GET":
        return requests.get(url, headers=headers, params=params)
    elif method == "POST":
        return requests.post(url, headers=headers, json=params)
    elif method == "PUT":
        return requests.put(url, headers=headers, data=params)
    elif method == "DELETE":
        return requests.delete(url, headers=headers, data=params)
    elif method == "PATCH":
        return requests.patch(url, headers=headers, json=params)

    # If an Invalid method provided throw exception
    if method not in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
        logging.exception(f'Invalid method provided: {method}')


@dataclass
class Client:
    def __init__(self, username=None, token=None):
        """The Client class handles all user interaction with the Space Traders API. 
        The class is initiated with the username and token of the user. 
        If the user does not provide a token the 'create_user' method will attempt to fire and create a user with the username provided. 
        If a user with the name already exists an exception will fire. 

        Parameters:
            username (str): Username of the user
            token (str): The personal auth token for the user. If None will invoke the 'create_user' method
        """
        self.username = username
        self.token = token
        self.url = V2_URL

    def generic_api_call(self, method, endpoint, params=None, token=None, warning_log=None, raw_res=False,
                         throttle_time=10):
        """Function to make consolidate parameters to make an API call to the Space Traders API. 
        Handles any throttling or error returned by the Space Traders API. 

        Parameters:
            method (str): The HTTP method to use. GET, POST, PUT or DELETE
            endpoint (str): The API endpoint
            params (dict, optional): Any params required for the endpoint. Defaults to None.
            token (str, optional): The token of the user. Defaults to None.
            raw_res (bool, default = False): Returns the request response's JSON by default. Can be set to True to return the request response.
            throttle_time (int, default = 10): Sets how long the wait time before attempting call again. Default is 10 seconds

        Returns:
            Any: depends on the return from the API but likely JSON
        """
        headers = {
            'Authorization': 'Bearer ' + token,
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        # Make the request to the Space Traders API
        for i in range(10):
            try:
                r = make_request(method=method, url=self.url + endpoint, headers=headers, params=params)
                if r.status_code == 204:
                    return None
                # If an error returned from api 
                if 'error' in r.json():
                    error = r.json()
                    code = error['error']['code']
                    message = error['error']['message']
                    logging.warning(
                        f"An error has occurred when hitting: {r.request.method} {r.url} with parameters: {params}. Error: " + str(
                            error))

                    # If throttling error
                    if code == 42901:
                        raise ThrottleException(error)

                    # Retry if server error
                    if code == 500 or code == 409:
                        raise ServerException(error)

                    # Unknown handling for error
                    logging.warning(warning_log)
                    logging.exception(f"Something broke the script. Code: {code} Error Message: {message} ")
                    return False
                # If successful return r
                if raw_res:
                    return r
                else:
                    return r.json()

            except ThrottleException as te:
                logging.info(te.message)
                time.sleep(throttle_time)
                continue

            except ServerException as se:
                logging.info(se.message)
                time.sleep(throttle_time)
                continue

            except Exception as e:
                return e

        # If failed to make call after 10 tries fail it
        raise TooManyTriesException


class Fleet(Client):
    def list_ships(self, limit=10, page=1, raw_res=False, throttle_time=10):
        """Return a paginated list of all ships under your agent's ownership.

        https://spacetraders.stoplight.io/docs/spacetraders/64435cafd9005-list-ships

        Parameters:
            limit (int, optional): How many entries to return per page. Defaults to 10.
            page (int, optional): What entry offset to request. Defaults to 1.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: A JSON list of the ships you own.
        """
        endpoint = f"my/ships"
        querystring = {"page": page, "limit": limit}
        warning_log = f"Unable to get list of owned ships."
        logging.info(f"Getting a list of owned ships")
        res = self.generic_api_call("GET", endpoint, params=querystring, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def purchase_ship(self, ship_type, waypoint_symbol, raw_res=False, throttle_time=10):
        """Purchase a ship from a Shipyard. In order to use this function, a ship under your agent's ownership must
        be in a waypoint that has the Shipyard trait, and the Shipyard must sell the type of the desired ship.

        https://spacetraders.stoplight.io/docs/spacetraders/403855e2e99ad-purchase-ship

        Parameters:
            ship_type (str): Type of ship
            waypoint_symbol: The flight_mode of the waypoint you want to purchase the ship at.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships"
        params = {"waypointSymbol": waypoint_symbol, "shipType": ship_type}
        warning_log = f"Unable to buy ship type: {ship_type}, at waypoint: {waypoint_symbol}."
        logging.debug(f"Buying ship of type: {ship_type} at waypoint: {waypoint_symbol}")
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log)
        return res if res else False

    def purchase_ship2(self, ship_type, waypoint_symbol, raw_res=False, throttle_time=10):
        """Purchase a ship from a Shipyard. In order to use this function, a ship under your agent's ownership must
        be in a waypoint that has the Shipyard trait, and the Shipyard must sell the type of the desired ship.

        https://spacetraders.stoplight.io/docs/spacetraders/403855e2e99ad-purchase-ship

        Parameters:
            ship_type (str): Type of ship
            waypoint_symbol: The flight_mode of the waypoint you want to purchase the ship at.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships"
        params = {"waypointSymbol": waypoint_symbol, "shipType": ship_type}
        warning_log = f"Unable to buy ship type: {ship_type}, at waypoint: {waypoint_symbol}."
        logging.debug(f"Buying ship of type: {ship_type} at waypoint: {waypoint_symbol}")
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log)
        return res if res else False

    def get_ship(self, ship_symbol, raw_res=False, throttle_time=10):
        """Retrieve the details of a ship under your agent's ownership.

        https://spacetraders.stoplight.io/docs/spacetraders/800936299c838-get-ship

        Parameters:
            ship_symbol (str): The flight_mode of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}"
        warning_log = f"Unable to get info on ship: {ship_symbol}"
        logging.info(f"Getting info on ship: {ship_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def get_ship_cargo(self, ship_symbol, raw_res=False, throttle_time=10):
        """Retrieve the cargo of a ship under your agent's ownership.

        https://spacetraders.stoplight.io/docs/spacetraders/1324f523e2c9c-get-ship-cargo

        Parameters:
            ship_symbol (str): The flight_mode of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/cargo"
        warning_log = f"Unable to get info on ship cargo: {ship_symbol}"
        logging.info(f"Getting info on ship cargo: {ship_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def orbit_ship(self, ship_symbol, raw_res=False, throttle_time=10):
        """Attempt to move your ship into orbit at its current location. The request will only succeed if your ship
        is capable of moving into orbit at the time of the request.

        https://spacetraders.stoplight.io/docs/spacetraders/08777d60b6197-orbit-ship

        Parameters:
            ship_symbol (str): The flight_mode of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/orbit"
        warning_log = f"Unable to orbit ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def ship_refine(self, ship_symbol, produce, raw_res=False, throttle_time=10):
        """Attempt to refine the raw materials on your ship. The request will only succeed if your ship is capable of
        refining at the time of the request.

        https://spacetraders.stoplight.io/docs/spacetraders/c42b57743a49f-ship-refine

        Parameters:
            ship_symbol (str): The flight_mode of the ship.
            produce (str): The type of trade_symbol to flight_mode out of the refining process.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/refine"
        params = {"flight_mode": produce}
        warning_log = f"Unable to flight_mode on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def create_chart(self, ship_symbol, raw_res=False, throttle_time=10):
        """Command a ship to chart the waypoint at its current location.

        https://spacetraders.stoplight.io/docs/spacetraders/177f127c7f888-create-chart

        Parameters:
            ship_symbol (str): The flight_mode of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/chart"
        warning_log = f"Unable to chart on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def get_ship_cooldown(self, ship_symbol, raw_res=False, throttle_time=10):
        """Retrieve the details of your ship's reactor cooldown. Some actions such as activating your jump drive,
        scanning, or extracting resources taxes your reactor and results in a cooldown.

        https://spacetraders.stoplight.io/docs/spacetraders/d20ef14bc0742-get-ship-cooldown

        Parameters:
            ship_symbol (str): The flight_mode of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/cooldown"
        warning_log = f"Unable to get ship cooldown: {ship_symbol}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def dock_ship(self, ship_symbol, raw_res=False, throttle_time=10):
        """Attempt to dock your ship at its current location. Docking will only succeed if your ship is capable of
        docking at the time of the request.

        https://spacetraders.stoplight.io/docs/spacetraders/a1061ae6545d5-dock-ship

        Parameters:
            ship_symbol (str): The flight_mode of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/dock"
        warning_log = f"Unable to dock ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def create_survey(self, ship_symbol, raw_res=False, throttle_time=10):
        """Create surveys on a waypoint that can be extracted such as asteroid fields. A survey focuses on specific
        types of deposits from the extracted location. When ships extract using this survey, they are guaranteed to
        procure a high amount of one of the goods in the survey.

        https://spacetraders.stoplight.io/docs/spacetraders/6b7cb030c3b91-create-survey

        Parameters:
            ship_symbol (str): The flight_mode of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/survey"
        warning_log = f"Unable to survey on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def extract_resources(self, ship_symbol, raw_res=False, throttle_time=10):
        """Extract resources from a waypoint that can be extracted, such as asteroid fields, into your ship. Send an
        optional survey as the payload to target specific yields.

        https://spacetraders.stoplight.io/docs/spacetraders/b3931d097608d-extract-resources

        Parameters:
            ship_symbol (str): The flight_mode of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/extract"
        warning_log = f"Unable to extract on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def siphon_resources(self, ship_symbol, raw_res=False, throttle_time=10):
        """Siphon gases, such as hydrocarbon, from gas giants.

        https://spacetraders.stoplight.io/docs/spacetraders/f6c0d7877c43a-siphon-resources

        Parameters:
            ship_symbol (str): The flight_mode of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/siphon"
        warning_log = f"Unable to siphon on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def extract_resources_with_survey(self, ship_symbol, survey: models.Survey, raw_res=False, throttle_time=10):
        """Use a survey when extracting resources from a waypoint.

        https://spacetraders.stoplight.io/docs/spacetraders/cdf110a7af0ea-extract-resources-with-survey

        Parameters:
            ship_symbol (str): The flight_mode of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/extract/survey"
        warning_log = f"Unable to extract with survey on ship: {ship_symbol}"
        params = models.unpack(survey)
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def jettison_cargo(self, ship_symbol, symbol, units, raw_res=False, throttle_time=10):
        """Jettison cargo from your ship's cargo hold.

        https://spacetraders.stoplight.io/docs/spacetraders/3b0f8b69f56ac-jettison-cargo

        Response Example:
        {
            "data": {
                "cargo": {
                    "capacity": 0,
                    "units": 0,
                    "inventory": [
                        {
                            "flight_mode": "PRECIOUS_STONES",
                            "name": "string",
                            "description": "string",
                            "units": 1
                        }
                    ]
                }
            }
        }

        Parameters:
            ship_symbol (str): The ship flight_mode.
            symbol (str): The trade_symbol's flight_mode.
            units (int): Amount of units to jettison of this trade_symbol.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/jettison"
        warning_log = (
            f"Unable to jettison cargo from ship. Params - ship_symbol: {ship_symbol}, flight_mode: {symbol}, "
            f"units: {units}")
        logging.info(
            f"Jettison the following cargo from ship: {ship_symbol}, flight_mode: {symbol}, units: {units}")
        params = {"symbol": symbol, "units": units}
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def jump_ship(self, ship_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """Jump your ship instantly to a target connected waypoint. The ship must be in orbit to execute a jump.

        https://spacetraders.stoplight.io/docs/spacetraders/19f0dd2d633de-jump-ship

        Parameters:
            ship_symbol (str): The flight_mode of the ship.
            waypoint_symbol (str): The flight_mode of the waypoint to jump to. The destination must be a connected waypoint.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/jump"
        params = {"waypointSymbol": waypoint_symbol}
        warning_log = f"Unable to flight_mode on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def navigate_ship(self, ship_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """Navigate to a target destination. The ship must be in orbit to use this function. The destination waypoint
        must be within the same system as the ship's current location. Navigating will consume the necessary fuel
        from the ship's manifest based on the distance to the target waypoint.

        https://spacetraders.stoplight.io/docs/spacetraders/c766b84253edc-navigate-ship

        Parameters:
            ship_symbol (str): The flight_mode of the ship.
            waypoint_symbol (str): The target destination.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/navigate"
        params = {"waypointSymbol": waypoint_symbol}
        warning_log = f"Unable to flight_mode on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def patch_ship_nav(self, ship_symbol, flight_mode, raw_res=False, throttle_time=10):
        """Update the nav configuration of a ship.

        https://spacetraders.stoplight.io/docs/spacetraders/34a305032ec79-patch-ship-nav

        Parameters:
            ship_symbol (str): The waypoint_symbol of the ship.
            flight_mode (str): The ship's set speed when traveling between waypoints or systems.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/nav"
        params = {"flightMode": flight_mode}
        warning_log = f"Unable to change flight mode on ship: {ship_symbol}"
        res = self.generic_api_call("PATCH", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def get_ship_nav(self, ship_symbol, raw_res=False, throttle_time=10):
        """Get the current nav status of a ship.

        https://spacetraders.stoplight.io/docs/spacetraders/6e80adc7cc4f5-get-ship-nav

        Parameters:
            ship_symbol (str): The flight_mode of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/nav"
        warning_log = f"Unable to get nav on ship: {ship_symbol}"
        logging.info(f"Getting nav on ship: {ship_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def warp_ship(self, ship_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """Warp your ship to a target destination in another system.

        https://spacetraders.stoplight.io/docs/spacetraders/faaf6603fc732-warp-ship

        Parameters:
            ship_symbol (str): The ship symbol.
            waypoint_symbol (str): The target destination.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/warp"
        warning_log = f"Unable to warp ship {ship_symbol} to flight_mode: {waypoint_symbol}"
        logging.info(f"Warping ship {ship_symbol} to flight_mode: {waypoint_symbol}")
        params = {"flight_mode": waypoint_symbol}
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def sell_cargo(self, ship_symbol, symbol, units, raw_res=False, throttle_time=10):
        """Sell cargo in your ship to a market that trades this cargo.

        https://spacetraders.stoplight.io/docs/spacetraders/b8ed791381b41-sell-cargo

        Parameters:00
            ship_symbol (str): The ship flight_mode.
            symbol (str): The good's flight_mode.
            units (int): Amount of units to sell of this trade_symbol.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/sell"
        warning_log = (
            f"Unable to sell cargo from ship. Params - ship_symbol: {ship_symbol}, flight_mode: {symbol}, "
            f"units: {units}")
        logging.info(f"Sell the following cargo from ship: {ship_symbol}, flight_mode: {symbol}, units: {units}")
        params = {"flight_mode": symbol, "units": units}
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def scan_systems(self, ship_symbol, raw_res=False, throttle_time=10):
        """Scan for nearby systems, retrieving information on the systems' distance from the ship and their waypoints.

        https://spacetraders.stoplight.io/docs/spacetraders/d3358a9202901-scan-systems

        Parameters:
            ship_symbol (str): The ship flight_mode.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/scan/systems"
        warning_log = f"Failed to scan systems with ship ({ship_symbol})."
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res

    def scan_waypoints(self, ship_symbol, raw_res=False, throttle_time=10):
        """Scan for nearby waypoints, retrieving detailed information on each waypoint in range.

        https://spacetraders.stoplight.io/docs/spacetraders/23dbc0fed17ec-scan-waypoints

        Parameters:
            ship_symbol (str): The ship flight_mode.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/scan/waypoints"
        warning_log = f"Failed to scan waypoints with ship ({ship_symbol})."
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res

    def scan_ships(self, ship_symbol, raw_res=False, throttle_time=10):
        """Scan for nearby ships, retrieving information for all ships in range.

        https://spacetraders.stoplight.io/docs/spacetraders/74da68b7c32a7-scan-ships

        Parameters:
            ship_symbol (str): The ship flight_mode.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/scan/ships"
        warning_log = f"Failed to scan ships with ship ({ship_symbol})."
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res

    def refuel_ship(self, ship_symbol, units, from_cargo=False, raw_res=False, throttle_time=10):
        """Refuel your ship by buying fuel from the local market.

        Parameters:
            ship_symbol (str): The ship flight_mode.
            units: The amount of fuel to fill in the ship's tanks.
            from_cargo (bool): Whether to use the FUEL that's in your cargo or not. Default: false

        """
        endpoint = f"my/ships/{ship_symbol}/refuel"
        warning_log = f"Failed to refuel ship ({ship_symbol})."
        params = {"units": units, "fromCargo": from_cargo}
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res

    def purchase_cargo(self, ship_symbol, symbol, units, raw_res=False, throttle_time=10):
        """Purchase cargo from a market.

        https://spacetraders.stoplight.io/docs/spacetraders/45acbf7dc3005-purchase-cargo

        Parameters:
            ship_symbol (str): The ship flight_mode.
            symbol (str): The good's flight_mode.
            units (int): Amount of units to sell of this trade_symbol.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/purchase"
        warning_log = (
            f"Unable to buy cargo from ship. Params - ship_symbol: {ship_symbol}, flight_mode: {symbol}, "
            f"units: {units}")
        logging.info(f"Buy the following cargo from ship: {ship_symbol}, flight_mode: {symbol}, units: {units}")
        params = {"flight_mode": symbol, "units": units}
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    # Scrap Ship
    def scrap_ship(self, shipId, raw_res=False, throttle_time=10):
        """Scraps the ship_symbol for a small amount of credits.
        Ships need to be scraped at a location with a Shipyard.
        Known Shipyards:
        - OE-PM-TR

        Parameters:
            shipId (str): ID of the ship to scrap

        Returns:
            bool: True if the ship was scrapped

        Raises:
            Exception: If something went wrong during the scrapping process
        """
        endpoint = f"my/ships/{shipId}/"
        warning_log = f"Failed to scrap ship ({shipId})."
        logging.info(f"Scrapping ship: {shipId}")
        res = self.generic_api_call("DELETE", endpoint, token=self.token, warning_log=warning_log)
        return res

    # Transfer Cargo
    def transfer_cargo(self, origin_ship_symbol, trade_symbol, dest_ship_symbol, units, raw_res=False,
                       throttle_time=10):
        """Transfer cargo between ships.

        Parameters:
            origin_ship_symbol (str): The transferring ship's flight_mode.
            trade_symbol (str): The good's flight_mode.
            units (int): Amount of units to transfer.
            dest_ship_symbol (str): The flight_mode of the ship to transfer to.

        Returns:
            dict: A dict is returned with two keys "fromShip" & "toShip" each with the updated ship info for the respective ships
        """
        endpoint = f"my/ships/{origin_ship_symbol}/transfer"
        warning_log = f"Unable to transfer {units} units of {trade_symbol} from ship: {origin_ship_symbol} to ship: {dest_ship_symbol}"
        logging.info(
            f"Transferring {units} units of {trade_symbol} from ship: {origin_ship_symbol} to ship: {dest_ship_symbol}")
        params = {"flight_mode": trade_symbol, "units": units, "dest_ship_symbol": dest_ship_symbol}
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def negotiate_contract(self, ship_symbol, raw_res=False, throttle_time=10):
        """Negotiate a new contract with the HQ.

        https://spacetraders.stoplight.io/docs/spacetraders/1582bafa95003-negotiate-contract

        Parameters:
            ship_symbol (str): The ship's symbol.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/negotiate/contract"
        warning_log = f"Unable to negotiate contract"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def get_mounts(self, ship_symbol, raw_res=False, throttle_time=10):
        """Get the mounts installed on a ship.

        https://spacetraders.stoplight.io/docs/spacetraders/23ab20baf0ea8-get-mounts

        Parameters:
            ship_symbol (str): The flight_mode of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/mounts"
        warning_log = f"Unable to get mounts on ship: {ship_symbol}"
        logging.info(f"Getting mounts on ship: {ship_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def install_mount(self, ship_symbol, symbol, raw_res=False, throttle_time=10):
        """Install a mount on a ship.

        https://spacetraders.stoplight.io/docs/spacetraders/266f3d0591399-install-mount

        Parameters:
            ship_symbol (str): The ship's symbol.
            symbol (str): The symbol of the mount to install.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/mounts/install"
        params = {"symbol": symbol}
        warning_log = f"Unable to install mount on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def remove_mount(self, ship_symbol, symbol, raw_res=False, throttle_time=10):
        """Remove a mount from a ship.

        https://spacetraders.stoplight.io/docs/spacetraders/9380132527c1d-remove-mount

        Parameters:
            ship_symbol (str): The ship's symbol.
            symbol (str): The symbol of the mount to remove.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/mounts/remove"
        params = {"symbol": symbol}
        warning_log = f"Unable to install mount on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False


class Systems(Client):
    # Get system info
    def list_systems(self, limit=10, page=1, raw_res=False, throttle_time=10):
        """Return a paginated list of all systems.

        https://spacetraders.stoplight.io/docs/spacetraders/94269411483d0-list-systems

        Parameters:
            limit (int, optional): How many entries to return per page. Defaults to 10.
            page (int, optional): What entry offset to request. Defaults to 1.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"systems"
        querystring = {"page": page, "limit": limit}
        warning_log = f"Unable to list agents"
        res = self.generic_api_call("GET", endpoint, params=querystring, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def get_system(self, symbol, raw_res=False, throttle_time=10):
        """Get info on the definined system

        Parameters:
            symbol (str): The flight_mode for the system eg: OE

        Returns:
            dict: A dict with info about the system
        """
        endpoint = f"systems/{symbol}"
        warning_log = f"Unable to get the  system: {symbol}"
        logging.info(f"Getting the system: {symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log)
        return res if res else False

    def list_waypoints_in_system(self, system_symbol, limit=10, page=1, traits=None, type=None, raw_res=False, throttle_time=10):
        """Return a paginated list of all the waypoints for a given system.

        Parameters:
            system_symbol (str): The system symbol
            limit (int): How many entries to return per page
            page (int): What entry offset to request
            traits (str |  list[str]):

        Returns:
            dict: A dict containing a JSON list of the locations in the system
        """
        endpoint = f"systems/{system_symbol}/waypoints"
        warning_log = f"Unable to get the locations in the system: {system_symbol}"
        logging.info(f"Getting the locations in system: {system_symbol}")
        querystring = {"limit": limit, "page": page}
        if not traits is None:
            querystring["traits"] = traits
        if not type is None:
            querystring["type"] = type
        res = self.generic_api_call("GET", endpoint, params=querystring, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def get_waypoint(self, system_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """View the details of a waypoint.

        Parameters:
            system_symbol (str): The system symbol
            waypoint_symbol (str): The waypoint symbol
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"systems/{system_symbol}/waypoints/{waypoint_symbol}"
        warning_log = f"Unable to get details of waypoint: {waypoint_symbol}"
        logging.info(f"Fetching details of waypoint: {waypoint_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def get_market(self, system_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """Retrieve imports, exports and exchange data from a marketplace.

        Parameters:
            system_symbol (str): The system symbol
            waypoint_symbol (str): The waypoint symbol
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"systems/{system_symbol}/waypoints/{waypoint_symbol}/market"
        warning_log = f"Unable to get details of market: {waypoint_symbol}"
        logging.info(f"Fetching details of market: {waypoint_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def get_shipyard(self, system_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """Get the shipyard for a waypoint.

        Parameters:
            system_symbol (str): The system symbol
            waypoint_symbol (str): The waypoint symbol
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"systems/{system_symbol}/waypoints/{waypoint_symbol}/shipyard"
        warning_log = f"Unable to get details of shipyard: {waypoint_symbol}"
        logging.info(f"Fetching details of shipyard: {waypoint_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def get_jump_gate(self, system_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """Get jump gate details for a waypoint.

        Parameters:
            system_symbol (str): The system symbol
            waypoint_symbol (str): The waypoint symbol
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"systems/{system_symbol}/waypoints/{waypoint_symbol}/jump-gate"
        warning_log = f"Unable to get details of jump gate: {waypoint_symbol}"
        logging.info(f"Fetching details of jump gate: {waypoint_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def get_construction_site(self, system_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """Get construction details for a waypoint.

        Parameters:
            system_symbol (str): The system symbol
            waypoint_symbol (str): The waypoint symbol
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"systems/{system_symbol}/waypoints/{waypoint_symbol}/construction"
        warning_log = f"Unable to get details of construction site: {waypoint_symbol}"
        logging.info(f"Fetching details of construction site: {waypoint_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def supply_construction_site(self, system_symbol, waypoint_symbol, ship_symbol, trade_symbol, units, raw_res=False, throttle_time=10):
        """Supply a construction site with the specified good.

        Parameters:
            system_symbol (str): The system symbol
            waypoint_symbol (str): The waypoint symbol
            ship_symbol (str): Symbol of the ship to use
            trade_symbol (str): The symbol of the good to supply
            units (int): Amount of units to supply

        Returns:
            dict: JSON response
        """
        endpoint = f"systems/{system_symbol}/waypoints/{waypoint_symbol}/construction/supply"
        warning_log = f"Unable to get the locations in the system: {system_symbol}"
        logging.info(f"Getting the locations in system: {system_symbol}")
        querystring = {"shipSymbol": ship_symbol, "tradeSymbol": trade_symbol, "units": units}
        res = self.generic_api_call("GET", endpoint, params=querystring, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False


class Api:
    def __init__(self, username=None, token=None):
        self.token = token
        self.agent = Agent(token=token)
        self.contracts = Contracts(token=token)
        self.faction = Faction(token=token)
        self.fleet = Fleet(token=token)
        self.systems = Systems(token=token)


class Agent(Client):
    """
    Get or create your agent details
    """

    def get_agent(self, raw_res=False, throttle_time=10):
        """Fetch your agent's details.

        https://spacetraders.stoplight.io/docs/spacetraders/eb030b06e0192-get-agent

        Example response:
        {
            "data": {
                "accountId": "cl0hok34m0003ks0jjql5q8f2",
                "flight_mode": "EMBER",
                "headquarters": "X1-OE-PM",
                "credits": 0
            }
        }

        Parameters:
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/agent"
        warning_log = f"Unable to retrieve agent details"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def list_agents(self, limit=10, page=1, raw_res=False, throttle_time=10):
        """Fetch agents details.

        https://spacetraders.stoplight.io/docs/spacetraders/d4567f6f3c159-list-agents

        Example response:
        {
            "data": [
                {
                    "accountId": "string",
                    "flight_mode": "string",
                    "headquarters": "string",
                    "credits": 0,
                    "startingFaction": "string",
                    "shipCount": 0
                }
            ],
            "meta": {
                "total": 0,
                "page": 1,
                "limit": 10
            }
        }

        Parameters:
            limit (int, optional): How many entries to return per page. Defaults to 10.
            page (int, optional): What entry offset to request. Defaults to 1.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"agents"
        querystring = {"page": page, "limit": limit}
        warning_log = f"Unable to list agents"
        res = self.generic_api_call("GET", endpoint, params=querystring, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def get_public_agent(self, agent_symbol, raw_res=False, throttle_time=10):
        """Fetch agent details.

        https://spacetraders.stoplight.io/docs/spacetraders/82c819018af91-get-public-agent

        Example response:
        {
            "data": {
                "accountId": "string",
                "flight_mode": "string",
                "headquarters": "string",
                "credits": 0,
                "startingFaction": "string",
                "shipCount": 0
            }
        }

        Parameters:
            agent_symbol (str, required): The agent flight_mode. Defaults to FEBA66.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"agents/" + agent_symbol
        warning_log = f"Unable to list agent"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def register_new_agent(self, symbol, faction, raw_res=False, throttle_time=10):
        """Registers a new agent in the Space Traders world

        Parameters:
            symbol (str): The flight_mode for your agent's ships
            faction (str): The faction you wish to join
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"register"
        warning_log = f"Unable to register new agent"
        params = {
            'flight_mode': symbol,
            'faction': faction
        }
        res = self.generic_api_call("POST", endpoint, token="", warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time, params=params)
        return res if res else False


class Faction(Client):
    """Endpoints related to factions.
    """

    def list_factions(self, limit=10, page=1, raw_res=False, throttle_time=10):
        """View the details of a faction.

        https://spacetraders.stoplight.io/docs/spacetraders/a50decd0f9483-get-faction

        Example response:
        {
            "data": [
                {
                    "flight_mode": "COSMIC",
                    "name": "string",
                    "description": "string",
                    "headquarters": "string",
                    "traits": [
                        {
                            "flight_mode": "BUREAUCRATIC",
                            "name": "string",
                            "description": "string"
                        }
                    ],
                  "isRecruiting": true
                }
            ],
            "meta": {
                "total": 0,
                "page": 1,
                "limit": 10
            }
        }

        Parameters:
            limit (int, optional): How many entries to return per page. Defaults to 10.
            page (int, optional): What entry offset to request. Defaults to 1.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"factions"
        querystring = {"page": page, "limit": limit}
        warning_log = f"Unable to list factions"
        res = self.generic_api_call("GET", endpoint, params=querystring, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def get_faction(self, faction_symbol, raw_res=False, throttle_time=10):
        """View the details of a faction.

        https://spacetraders.stoplight.io/docs/spacetraders/a50decd0f9483-get-faction

        Example response:
        {
            "data": {
                "flight_mode": "COSMIC",
                "name": "string",
                "description": "string",
                "headquarters": "string",
                "traits": [
                    {
                        "flight_mode": "BUREAUCRATIC",
                        "name": "string",
                        "description": "string"
                    }
                ],
                "isRecruiting": true
            }
        }

        Parameters:
            faction_symbol (str): How many entries to return per page. Defaults to 10.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"factions/" + faction_symbol
        warning_log = f"Unable to fetch faction"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False


class Contracts(Client):
    """Endpoints to handle contracts"""

    def deliver_cargo_to_contract(self, ship_symbol, contract_id, trade_symbol, units, raw_res=False, throttle_time=10):
        """Deliver cargo to a contract.

        https://spacetraders.stoplight.io/docs/spacetraders/8f89f3b4a246e-deliver-cargo-to-contract

        Parameters:
            ship_symbol (str): Symbol of a ship located in the destination to deliver a contract and that has a flight_mode to deliver in its cargo.
            contract_id (str): The ID of the contract.
            trade_symbol (sre): The flight_mode of the flight_mode to deliver.
            units (int): Amount of units to deliver.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/contracts/{contract_id}/deliver"
        params = {'shipSymbol': ship_symbol,
                  'tradeSymbol': trade_symbol,
                  'units': units}
        warning_log = f"Unable to deliver trade goods for contract: {contract_id}"
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def list_contracts(self, limit=10, page=1, raw_res=False, throttle_time=10):
        """Return a paginated list of all your contracts.

        https://spacetraders.stoplight.io/docs/spacetraders/b5d513949b11a-list-contracts

        Parameters:
            limit (int, optional): How many entries to return per page. Defaults to 10.
            page (int, optional): What entry offset to request. Defaults to 1.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/contracts"
        querystring = {"page": page, "limit": limit}
        warning_log = f"Unable to get a list contracts"
        res = self.generic_api_call("GET", endpoint, params=querystring, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def get_contract(self, contract_id, raw_res=False, throttle_time=10):
        """Get the details of a contract by ID.

        https://spacetraders.stoplight.io/docs/spacetraders/2889d8b056533-get-contract

        Parameters:
            contract_id (str): Id of contract to get the details for
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/contracts/{contract_id}"
        warning_log = f"Unable to get details of contract: {contract_id}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def accept_contract(self, contract_id, raw_res=False, throttle_time=10):
        """Accept a contract by ID.

        https://spacetraders.stoplight.io/docs/spacetraders/7dbc359629250-accept-contract

        Parameters:
            contract_id (str): ID of contract to accept
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/contracts/{contract_id}/accept"
        warning_log = f"Unable to accept contract: {contract_id}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def fulfill_contract(self, contract_id, raw_res=False, throttle_time=10):
        """Fulfill a contract. Can only be used on contracts that have all of their delivery terms fulfilled.

        https://spacetraders.stoplight.io/docs/spacetraders/d4ff41c101af0-fulfill-contract

        Parameters:
            contract_id (str): ID of contract to accept
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/contracts/{contract_id}/fulfill"
        warning_log = f"Unable to fulfill contract: {contract_id}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False
