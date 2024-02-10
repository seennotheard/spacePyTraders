from asyncio.format_helpers import extract_stack
import requests
import logging
import time
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
        print(type(params))
        return requests.post(url, headers=headers, json=params)
    elif method == "PUT":
        return requests.put(url, headers=headers, data=params)
    elif method == "DELETE":
        return requests.delete(url, headers=headers, data=params)

    # If an Invalid method provided throw exception
    if method not in ["GET", "POST", "PUT", "DELETE"]:
        logging.exception(f'Invalid method provided: {method}')


@dataclass
class Client():
    def __init__(self, username=None, token=None):
        """The Client class handles all user interaction with the Space Traders API. 
        The class is initiated with the username and token of the user. 
        If the user does not provide a token the 'create_user' method will attempt to fire and create a user with the username provided. 
        If a user with the name already exists an exception will fire. 

        Parameters:
            username (str): Username of the user
            token (str): The personal auth token for the user. If None will invoke the 'create_user' method
            v2 (bool): Determine if you want to use the new V2 API or V1
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
        raise (TooManyTriesException)


class Fleet(Client):
    def list_ships(self, limit=10, page=1, raw_res=False, throttle_time=10):
        """Return a paginated list of all of ships under your agent's ownership.

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
            waypoint_symbol: The symbol of the waypoint you want to purchase the ship at.

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
            ship_symbol (str): The symbol of the ship.
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
            ship_symbol (str): The symbol of the ship.
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
            ship_symbol (str): The symbol of the ship.
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
            ship_symbol (str): The symbol of the ship.
            produce (str): The type of trade_symbol to waypoint_symbol out of the refining process.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/refine"
        params = {"waypoint_symbol": produce}
        warning_log = f"Unable to waypoint_symbol on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def create_chart(self, ship_symbol, raw_res=False, throttle_time=10):
        """Command a ship to chart the waypoint at its current location.

        https://spacetraders.stoplight.io/docs/spacetraders/177f127c7f888-create-chart

        Parameters:
            ship_symbol (str): The symbol of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/orbit"
        warning_log = f"Unable to chart on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def get_ship_cooldown(self, ship_symbol, raw_res=False, throttle_time=10):
        """Retrieve the details of your ship's reactor cooldown. Some actions such as activating your jump drive,
        scanning, or extracting resources taxes your reactor and results in a cooldown.

        https://spacetraders.stoplight.io/docs/spacetraders/d20ef14bc0742-get-ship-cooldown

        Parameters:
            ship_symbol (str): The symbol of the ship.
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
            ship_symbol (str): The symbol of the ship.
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
            ship_symbol (str): The symbol of the ship.
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
            ship_symbol (str): The symbol of the ship.
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
            ship_symbol (str): The symbol of the ship.
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
                            "symbol": "PRECIOUS_STONES",
                            "name": "string",
                            "description": "string",
                            "units": 1
                        }
                    ]
                }
            }
        }

        Parameters:
            ship_symbol (str): The ship symbol.
            symbol (str): The trade_symbol's symbol.
            units (int): Amount of units to jettison of this trade_symbol.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/jettison"
        warning_log = (f"Unable to jettison cargo from ship. Params - ship_symbol: {ship_symbol}, symbol: {symbol}, "
                       f"units: {units}")
        logging.info(f"Jettison the following cargo from ship: {ship_symbol}, symbol: {symbol}, units: {units}")
        params = {"symbol": symbol, "units": units}
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def jump_ship(self, ship_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """Jump your ship instantly to a target connected waypoint. The ship must be in orbit to execute a jump.

        https://spacetraders.stoplight.io/docs/spacetraders/19f0dd2d633de-jump-ship

        Parameters:
            ship_symbol (str): The symbol of the ship.
            waypoint_symbol (str): The symbol of the waypoint to jump to. The destination must be a connected waypoint.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/jump"
        params = {"waypoint_symbol": waypoint_symbol}
        warning_log = f"Unable to waypoint_symbol on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def navigate_ship(self, ship_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """Navigate to a target destination. The ship must be in orbit to use this function. The destination waypoint
        must be within the same system as the ship's current location. Navigating will consume the necessary fuel
        from the ship's manifest based on the distance to the target waypoint.

        https://spacetraders.stoplight.io/docs/spacetraders/c766b84253edc-navigate-ship

        Parameters:
            ship_symbol (str): The symbol of the ship.
            waypoint_symbol (str): The target destination.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/jump"
        params = {"waypoint_symbol": waypoint_symbol}
        warning_log = f"Unable to waypoint_symbol on ship: {ship_symbol}"
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
    def transfer_cargo(self, origin_ship_symbol, trade_symbol, dest_ship_symbol, units, raw_res=False, throttle_time=10):
        """Transfer cargo between ships.

        Parameters:
            origin_ship_symbol (str): The transferring ship's symbol.
            trade_symbol (str): The good's symbol.
            units (int): Amount of units to transfer.
            dest_ship_symbol (str): The symbol of the ship to transfer to.

        Returns:
            dict: A dict is returned with two keys "fromShip" & "toShip" each with the updated ship info for the respective ships
        """
        endpoint = f"my/ships/{origin_ship_symbol}/transfer"
        warning_log = f"Unable to transfer {units} units of {trade_symbol} from ship: {origin_ship_symbol} to ship: {dest_ship_symbol}"
        logging.info(f"Transferring {units} units of {trade_symbol} from ship: {origin_ship_symbol} to ship: {dest_ship_symbol}")
        params = {"symbol": trade_symbol, "units": units, "dest_ship_symbol": dest_ship_symbol}
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False


class Systems(Client):
    # Get system info
    def get_systems(self, raw_res=False, throttle_time=10):
        """[ENDPOINT CURRENTLY BROKEN - DEVS FIXING]
        
        Get info about the systems and their locations.

        Returns:
            dict: dict containing a JSON list of the different systems
        """
        # Get user
        endpoint = f"game/systems"
        warning_log = f"Unable to get systems"
        logging.info(f"Getting systems")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log)
        return res if res else False

        # Get all active flights

    def get_active_flight_plans(self, symbol, raw_res=False, throttle_time=10)
        """Get all the currently active flight plans in the system given. This is for all global accounts

        Parameters:
            symbol (str): Symbol of the system. OE or XV

        Returns:
            dict : dict containing a list of flight plans for each system as the key
        """
        endpoint = f"systems/{symbol}/flight-plans"
        warning_log = f"Unable to get flight plans for system: {symbol}."
        logging.info(f"Getting the flight plans in the {symbol} system")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log)
        return res if res else False

    # Get System's Locations
    def get_system_locations(self, symbol, raw_res=False, throttle_time=10):
        """Get locations in the defined system

        Parameters:
            symbol (str): The symbol for the system eg: OE

        Returns:
            dict: A dict containing a JSON list of the locations in the system
        """
        endpoint = f"systems/{symbol}/locations"
        warning_log = f"Unable to get the locations in the system: {symbol}"
        logging.info(f"Getting the locations in system: {symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log)
        return res if res else False

    def get_system_docked_ships(self, symbol, raw_res=False, throttle_time=10):
        """Get docked ships in the defined system

        Parameters:
            symbol (str): The symbol for the system eg: OE

        Returns:
            dict: A dict containing a JSON list of the docked ships in the system
        """
        endpoint = f"systems/{symbol}/ships"
        warning_log = f"Unable to get the docked ships in the system: {symbol}"
        logging.info(f"Getting the docked ships in system: {symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log)
        return res if res else False

    def get_system(self, symbol, raw_res=False, throttle_time=10):
        """Get info on the definined system

        Parameters:
            symbol (str): The symbol for the system eg: OE

        Returns:
            dict: A dict with info about the system
        """
        endpoint = f"systems/{symbol}"
        warning_log = f"Unable to get the  system: {symbol}"
        logging.info(f"Getting the system: {symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log)
        return res if res else False

    def get_available_ships(self, symbol, raw_res=False, throttle_time=10):
        """Get the ships listed for sale in the system defined

        Parameters:
            symbol (str): The symbol for the system eg: OE

        Returns:
            dict: A dict containing a list of the available ships for sale
        """
        endpoint = f"systems/{symbol}/ship-listings"
        warning_log = f"Unable to get the listed ships in system: {symbol}"
        logging.info(f"Getting the ships available for sale: {symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log)
        return res if res else False

    def chart_waypoint(self, ship_symbol, raw_res=False, throttle_time=10):
        """Chart a new system or waypoint. 
        Returns an array of the symbols that have been charted, 
        including the system and the waypoint if both were uncharted, or just the waypoint.

        Parameters:
            ship_symbol (str): symbol of ship that will perform the charting
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

            API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDQ2NjQ0MjA-chart-waypoint
        """
        endpoint = f"my/ships/{ship_symbol}/chart"
        warning_log = f"Unable to chart the waypoint: {ship_symbol}"
        logging.info(f"Unable to chart the waypoint: {ship_symbol}")
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log)
        return res if res else False

    def list_systems(self, raw_res=False, throttle_time=10):
        """Return a list of all systems.

        Parameters:
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

            API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDQ5Mjk2Mzc-list-systems
        """
        endpoint = f"systems"
        warning_log = f"Unable to view systems"
        logging.info(f"Unable to view systems")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log)
        return res if res else False

    def list_waypoints(self, system_symbol, raw_res=False, throttle_time=10):
        """Fetch all of the waypoints for a given system. 
        System must be charted or a ship must be present to return waypoint details.

        Parameters:
            system_symbol (str): symbol of system to get list of waypoints
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

            API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDY2NzYwMTY-list-waypoints
        """
        endpoint = f"systems/{system_symbol}/waypoints"
        warning_log = f"Unable to get list of waypoints in system: {system_symbol}"
        logging.info(f"Unable to get list of waypoints in system: {system_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log)
        return res if res else False

    def view_waypoint(self, system_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """View the details of a waypoint.

        Parameters:
            system_symbol (str): Symbol of system waypoint is located in
            waypoint_symbol (str): Symbol of waypoint to get details for
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"systems/{system_symbol}/waypoints/{waypoint_symbol}"
        warning_log = f"Unable to get details of waypoint: {waypoint_symbol}"
        logging.info(f"Unable to get details of waypoint: {waypoint_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log)
        return res if res else False


class Api():
    def __init__(self, username=None, token=None):
        self.token = token
        self.agent = Agent(token=token)
        self.contracts = Contracts(token=token)
        self.faction = Faction(token=token)
        self.extract = Extract(token=token)
        self.markets = Markets(token=token)
        self.navigation = Navigation(token=token)
        self.fleet = Fleet(token=token)
        self.shipyard = Shipyard(token=token)
        self.systems = Systems(token=token)
        self.trade = Trade(token=token)

    def register_new_agent(self, symbol, faction, *Parameters, **kwParameters):
        """Registers a new agent in the Space Traders world

        Parameters:
            symbol (str): The symbol for your agent's ships
            faction (str): The faction you wish to join

        Returns:
            dict: JSON response
        
        Usage:
        """
        endpoint = f"register"
        warning_log = f"Unable to register new agent"
        params = {
            'symbol': symbol,
            'faction': faction
        }
        res = make_request("POST", V2_URL + endpoint, headers={}, params=params)
        print(res.text)
        if res.ok:
            data = res.json().get("data")
            self.token = data.get("token")
            self.fleet.token = self.token
            self.systems.token = self.token
            self.agent.token = self.token
            self.markets.token = self.token
            self.trade.token = self.token
            self.navigation.token = self.token
            self.contracts.token = self.token
            self.extract.token = self.token
            self.shipyard.token = self.token
        else:
            logging.warning(warning_log)
            logging.warning(res.text)
        return res if res else False


#
#
# V2 Related Classes
#
#


class Agent(Client):
    """
    Get or create your agent details
    """

    def get_my_agent_details(self, raw_res=False, throttle_time=10):
        """Get your agent details

        https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDQ2NjQ0MTk-my-agent-details

        Example response:
        {
            "data": {
                "accountId": "cl0hok34m0003ks0jjql5q8f2",
                "symbol": "EMBER",
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
                    "symbol": "string",
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

    def get_public_agent(self, agentSymbol, raw_res=False, throttle_time=10):
        """Fetch agent details.

        https://spacetraders.stoplight.io/docs/spacetraders/82c819018af91-get-public-agent

        Example response:
        {
            "data": {
                "accountId": "string",
                "symbol": "string",
                "headquarters": "string",
                "credits": 0,
                "startingFaction": "string",
                "shipCount": 0
            }
        }

        Parameters:
            agentSymbol (str, required): The agent symbol. Defaults to FEBA66.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"agents/" + agentSymbol
        warning_log = f"Unable to list agent"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def register_new_agent(self, symbol, faction, raw_res=False, throttle_time=10):
        """Registers a new agent in the Space Traders world

        Parameters:
            symbol (str): The symbol for your agent's ships
            faction (str): The faction you wish to join
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"register"
        warning_log = f"Unable to register new agent"
        params = {
            'symbol': symbol,
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
                    "symbol": "COSMIC",
                    "name": "string",
                    "description": "string",
                    "headquarters": "string",
                    "traits": [
                        {
                            "symbol": "BUREAUCRATIC",
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

    def get_faction(self, factionSymbol, raw_res=False, throttle_time=10):
        """Return a paginated list of all the factions in the game.

        https://spacetraders.stoplight.io/docs/spacetraders/93c5d5e6ad5b0-list-factions

        Example response:
        {
            "data": {
                "symbol": "COSMIC",
                "name": "string",
                "description": "string",
                "headquarters": "string",
                "traits": [
                    {
                        "symbol": "BUREAUCRATIC",
                        "name": "string",
                        "description": "string"
                    }
                ],
                "isRecruiting": true
            }
        }

        Parameters:
            factionSymbol (str): How many entries to return per page. Defaults to 10.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"factions/" + factionSymbol
        warning_log = f"Unable to fetch faction"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False


class Markets(Client):
    """Endpoints related to interacting with markets in the system
    """

    def deploy_asset(self, ship_symbol, trade_symbol, raw_res=False, throttle_time=10):
        """Use this endpoint to deploy a Communications Relay to a waypoint. 
            A waypoint with a communications relay will allow agents to retrieve price information from the market. 
            Without a relay, agents must send a ship to a market to retrieve price information.
            Communication relays can be purchased from a market that exports COMM_RELAY_I.

        Parameters:
            shipSymbol (str): The symbol for your agent's ships
            tradeSymbol (str): Symbol for communicatino relay that you want to deploy to the waypoint.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

        API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDY0ODE2NDA-deploy-asset
        """
        endpoint = f"my/ships/{ship_symbol}/deploy"
        params = {'tradeSymbol': trade_symbol}
        warning_log = f"Unable to deploy communicatino relay. Ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time, params=params)
        return res if res else False

    def trade_imports(self, trade_symbol, raw_res=False, throttle_time=10):
        """TODO: Explain what this endpoint does

        Parameters:
            trade_symbol (str): symbol of the trade symbol you want to import
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

        API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDY0MDgxNTg-trade-imports
        """
        endpoint = f"trade/{trade_symbol}/imports"
        warning_log = f"Unable to view trade import for trade: {trade_symbol}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def trade_exports(self, trade_symbol, raw_res=False, throttle_time=10):
        """TODO: Explain what this endpoint does

        Parameters:
            trade_symbol (str): symbol of the trade symbol you want to import
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

        API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDY0MDgxNTk-trade-exports
        """
        endpoint = f"trade/{trade_symbol}/exports"
        warning_log = f"Unable to view trade export for trade: {trade_symbol}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def trade_exchanges(self, trade_symbol, raw_res=False, throttle_time=10):
        """TODO: Explain what this endpoint does

        Parameters:
            trade_symbol (str): symbol of the trade symbol you want to import
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

        API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDY0MDgxNjA-trade-exchanges
        """
        endpoint = f"trade/{trade_symbol}/exchange"
        warning_log = f"Unable to view trade exchange for trade symbol: {trade_symbol}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def list_markets(self, system_symbol, raw_res=False, throttle_time=10):
        """Retrieve a list of all charted markets in the given system. 
           Markets are only available if the waypoint is charted and contains a communications relay.

           To install a communications relay at a market, look at the my/ships/{shipSymbol}/deploy endpoint.

        Parameters:
            system_symbol (sre): symbol of the system you want to list markets for
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        
        API URL: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDY0ODYwNjQ-list-markets
        """
        endpoint = f"systems/{system_symbol}/markets"
        warning_log = f"Unable to get list of markets in system: {system_symbol}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def view_market(self, system_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """Retrieve imports, exports and exchange data from a marketplace. 
           Imports can be sold, exports can be purchased, and exchange trades can be purchased or sold.

           Market data is only available if you have a ship at the location, or the location is charted and has a communications relay deployed.

           See /my/ships/{shipSymbol}/deploy for deploying relays at a location.

        Parameters:
            system_symbol (str): Symbol for the system the market is located in
            waypoint_symbol (str): Symbol for the waypoint the market is located in
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

            API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDY2OTM4NjY-view-market
        """
        endpoint = f"systems/{system_symbol}/markets/{waypoint_symbol}"
        warning_log = f"Unable to get markets in system: {system_symbol} & waypoint: {waypoint_symbol}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False


class Trade(Client):
    "Buy and Sell cargo"

    def purchase_cargo(self, ship_symbol, trade_symbol, units, raw_res=False, throttle_time=10):
        """Purchase cargo from a waypoint's market
        
        Example Response:
        {
            "data": {
                "waypointSymbol": "X1-OE-PM",
                "tradeSymbol": "MICROPROCESSORS",
                "credits": -843,
                "units": 1
            }
        }

        Parameters:
            ship_symbol (str): Symbol of the ship to transfer the cargo onto
            trade_symbol (str): symbol of the trade symbol to purchase
            units (str): how many units of the trade symbol to purchase
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

            API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDQ2NjQ0Mjc-purchase-cargo
        """
        endpoint = f"my/ships/{ship_symbol}/purchase"
        params = {
            'tradeSymbol': trade_symbol,
            'units': units
        }
        warning_log = f"Unable to get purchase {units} units of symbol: {trade_symbol} onto ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time, params=params)
        return res if res else False

    def sell_cargo(self, ship_symbol, trade_symbol, units, raw_res=False, throttle_time=10):
        """Sell cargo to a waypoint's market
        
        Example Response:
        {
            "data": {
                "waypointSymbol": "X1-OE-PM",
                "tradeSymbol": "SILICON",
                "credits": 144,
                "units": -1
            }
        }

        Parameters:
            ship_symbol (str): Symbol of the ship to transfer the cargo from
            trade_symbol (str): symbol of the trade symbol to sell
            units (int): how many units of the trade symbol to sell
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

            API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDQ2NjQ0MzA-sell-cargo
        """
        endpoint = f"my/ships/{ship_symbol}/sell"
        params = {
            'tradeSymbol': trade_symbol,
            'units': units
        }
        warning_log = f"Unable to get purchase {units} units of symbol: {trade_symbol} onto ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time, params=params)
        return res if res else False


class Navigation(Client):

    def dock_ship(self, ship_symbol, raw_res=False, throttle_time=10):
        """Transition your ship from orbit to docked. Consecutive calls to this endpoint will succeed.

        {
            "data": {
                "status": "DOCKED"
            }
        }

        Parameters:
            ship_symbol (str): Symbol of the ship to dock
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        
        API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDQ2NjQ0MjI-dock-ship
        """
        endpoint = f"my/ships/{ship_symbol}/dock"
        warning_log = f"Unable to dock ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def orbit_ship(self, ship_symbol, raw_res=False, throttle_time=10):
        """Transition your ship from docked into orbit. 
        Ships are placed into orbit by default when arriving at a destination. 
        Consecutive calls to this endpoint will continue to return a 200 response status.

        {
            "data": {
                "status": "ORBIT"
            }
        }

        Parameters:
            ship_symbol (str): Symbol of the ship to dock
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        
        API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDQ2NjQ0MjI-dock-ship
        """
        endpoint = f"my/ships/{ship_symbol}/orbit"
        warning_log = f"Unable to orbit ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def jump_ship(self, ship_symbol, destination, raw_res=False, throttle_time=10):
        """Navigate a ship between systems

        Parameters:
            ship_symbol (str): Symbol of ship to make a jump
            destination (str): System to jump to
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

        API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDQ2NjQ0MjY-jump-ship
        """
        endpoint = f"my/ships/{ship_symbol}/jump"
        params = {'destination': destination}
        warning_log = f"Unable to jump ship: {ship_symbol} to System: {destination}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time, params=params)
        return res if res else False

    def jump_cooldown(self, ship_symbol, raw_res=False, throttle_time=10):
        """See how long your ship has on cooldown

        Parameters:
            ship_symbol (str): Symbol of the ship to check it's cooldown for
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

            API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDUyMzY2MDg-jump-cooldown
        """
        endpoint = f"my/ships/{ship_symbol}/jump"
        warning_log = f"Unable to jump ship: {ship_symbol}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def refuel_ship(self, ship_symbol, raw_res=False, throttle_time=10):
        """Fully refuel a ship

        Response example:
        {
            "data": {
                "credits": -1920,
                "fuel": 800
            }
        }

        Parameters:
            ship_symbol (str): Symbol of ship to refuel
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

            API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDQ2NjQ0Mjg-refuel-ship
        """
        endpoint = f"my/ships/{ship_symbol}/refuel"
        warning_log = f"Unable to refuel ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def navigate_ship(self, ship_symbol, destination, raw_res=False, throttle_time=10):
        """Fly a ship from one place to another.

        Example response:
        {
            "data": {
                "fuelCost": 38,
                "navigation": {
                "shipSymbol": "BA03F2-1",
                "departure": "X1-OE-PM",
                "destination": "X1-OE-A005",
                "durationRemaining": 2279,
                "arrivedAt": null
                }
            }
        }

        Parameters:
            ship_symbol (str): Symbol of ship to fly
            destination (str): Symbol of destination to fly to
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

            API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDQ5MzQ3MzU-navigate-ship
        """
        endpoint = f"my/ships/{ship_symbol}/navigate"
        params = {'destination': destination}
        warning_log = f"Unable to navigate ship: {ship_symbol} to destination: {destination}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time, params=params)
        return res if res else False

    def navigation_status(self, ship_symbol, raw_res=False, throttle_time=10):
        """Checks to see the status of a ships navigation path

        Parameters:
            ship_symbol (str): Symbol of ship to check navigation status for
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        
            API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDQ5MzQ3MzY-navigation-status
        """
        endpoint = f"my/ships/{ship_symbol}/navigate"
        warning_log = f"Unable to get navigation status for ship: {ship_symbol}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False


class Contracts(Client):
    """Endpoints to handle contracts"""

    def deliver_contract(self, ship_symbol, contract_id, trade_symbol, units, raw_res=False, throttle_time=10):
        """Deliver cargo to a contract.

        https://spacetraders.stoplight.io/docs/spacetraders/8f89f3b4a246e-deliver-cargo-to-contract

        Parameters:
            ship_symbol (str): Symbol of a ship located in the destination to deliver a contract and that has a symbol to deliver in its cargo.
            contract_id (str): The ID of the contract.
            trade_symbol (sre): The symbol of the symbol to deliver.
            units (int): Amount of units to deliver.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/contracts/{contract_id}/deliver"
        params = {
            'shipSymbol': ship_symbol,
            'tradeSymbol': trade_symbol,
            'units': units
        }
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


class Extract(Client):
    """Functions related to extracting resources from a waypoint"""

    def extract_resource(self, ship_symbol, survey={}, raw_res=False, throttle_time=10):
        """Extract resources from the waypoint into your ship. 
        Send a survey as the payload to target specific yields. 
        The entire survey must be sent as it contains a signature that the backend verifies.

        Example Response:
        {
            "data": {
                "extraction": {
                    "shipSymbol": "4B902A-1",
                    "yield": {
                        "tradeSymbol": "SILICON",
                        "units": 16
                    }
                },
                "cooldown": {
                    "duration": 119,
                    "expiration": "2022-03-12T00:41:29.371Z"
                }
            }
        }

        Parameters:
            ship_symbol (str): Symbol of ship performing the extraction
            payload (dict): entire response from a survey of a waypoint
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"my/ships/{ship_symbol}/extract"
        warning_log = f"Unable to extract resources: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time, params=survey)
        return res if res else False

    def extraction_cooldown(self, ship_symbol, raw_res=False, throttle_time=10):
        """Get the status of your last extraction.

        Parameters:
            ship_symbol (str): Symbol of ship to get status for
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

            API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDQ5MzU0NDQ-extraction-cooldown
        """
        endpoint = f"my/ships/{ship_symbol}/extract"
        warning_log = f"Get the status of your last extraction: {ship_symbol}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def survey_waypoint(self, ship_symbol, raw_res=False, throttle_time=10):
        """If you want to target specific yields for an extraction, you can survey a waypoint, 
        such as an asteroid field, and send the survey in the body of the extract request. 
        Each survey may have multiple deposits, and if a symbol shows up more than once, 
        that indicates a higher chance of extracting that resource.

        Your ship will enter a cooldown between consecutive survey requests. 
        Surveys will eventually expire after a period of time. 
        Multiple ships can use the same survey for extraction.

        Parameters:
            ship_symbol (str): Symbol of ship to perform the survey
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

            API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDQ5MzU0NTI-survey-waypoint
        """
        endpoint = f"my/ships/{ship_symbol}/survey"
        warning_log = f"Unable to perform a survey of a waypoint: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def survey_cooldown(self, ship_symbol, raw_res=False, throttle_time=10):
        """Executing a survey will initiate a cooldown for a number of seconds before you can call it again. 
        This endpoint returns the details of your cooldown, or a 404 if there is no cooldown for the survey action.

        Parameters:
            ship_symbol (str): symbol of ship to check status of cooldown
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

            API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDQ5MzU0NTM-survey-cooldown
        """
        endpoint = f"my/ships/{ship_symbol}/survey"
        warning_log = f"Unable to check on status of cooldown for ship: {ship_symbol}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False


class Shipyard(Client):
    """Function specific to handling shipyard"""

    def purchase_ship(self, listing_id, raw_res=False, throttle_time=10):
        """Purchase a ship

        Parameters:
            listing_id (str): The id of the shipyard listing you want to purchase.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

            API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDUyNDAzMDc-purchase-ship
        """
        endpoint = f"my/ships"
        warning_log = f"Unable to purchase ship with listing id: {listing_id}"
        params = {'id': listing_id}
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time, params=params)
        return res if res else False

    def list_shipyards(self, system_symbol, raw_res=False, throttle_time=10):
        """Returns a list of all shipyards in a system.

        Parameters:
            system_symbol (str): symbol of system to get list of shipyards for
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

            API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDUyNDAzMDY-list-shipyards
        """
        endpoint = f"systems/{system_symbol}/shipyards"
        warning_log = f"Unable to view shipyards in system: {system_symbol}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def shipyard_details(self, system_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """Get details about a shipyard

        Parameters:
            system_symbol (str): Symbol of system shipyard is located in
            waypoint_symbol (str): Symbol of waypoint shipyeard is located in
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response

            API Link: https://spacetraders.stoplight.io/docs/spacetraders/b3A6NDUyNDAzMDQ-shipyard-details
        """
        endpoint = f"systems/{system_symbol}/shipyards/{waypoint_symbol}"
        warning_log = f"Unable to view shipyard in system: {system_symbol}, waypoint: {waypoint_symbol}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False

    def shipyard_listings(self, system_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """View ships available for purchase in shipyard

        Parameters:
            system_symbol (str): system shipyard is located in
            waypoint_symbol (str): waypoint shipyard is located in
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict: JSON response
        """
        endpoint = f"systems/{system_symbol}/shipyards/{waypoint_symbol}/ships"
        warning_log = f"Unable to view ships in shipyard in system: {system_symbol}, waypoint: {waypoint_symbol}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return res if res else False


if __name__ == "__main__":
    token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZGVudGlmaWVyIjoiSE1BUyIsImlhdCI6MTY1Mzc4NDEzNSwic3ViIjoiYWdlbnQtdG9rZW4ifQ.ovMpoIza1Xd9f5WfvxtvQTGmHVELXfea9sdm-usgdnFxr_vLxm3YTIFMxZPeptIXd_GVc9rX4m_iEajpu_DZzeO4uDO0w66vY9GNnltdid243v1ePMVacTZg0sVsVLG24SjL5hlNrb-4TUZ8yDJkdg-C4w_1ODbB3YZ1KxrHTt4u4F-zbfuW8JNkAJBa-KBUHhpI3Abl3G699KzNYuj77m5u1XtBtDfHBXHQqTeSlz72jf5nLUSFcN4BGoADCPyZxmUPK4C9NRW_IYUiEqa4i7ETBaoUVl-Ot6bnEJ2ZTciDqj8cdgZHMsMqq68pB_fnw1-hkaECVxkwSK6uK3LmPVD0R8-BtVcxOx0NvDQxKyLoLjKHPxAbOgfk1j_51qJuscPxzosPkimK8wOZGlxuUrXCp6FAwVHzIcDhU-Y0KvLdG-OZpM6nDJZe-2WbjCeFhM8JgDG-Sne2kTY32MfhVYWMeXdNmRuTOJaCCh-dF5WVRs53bGzczsYhYz4tAbbU"
    client = Client("HMAS", token=token, v2=True)
    ship = Fleet("", token, v2=True)
    extract = Shipyard("", token, v2=True)
    print(ship.list_ships())
    # username = "JimHawkins"
    # token = "0930cc36-7dc7-4cb1-8823-d8e72594d91e"

    # api = Api(username, token)

    # print(api.loans.get_loans_available())