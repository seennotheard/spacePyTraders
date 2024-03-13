from asyncio.format_helpers import extract_stack
import requests
import logging
import time
from SpacePyTradersV2 import models
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
            dict:
                ships (list[Ship]): List of ships you own.
                meta (Meta): Meta object.
        """
        endpoint = f"my/ships"
        querystring = {"page": page, "limit": limit}
        warning_log = f"Unable to get list of owned ships."
        logging.info(f"Getting a list of owned ships")
        res = self.generic_api_call("GET", endpoint, params=querystring, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"ships": models.parser(res['data'], list[models.Ship]),
               "meta": models.parser(res['meta'], models.Meta)}
        return ret if res else False

    def purchase_ship(self, ship_type, waypoint_symbol, raw_res=False, throttle_time=10):
        """Purchase a ship from a Shipyard. In order to use this function, a ship under your agent's ownership must
        be in a waypoint that has the Shipyard trait, and the Shipyard must sell the type of the desired ship.

        https://spacetraders.stoplight.io/docs/spacetraders/403855e2e99ad-purchase-ship

        Parameters:
            ship_type (str): Type of ship
            waypoint_symbol: The symbol of the waypoint you want to purchase the ship at.

        Returns:
            dict:
                agent (Agent): Agent object.
                ship (Ship): Ship object.
                transaction (ShipyardTransaction): ShipyardTransaction object.
        """
        endpoint = f"my/ships"
        params = {"waypointSymbol": waypoint_symbol, "shipType": ship_type}
        warning_log = f"Unable to buy ship type: {ship_type}, at waypoint: {waypoint_symbol}."
        logging.debug(f"Buying ship of type: {ship_type} at waypoint: {waypoint_symbol}")
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"agent": models.parser(res['data']['agent'], models.Agent),
               "ship": models.parser(res['data']['ship'], models.Ship),
               "transaction": models.parser(res['data']['transaction'], models.ShipyardTransaction)}
        return ret if res else False

    def get_ship(self, ship_symbol, raw_res=False, throttle_time=10):
        """Retrieve the details of a ship under your agent's ownership.

        https://spacetraders.stoplight.io/docs/spacetraders/800936299c838-get-ship

        Parameters:
            ship_symbol (str): The symbol of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            Ship (Ship): Ship object.
        """
        endpoint = f"my/ships/{ship_symbol}"
        warning_log = f"Unable to get info on ship: {ship_symbol}"
        logging.info(f"Getting info on ship: {ship_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data'], models.Ship) if res else False

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
        return models.parser(res['data'], models.ShipCargo) if res else False

    def orbit_ship(self, ship_symbol, raw_res=False, throttle_time=10):
        """Attempt to move your ship into orbit at its current location. The request will only succeed if your ship
        is capable of moving into orbit at the time of the request.

        https://spacetraders.stoplight.io/docs/spacetraders/08777d60b6197-orbit-ship

        Parameters:
            ship_symbol (str): The symbol of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            ShipNav: ShipNav object
        """
        endpoint = f"my/ships/{ship_symbol}/orbit"
        warning_log = f"Unable to orbit ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data']['nav'], models.ShipNav) if res else False

    def ship_refine(self, ship_symbol, produce, raw_res=False, throttle_time=10):
        """Attempt to refine the raw materials on your ship. The request will only succeed if your ship is capable of
        refining at the time of the request.

        https://spacetraders.stoplight.io/docs/spacetraders/c42b57743a49f-ship-refine

        Parameters:
            ship_symbol (str): The symbol of the ship.
            produce (str): The type of good to produce out of the refining process.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                cargo (ShipCargo): ShipCargo object.
                cooldown (Cooldown): Cooldown object.
                produced (list[ShipRefineGood]): List of produced goods.
                consumed (list[ShipRefineGood]): List of consumed goods.
        """
        endpoint = f"my/ships/{ship_symbol}/refine"
        params = {"produce": produce}
        warning_log = f"Unable to produce on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"cargo": models.parser(res['data']['cargo'], models.ShipCargo),
               "cooldown": models.parser(res['data']['cooldown'], models.Cooldown),
               "produced": models.parser(res['data']['produced'], list[models.ShipRefineGood]),
               "consumed": models.parser(res['data']['consumed'], list[models.ShipRefineGood])}
        return ret if res else False

    def create_chart(self, ship_symbol, raw_res=False, throttle_time=10):
        """Command a ship to chart the waypoint at its current location.

        https://spacetraders.stoplight.io/docs/spacetraders/177f127c7f888-create-chart

        Parameters:
            ship_symbol (str): The symbol of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                chart (Chart): Chart object
                waypoint (Waypoint): Waypoint object
        """
        endpoint = f"my/ships/{ship_symbol}/chart"
        warning_log = f"Unable to chart on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"chart": models.parser(res['data']['chart'], models.Chart),
               "waypoint": models.parser(res['data']['waypoint'], models.Waypoint)}
        return ret if res else False

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
        return models.parser(res['data'], models.Cooldown) if res else False

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
        return models.parser(res['data']['nav'], models.ShipNav) if res else False

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
            dict:
                cooldown (Cooldown): Cooldown object.
                surveys (list[Survey]): List of surveys.
        """
        endpoint = f"my/ships/{ship_symbol}/survey"
        warning_log = f"Unable to survey on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"cooldown": models.parser(res['data']['cooldown'], models.Cooldown),
               "surveys": models.parser(res['data']['surveys'], list[models.Survey])}
        return ret if res else False

    def extract_resources(self, ship_symbol, raw_res=False, throttle_time=10):
        """Extract resources from a waypoint that can be extracted, such as asteroid fields, into your ship. Send an
        optional survey as the payload to target specific yields.

        https://spacetraders.stoplight.io/docs/spacetraders/b3931d097608d-extract-resources

        Parameters:
            ship_symbol (str): The symbol of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                cooldown (Cooldown): Cooldown object.
                extraction (dict):
                    ship_symbol (str): Symbol of the ship that executed the extraction.
                    yield (ExtractionYield): ExtractionYield object.
                cargo (ShipCargo): ShipCargo object.
                events (list[ShipConditionEvent]): List of events.
        """
        endpoint = f"my/ships/{ship_symbol}/extract"
        warning_log = f"Unable to extract on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)

        ret = {"cooldown": models.parser(res['data']['cooldown'], models.Cooldown),
               "extraction": {"ship_symbol": res['data']['extraction']['shipSymbol'],
                              "yield": models.parser(res['data']['extraction']['yield'], models.ExtractionYield)},
               "cargo": models.parser(res['data']['cargo'], models.ShipCargo),
               "events": models.parser(res['data']['events'], list[models.ShipConditionEvent])}
        return ret if res else False

    def siphon_resources(self, ship_symbol, raw_res=False, throttle_time=10):
        """Siphon gases, such as hydrocarbon, from gas giants.

        https://spacetraders.stoplight.io/docs/spacetraders/f6c0d7877c43a-siphon-resources

        Parameters:
            ship_symbol (str): The symbol of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                cooldown (Cooldown): Cooldown object.
                siphon (dict):
                    ship_symbol (str): Symbol of the ship that executed the extraction.
                    yield (ExtractionYield): ExtractionYield object.
                cargo (ShipCargo): ShipCargo object.
                events (list[ShipConditionEvent]): List of events.
        """
        endpoint = f"my/ships/{ship_symbol}/siphon"
        warning_log = f"Unable to siphon on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"cooldown": models.parser(res['data']['cooldown'], models.Cooldown),
               "siphon": {"ship_symbol": res['data']['siphon']['shipSymbol'],
                          "yield": models.parser(res['data']['extraction']['yield'], models.ExtractionYield)},
               "cargo": models.parser(res['data']['cargo'], models.ShipCargo),
               "events": models.parser(res['data']['events'], list[models.ShipConditionEvent])}
        return ret if res else False

    def extract_resources_with_survey(self, ship_symbol, survey: models.Survey, raw_res=False, throttle_time=10):
        """Use a survey when extracting resources from a waypoint.

        https://spacetraders.stoplight.io/docs/spacetraders/cdf110a7af0ea-extract-resources-with-survey

        Parameters:
            ship_symbol (str): The symbol of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                cooldown (Cooldown): Cooldown object.
                extraction (dict):
                    ship_symbol (str): Symbol of the ship that executed the extraction.
                    yield (ExtractionYield): ExtractionYield object.
                cargo (ShipCargo): ShipCargo object.
                events (list[ShipConditionEvent]): List of events.
        """
        endpoint = f"my/ships/{ship_symbol}/extract/survey"
        warning_log = f"Unable to extract with survey on ship: {ship_symbol}"
        params = models.unpack(survey)
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"cooldown": models.parser(res['data']['cooldown'], models.Cooldown),
               "extraction": {"ship_symbol": res['data']['extraction']['shipSymbol'],
                              "yield": models.parser(res['data']['extraction']['yield'], models.ExtractionYield)},
               "cargo": models.parser(res['data']['cargo'], models.ShipCargo),
               "events": models.parser(res['data']['events'], list[models.ShipConditionEvent])}
        return ret if res else False

    def jettison_cargo(self, ship_symbol, symbol, units, raw_res=False, throttle_time=10):
        """Jettison cargo from your ship's cargo hold.

        https://spacetraders.stoplight.io/docs/spacetraders/3b0f8b69f56ac-jettison-cargo

        Parameters:
            ship_symbol (str): The ship symbol.
            symbol (str): The trade_symbol's symbol.
            units (int): Amount of units to jettison of this trade_symbol.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            Cargo: Cargo object
        """
        endpoint = f"my/ships/{ship_symbol}/jettison"
        warning_log = (
            f"Unable to jettison cargo from ship. Params - ship_symbol: {ship_symbol}, symbol: {symbol}, "
            f"units: {units}")
        logging.info(
            f"Jettison the following cargo from ship: {ship_symbol}, symbol: {symbol}, units: {units}")
        params = {"symbol": symbol, "units": units}
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data']['cargo'], models.ShipCargo) if res else False

    def jump_ship(self, ship_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """Jump your ship instantly to a target connected waypoint. The ship must be in orbit to execute a jump.

        https://spacetraders.stoplight.io/docs/spacetraders/19f0dd2d633de-jump-ship

        Parameters:
            ship_symbol (str): The symbol of the ship.
            waypoint_symbol (str): The symbol of the waypoint to jump to. The destination must be a connected waypoint.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                nav (ShipNav): ShipNav object.
                cooldown (Cooldown): Cooldown object.
                transaction (MarketTransaction): MarketTransaction object.
                agent (Agent): Agent object.
        """
        endpoint = f"my/ships/{ship_symbol}/jump"
        params = {"waypointSymbol": waypoint_symbol}
        warning_log = f"Unable to jump ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"nav": models.parser(res['data']['nav'], models.ShipNav),
               "cooldown": models.parser(res['data']['cooldown'], models.Cooldown),
               "transaction": models.parser(res['data']['transaction'], models.MarketTransaction),
               "agent": models.parser(res['data']['agent'], models.Agent)}
        return ret if res else False

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
            dict:
                fuel (ShipFuel): ShipFuel object.
                nav (ShipNav): ShipNav object.
                events (list[ShipConditionEvent]): List of events.
        """
        endpoint = f"my/ships/{ship_symbol}/navigate"
        params = {"waypointSymbol": waypoint_symbol}
        warning_log = f"Unable to navigate ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"fuel": models.parser(res['data']['fuel'], models.ShipFuel),
               "nav": models.parser(res['data']['nav'], models.ShipNav),
               "events": models.parser(res['data']['events'], list[models.ShipConditionEvent])}
        return ret if res else False

    def patch_ship_nav(self, ship_symbol, flight_mode, raw_res=False, throttle_time=10):
        """Update the nav configuration of a ship.

        https://spacetraders.stoplight.io/docs/spacetraders/34a305032ec79-patch-ship-nav

        Parameters:
            ship_symbol (str): The waypoint_symbol of the ship.
            flight_mode (str): The ship's set speed when traveling between waypoints or systems.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            ShipNav: ShipNav object
        """
        endpoint = f"my/ships/{ship_symbol}/nav"
        params = {"flightMode": flight_mode}
        warning_log = f"Unable to change flight mode on ship: {ship_symbol}"
        res = self.generic_api_call("PATCH", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data'], models.ShipNav) if res else False

    def get_ship_nav(self, ship_symbol, raw_res=False, throttle_time=10):
        """Get the current nav status of a ship.

        https://spacetraders.stoplight.io/docs/spacetraders/6e80adc7cc4f5-get-ship-nav

        Parameters:
            ship_symbol (str): The symbol of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            ShipNav: ShipNav object
        """
        endpoint = f"my/ships/{ship_symbol}/nav"
        warning_log = f"Unable to get nav on ship: {ship_symbol}"
        logging.info(f"Getting nav on ship: {ship_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data'], models.ShipNav) if res else False

    def warp_ship(self, ship_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """Warp your ship to a target destination in another system.

        https://spacetraders.stoplight.io/docs/spacetraders/faaf6603fc732-warp-ship

        Parameters:
            ship_symbol (str): The ship symbol.
            waypoint_symbol (str): The target destination.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                fuel (ShipFuel): ShipFuel object.
                nav (ShipNav): ShipNav object.
        """
        endpoint = f"my/ships/{ship_symbol}/warp"
        warning_log = f"Unable to warp ship {ship_symbol} to waypoint: {waypoint_symbol}"
        logging.info(f"Warping ship {ship_symbol} to waypoint: {waypoint_symbol}")
        params = {"waypointSymbol": waypoint_symbol}
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"fuel": models.parser(res['data']['fuel'], models.ShipFuel),
               "nav": models.parser(res['data']['nav'], models.ShipNav)}
        return ret if res else False

    def sell_cargo(self, ship_symbol, symbol, units, raw_res=False, throttle_time=10):
        """Sell cargo in your ship to a market that trades this cargo.

        https://spacetraders.stoplight.io/docs/spacetraders/b8ed791381b41-sell-cargo

        Parameters:00
            ship_symbol (str): The ship symbol.
            symbol (str): The good's symbol.
            units (int): Amount of units to sell of this trade_symbol.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                agent (Agent): Agent object.
                cargo (ShipCargo): ShipCargo object.
                transaction (MarketTransaction): MarketTransaction object.
        """
        endpoint = f"my/ships/{ship_symbol}/sell"
        warning_log = (
            f"Unable to sell cargo from ship. Params - ship_symbol: {ship_symbol}, symbol: {symbol}, "
            f"units: {units}")
        logging.info(f"Sell the following cargo from ship: {ship_symbol}, symbol: {symbol}, units: {units}")
        params = {"symbol": symbol, "units": units}
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"agent": models.parser(res['data']['agent'], models.Agent),
               "cargo": models.parser(res['data']['cargo'], models.ShipCargo),
               "transaction": models.parser(res['data']['transaction'], models.MarketTransaction)}
        return ret if res else False

    def scan_systems(self, ship_symbol, raw_res=False, throttle_time=10):
        """Scan for nearby systems, retrieving information on the systems' distance from the ship and their waypoints.

        https://spacetraders.stoplight.io/docs/spacetraders/d3358a9202901-scan-systems

        Parameters:
            ship_symbol (str): The ship symbol.

        Returns:
            dict:
                cooldown (Cooldown): Cooldown object
                systems (list[System]): List of systems
        """
        endpoint = f"my/ships/{ship_symbol}/scan/systems"
        warning_log = f"Failed to scan systems with ship ({ship_symbol})."
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"cooldown": models.parser(res['data']['cooldown'], models.Cooldown),
               "systems": models.parser(res['data']['systems'], list[models.ScannedSystem])}
        return ret if res else False

    def scan_waypoints(self, ship_symbol, raw_res=False, throttle_time=10):
        """Scan for nearby waypoints, retrieving detailed information on each waypoint in range.

        https://spacetraders.stoplight.io/docs/spacetraders/23dbc0fed17ec-scan-waypoints

        Parameters:
            ship_symbol (str): The ship symbol.

        Returns:
            dict:
                cooldown (Cooldown): Cooldown object
                waypoints (list[Waypoint]): List of waypoints
        """
        endpoint = f"my/ships/{ship_symbol}/scan/waypoints"
        warning_log = f"Failed to scan waypoints with ship ({ship_symbol})."
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"cooldown": models.parser(res['data']['cooldown'], models.Cooldown),
               "waypoints": models.parser(res['data']['waypoints'], list[models.Waypoint])}
        return ret if res else False

    def scan_ships(self, ship_symbol, raw_res=False, throttle_time=10):
        """Scan for nearby ships, retrieving information for all ships in range.

        https://spacetraders.stoplight.io/docs/spacetraders/74da68b7c32a7-scan-ships

        Parameters:
            ship_symbol (str): The ship symbol.

        Returns:
            dict:
                cooldown (Cooldown): Cooldown object
                waypoints (list[Waypoint]): List of waypoints
        """
        endpoint = f"my/ships/{ship_symbol}/scan/ships"
        warning_log = f"Failed to scan ships with ship ({ship_symbol})."
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"cooldown": models.parser(res['data']['cooldown'], models.Cooldown),
               "ships": models.parser(res['data']['ships'], list[models.Ship])}
        return ret if res else False

    def refuel_ship(self, ship_symbol, units, from_cargo=False, raw_res=False, throttle_time=10):
        """Refuel your ship by buying fuel from the local market.

        Parameters:
            ship_symbol (str): The ship symbol.
            units: The amount of fuel to fill in the ship's tanks.
            from_cargo (bool): Whether to use the FUEL that's in your cargo or not. Default: false

        Returns:
            dict:
                agent (Agent): Agent object.
                fuel (ShipFuel): ShipFuel object.
                transaction (MarketTransaction): MarketTransaction object.
        """
        endpoint = f"my/ships/{ship_symbol}/refuel"
        warning_log = f"Failed to refuel ship ({ship_symbol})."
        params = {"units": units, "fromCargo": from_cargo}
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"agent": models.parser(res['data']['agent'], models.Agent),
               "fuel": models.parser(res['data']['fuel'], models.ShipFuel),
               "transaction": models.parser(res['data']['transaction'], models.MarketTransaction)}
        return ret if res else False

    def purchase_cargo(self, ship_symbol, symbol, units, raw_res=False, throttle_time=10):
        """Purchase cargo from a market.

        https://spacetraders.stoplight.io/docs/spacetraders/45acbf7dc3005-purchase-cargo

        Parameters:
            ship_symbol (str): The ship symbol.
            symbol (str): The good's symbol.
            units (int): Amount of units to sell of this trade_symbol.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                agent (Agent): Agent object.
                cargo (ShipCargo): ShipCargo object.
                transaction (MarketTransaction): MarketTransaction object.
        """
        endpoint = f"my/ships/{ship_symbol}/purchase"
        warning_log = (
            f"Unable to buy cargo from ship. Params - ship_symbol: {ship_symbol}, symbol: {symbol}, "
            f"units: {units}")
        logging.info(f"Buy the following cargo from ship: {ship_symbol}, symbol: {symbol}, units: {units}")
        params = {"symbol": symbol, "units": units}
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"agent": models.parser(res['data']['agent'], models.Agent),
               "cargo": models.parser(res['data']['cargo'], models.ShipCargo),
               "transaction": models.parser(res['data']['transaction'], models.MarketTransaction)}
        return ret if res else False

    # Transfer Cargo
    def transfer_cargo(self, origin_ship_symbol, trade_symbol, dest_ship_symbol, units, raw_res=False,
                       throttle_time=10):
        """Transfer cargo between ships.

        Parameters:
            origin_ship_symbol (str): The transferring ship's symbol.
            trade_symbol (str): The good's symbol.
            units (int): Amount of units to transfer.
            dest_ship_symbol (str): The symbol of the ship to transfer to.

        Returns:
            ShipCargo: The origin ship's cargo.
        """
        endpoint = f"my/ships/{origin_ship_symbol}/transfer"
        warning_log = f"Unable to transfer {units} units of {trade_symbol} from ship: {origin_ship_symbol} to ship: {dest_ship_symbol}"
        logging.info(
            f"Transferring {units} units of {trade_symbol} from ship: {origin_ship_symbol} to ship: {dest_ship_symbol}")
        params = {"tradeSymbol": trade_symbol, "units": units, "shipSymbol": dest_ship_symbol}
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data']['cargo'], models.ShipCargo) if res else False

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
        return models.parser(res['data'], models.Contract) if res else False

    def get_mounts(self, ship_symbol, raw_res=False, throttle_time=10):
        """Get the mounts installed on a ship.

        https://spacetraders.stoplight.io/docs/spacetraders/23ab20baf0ea8-get-mounts

        Parameters:
            ship_symbol (str): The symbol of the ship.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            list[ShipMount]: List of installed mounts.
        """
        endpoint = f"my/ships/{ship_symbol}/mounts"
        warning_log = f"Unable to get mounts on ship: {ship_symbol}"
        logging.info(f"Getting mounts on ship: {ship_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data'], list[models.ShipMount]) if res else False

    def install_mount(self, ship_symbol, symbol, raw_res=False, throttle_time=10):
        """Install a mount on a ship.

        https://spacetraders.stoplight.io/docs/spacetraders/266f3d0591399-install-mount

        Parameters:
            ship_symbol (str): The ship's symbol.
            symbol (str): The symbol of the mount to install.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                agent (Agent): Agent object.
                mounts (list[ShipMount]): List of ShipMount objects.
                cargo (ShipCargo): ShipCargo object.
                transaction (MarketTransaction): MarketTransaction object.
        """
        endpoint = f"my/ships/{ship_symbol}/mounts/install"
        params = {"symbol": symbol}
        warning_log = f"Unable to install mount on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"agent": models.parser(res['data']['agent'], models.Agent),
               "mounts": models.parser(res['data']['mounts'], list[models.ShipMount]),
               "cargo": models.parser(res['data']['cargo'], models.ShipCargo),
               "transaction": models.parser(res['data']['transaction'], models.MarketTransaction)}
        return ret if res else False

    def remove_mount(self, ship_symbol, symbol, raw_res=False, throttle_time=10):
        """Remove a mount from a ship.

        https://spacetraders.stoplight.io/docs/spacetraders/9380132527c1d-remove-mount

        Parameters:
            ship_symbol (str): The ship's symbol.
            symbol (str): The symbol of the mount to remove.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                agent (Agent): Agent object.
                mounts (list[ShipMount]): List of ShipMount objects.
                cargo (ShipCargo): ShipCargo object.
                transaction (MarketTransaction): MarketTransaction object.
        """
        endpoint = f"my/ships/{ship_symbol}/mounts/remove"
        params = {"symbol": symbol}
        warning_log = f"Unable to install mount on ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"agent": models.parser(res['data']['agent'], models.Agent),
               "mounts": models.parser(res['data']['mounts'], list[models.ShipMount]),
               "cargo": models.parser(res['data']['cargo'], models.ShipCargo),
               "transaction": models.parser(res['data']['transaction'], models.MarketTransaction)}
        return ret if res else False

    def get_scrap_ship(self, ship_symbol, raw_res=False, throttle_time=10):
        """Get the amount of value that will be returned when scrapping a ship.

        https://spacetraders.stoplight.io/docs/spacetraders/7e41557eefa3c-get-scrap-ship

        Parameters:
            ship_symbol (str): The ship's symbol.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            RepairTransaction: RepairTransactionObject
        """
        endpoint = f"my/ships/{ship_symbol}/scrap"
        warning_log = f"Unable to get scrap price: {ship_symbol}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data']['transaction'], models.RepairTransaction) if res else False

    def scrap_ship(self, ship_symbol, raw_res=False, throttle_time=10):
        """Scrap a ship, removing it from the game and returning a portion of the ship's value to the agent.

        https://spacetraders.stoplight.io/docs/spacetraders/76039bfbf0cdb-scrap-ship

        Parameters:
            ship_symbol (str): The ship's symbol.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                agent: Agent object.
                transaction: RepairTransaction object.
        """
        endpoint = f"my/ships/{ship_symbol}/scrap"
        warning_log = f"Unable to scrap ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"agent": models.parser(res['data']['agent'], models.Agent),
               "transaction": models.parser(res['data']['transaction'], models.RepairTransaction)}
        return ret if res else False

    def get_repair_ship(self, ship_symbol, raw_res=False, throttle_time=10):
        """Get the cost of repairing a ship.

        https://spacetraders.stoplight.io/docs/spacetraders/4497f006ea9a7-get-repair-ship

        Parameters:
            ship_symbol (str): The ship's symbol.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            RepairTransaction: RepairTransactionObject
        """
        endpoint = f"my/ships/{ship_symbol}/repair"
        warning_log = f"Unable to get repair price: {ship_symbol}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data']['transaction'], models.RepairTransaction) if res else False

    def repair_ship(self, ship_symbol, raw_res=False, throttle_time=10):
        """Repair a ship, restoring the ship to maximum condition.

        https://spacetraders.stoplight.io/docs/spacetraders/54a08ae25a5da-repair-ship

        Parameters:
            ship_symbol (str): The ship's symbol.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                agent: Agent object.
                ship: Ship object.
                transaction: RepairTransaction object.
        """
        endpoint = f"my/ships/{ship_symbol}/repair"
        warning_log = f"Unable to repair ship: {ship_symbol}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"agent": models.parser(res['data']['agent'], models.Agent),
               "ship": models.parser(res['data']['ship'], models.Ship),
               "transaction": models.parser(res['data']['transaction'], models.RepairTransaction)}
        return ret if res else False


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
            dict:
                systems (list[System]): List of systems.
                meta (Meta): Meta object.
        """
        endpoint = f"systems"
        querystring = {"page": page, "limit": limit}
        warning_log = f"Unable to list agents"
        res = self.generic_api_call("GET", endpoint, params=querystring, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"systems": models.parser(res['data'], list[models.System]),
               "meta": models.parser(res['meta'], models.Meta)}
        return ret if res else False

    def get_system(self, system_symbol, raw_res=False, throttle_time=10):
        """Get the details of a system.

        https://spacetraders.stoplight.io/docs/spacetraders/67e77e75c65e7-get-system

        Parameters:
            system_symbol (str): The system symbol.

        Returns:
            System: System object.
        """
        endpoint = f"systems/{system_symbol}"
        warning_log = f"Unable to get the  system: {system_symbol}"
        logging.info(f"Getting the system: {system_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data'], models.System) if res else False

    def list_waypoints_in_system(self, system_symbol, limit=10, page=1, traits=None, type=None, raw_res=False,
                                 throttle_time=10):
        """Return a paginated list of all the waypoints for a given system.

        Parameters:
            system_symbol (str): The system symbol
            limit (int): How many entries to return per page
            page (int): What entry offset to request
            traits (str |  list[str]):

        Returns:
            dict:
                waypoints (list[Waypoint]): List of waypoints in the system.
                meta (Meta): Meta object.
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
        ret = {"waypoints": models.parser(res['data'], list[models.Waypoint]),
               "meta": models.parser(res['meta'], models.Meta)}
        return ret if res else False

    def get_waypoint(self, system_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """View the details of a waypoint.

        https://spacetraders.stoplight.io/docs/spacetraders/58e66f2fa8c82-get-waypoint

        Parameters:
            system_symbol (str): The system symbol
            waypoint_symbol (str): The waypoint symbol
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            waypoint: Waypoint object.
        """
        endpoint = f"systems/{system_symbol}/waypoints/{waypoint_symbol}"
        warning_log = f"Unable to get details of waypoint: {waypoint_symbol}"
        logging.info(f"Fetching details of waypoint: {waypoint_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data'], models.Waypoint) if res else False

    def get_market(self, system_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """Retrieve imports, exports and exchange data from a marketplace.

        https://spacetraders.stoplight.io/docs/spacetraders/a4fed7a0221e0-get-market

        Parameters:
            system_symbol (str): The system symbol
            waypoint_symbol (str): The waypoint symbol
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            Market: Market object.
        """
        endpoint = f"systems/{system_symbol}/waypoints/{waypoint_symbol}/market"
        warning_log = f"Unable to get details of market: {waypoint_symbol}"
        logging.info(f"Fetching details of market: {waypoint_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data'], models.Market) if res else False

    def get_shipyard(self, system_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """Get the shipyard for a waypoint.

        https://spacetraders.stoplight.io/docs/spacetraders/460fe70c0e4c2-get-shipyard

        Parameters:
            system_symbol (str): The system symbol
            waypoint_symbol (str): The waypoint symbol
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            Shipyard: Shipyard object.
        """
        endpoint = f"systems/{system_symbol}/waypoints/{waypoint_symbol}/shipyard"
        warning_log = f"Unable to get details of shipyard: {waypoint_symbol}"
        logging.info(f"Fetching details of shipyard: {waypoint_symbol}")
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data'], models.Shipyard) if res else False

    def get_jump_gate(self, system_symbol, waypoint_symbol, raw_res=False, throttle_time=10):
        """Get jump gate details for a waypoint.

        https://spacetraders.stoplight.io/docs/spacetraders/decd101af6414-get-jump-gate

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
        return models.parser(res['data'], models.JumpGate) if res else False

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
        return models.parser(res['data'], models.Construction) if res else False

    def supply_construction_site(self, system_symbol, waypoint_symbol, ship_symbol, trade_symbol, units, raw_res=False,
                                 throttle_time=10):
        """Supply a construction site with the specified good.

        Parameters:
            system_symbol (str): The system symbol
            waypoint_symbol (str): The waypoint symbol
            ship_symbol (str): Symbol of the ship to use
            trade_symbol (str): The symbol of the good to supply
            units (int): Amount of units to supply

        Returns:
            dict:
                construction (Construction): Construction object.
                cargo (ShipCargo): ShipCargo object.
        """
        endpoint = f"systems/{system_symbol}/waypoints/{waypoint_symbol}/construction/supply"
        warning_log = f"Unable to get the locations in the system: {system_symbol}"
        logging.info(f"Getting the locations in system: {system_symbol}")
        querystring = {"shipSymbol": ship_symbol, "tradeSymbol": trade_symbol, "units": units}
        res = self.generic_api_call("GET", endpoint, params=querystring, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"construction": models.parser(res['data']['construction'], models.Construction),
               "cargo": models.parser(res['data']['cargo'], models.ShipCargo)}
        return ret if res else False


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

        Parameters:
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            Agent: Agent object
        """
        endpoint = f"my/agent"
        warning_log = f"Unable to retrieve agent details"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data'], models.Agent) if res else False

    def list_agents(self, limit=10, page=1, raw_res=False, throttle_time=10):
        """Fetch agents details.

        https://spacetraders.stoplight.io/docs/spacetraders/d4567f6f3c159-list-agents

        Parameters:
            limit (int, optional): How many entries to return per page. Defaults to 10.
            page (int, optional): What entry offset to request. Defaults to 1.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                agents (list[Agent]): List of agents.
                meta (Meta): Meta object.
        """
        endpoint = f"agents"
        querystring = {"page": page, "limit": limit}
        warning_log = f"Unable to list agents"
        res = self.generic_api_call("GET", endpoint, params=querystring, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"agents": models.parser(res['data'], list[models.Agent]),
               "meta": models.parser(res['meta'], models.Meta)}
        return ret if res else False

    def get_public_agent(self, agent_symbol, raw_res=False, throttle_time=10):
        """Fetch agent details.

        https://spacetraders.stoplight.io/docs/spacetraders/82c819018af91-get-public-agent

        Parameters:
            agent_symbol (str, required): The agent symbol. Defaults to FEBA66.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            Agent: Agent object
        """
        endpoint = f"agents/" + agent_symbol
        warning_log = f"Unable to list agent"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data'], models.Agent) if res else False

    def register_new_agent(self, symbol, faction, raw_res=False, throttle_time=10):
        """Registers a new agent in the Space Traders world.

        Parameters:
            symbol (str): The symbol for your agent's ships
            faction (str): The faction you wish to join
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                agent (Agent): Agent object.
                contract (Contract): Contract object.
                faction (Faction): Faction object.
                ship (Ship): Ship object.
                token (str): A Bearer token for accessing secured API endpoints.
        """
        endpoint = f"register"
        warning_log = f"Unable to register new agent"
        params = {
            'symbol': symbol,
            'faction': faction
        }
        res = self.generic_api_call("POST", endpoint, token="", warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time, params=params)
        ret = {"agent": models.parser(res['data']['agent'], models.Agent),
               "contract": models.parser(res['data']['contract'], models.Contract),
               "faction": models.parser(res['data']['faction'], models.Faction),
               "ship": models.parser(res['data']['ship'], models.Ship),
               "token": res['data']['token']}
        return ret if res else False


class Faction(Client):
    """Endpoints related to factions.
    """

    def list_factions(self, limit=10, page=1, raw_res=False, throttle_time=10):
        """View the details of a faction.

        https://spacetraders.stoplight.io/docs/spacetraders/a50decd0f9483-get-faction

        Parameters:
            limit (int, optional): How many entries to return per page. Defaults to 10.
            page (int, optional): What entry offset to request. Defaults to 1.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                factions (list[Faction]): List of factions.
                meta (Meta): Meta object.
        """
        endpoint = f"factions"
        querystring = {"page": page, "limit": limit}
        warning_log = f"Unable to list factions"
        res = self.generic_api_call("GET", endpoint, params=querystring, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"factions": models.parser(res['data'], list[models.Faction]),
               "meta": models.parser(res['meta'], models.Meta)}
        return ret if res else False

    def get_faction(self, faction_symbol, raw_res=False, throttle_time=10):
        """View the details of a faction.

        https://spacetraders.stoplight.io/docs/spacetraders/a50decd0f9483-get-faction

        Parameters:
            faction_symbol (str): How many entries to return per page. Defaults to 10.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            Faction: Faction object
        """
        endpoint = f"factions/" + faction_symbol
        warning_log = f"Unable to fetch faction"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data'], models.Faction) if res else False


class Contracts(Client):
    """Endpoints to handle contracts"""

    def deliver_cargo_to_contract(self, ship_symbol, contract_id, trade_symbol, units, raw_res=False, throttle_time=10):
        """Deliver cargo to a contract.

        https://spacetraders.stoplight.io/docs/spacetraders/8f89f3b4a246e-deliver-cargo-to-contract

        Parameters:
            ship_symbol (str): Symbol of a ship located in the destination to deliver a contract and that has a good to deliver in its cargo.
            contract_id (str): The ID of the contract.
            trade_symbol (sre): The symbol of the good to deliver.
            units (int): Amount of units to deliver.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                contract (Contract): Contract object.
                cargo (ShipCargo): ShipCargo object.
        """
        endpoint = f"my/contracts/{contract_id}/deliver"
        params = {'shipSymbol': ship_symbol,
                  'tradeSymbol': trade_symbol,
                  'units': units}
        warning_log = f"Unable to deliver trade goods for contract: {contract_id}"
        res = self.generic_api_call("POST", endpoint, params=params, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"contract": models.parser(res['data']['contract'], models.Contract),
               "cargo": models.parser(res['data']['cargo'], models.ShipCargo)}
        return ret if res else False

    def list_contracts(self, limit=10, page=1, raw_res=False, throttle_time=10):
        """Return a paginated list of all your contracts.

        https://spacetraders.stoplight.io/docs/spacetraders/b5d513949b11a-list-contracts

        Parameters:
            limit (int, optional): How many entries to return per page. Defaults to 10.
            page (int, optional): What entry offset to request. Defaults to 1.
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                contracts (list[Contract]): List of contracts.
                meta (Meta): Meta object.
        """
        endpoint = f"my/contracts"
        querystring = {"page": page, "limit": limit}
        warning_log = f"Unable to get a list contracts"
        res = self.generic_api_call("GET", endpoint, params=querystring, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"contracts": models.parser(res['data'], list[models.Contract]),
               "meta": models.parser(res['meta'], models.Meta)}
        return ret if res else False

    def get_contract(self, contract_id, raw_res=False, throttle_time=10):
        """Get the details of a contract by ID.

        https://spacetraders.stoplight.io/docs/spacetraders/2889d8b056533-get-contract

        Parameters:
            contract_id (str): ID of contract to get the details for
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            Contract: Contract details.
        """
        endpoint = f"my/contracts/{contract_id}"
        warning_log = f"Unable to get details of contract: {contract_id}"
        res = self.generic_api_call("GET", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        return models.parser(res['data'], models.Contract) if res else False

    def accept_contract(self, contract_id, raw_res=False, throttle_time=10):
        """Accept a contract by ID.

        https://spacetraders.stoplight.io/docs/spacetraders/7dbc359629250-accept-contract

        Parameters:
            contract_id (str): ID of contract to accept
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                agent (Agent): Agent details.
                contract (Contract): Contract details.
        """
        endpoint = f"my/contracts/{contract_id}/accept"
        warning_log = f"Unable to accept contract: {contract_id}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"agent": models.parser(res['data']['agent'], models.Agent),
               "contract": models.parser(res['data']['contract'], models.Contract)}
        return ret if res else False

    def fulfill_contract(self, contract_id, raw_res=False, throttle_time=10):
        """Fulfill a contract. Can only be used on contracts that have all of their delivery terms fulfilled.

        https://spacetraders.stoplight.io/docs/spacetraders/d4ff41c101af0-fulfill-contract

        Parameters:
            contract_id (str): ID of contract to accept
            raw_res (bool, optional): Return raw response instead of JSON. Defaults to False.
            throttle_time (int, optional): How long to wait before attempting call again. Defaults to 10.

        Returns:
            dict:
                agent (Agent): Agent object.
                contract (Contract): Contract object.
        """
        endpoint = f"my/contracts/{contract_id}/fulfill"
        warning_log = f"Unable to fulfill contract: {contract_id}"
        res = self.generic_api_call("POST", endpoint, token=self.token, warning_log=warning_log,
                                    raw_res=raw_res, throttle_time=throttle_time)
        ret = {"agent": models.parser(res['data']['agent'], models.Agent),
               "contract": models.parser(res['data']['contract'], models.Contract)}
        return ret if res else False
