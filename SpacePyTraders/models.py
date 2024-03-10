from dataclasses import dataclass, field, fields
import re


@dataclass
class User:
    """
    The basic user object. Great way to store and access a user's credits, ships and loans.

    Args:
        username (str): The username of the user
        credits (int): How many credits does the user have
        ships (list): A list of the ships the user owns

    Returns:
        User: returns a user object
    """
    username: str
    credits: int
    ships: field(default_factory=list)


@dataclass
class Agent:
    account_id: str
    symbol: str
    headquarters: str
    credits: int
    starting_faction: int
    ship_count: int


@dataclass
class Chart:
    submitted_by: str
    submitted_on: str
    waypoint_symbol: str = None  # optional


@dataclass
class ConstructionMaterial:
    tradeSymbol: str
    required: int
    fulfilled: int


@dataclass
class Construction:
    symbol: str
    materials: list[ConstructionMaterial]
    isComplete: bool


@dataclass
class ContractDeliverGood:
    trade_symbol: str
    destination_symbol: str
    units_required: int
    units_fulfilled: int


@dataclass
class ContractPayment:
    on_accepted: int
    on_fulfilled: int


@dataclass
class ContractTerms:
    deadline: str
    payment: ContractPayment
    deliver: ContractDeliverGood


@dataclass
class Contract:
    id: str
    faction_symbol: str
    type: str
    terms: list[ContractTerms]
    accepted: bool
    fulfilled: bool
    expiration: str  # deprecated
    deadline_to_accept: str


@dataclass
class Cooldown:
    ship_symbol: str
    total_seconds: int
    remaining_seconds: int
    expiration: str = None  # optional


@dataclass
class ExtractionYield:
    symbol: str
    units: int


@dataclass
class FactionSymbol:
    symbol: str


@dataclass
class FactionTrait:
    symbol: str
    name: str
    description: str


@dataclass
class Faction:
    symbol: str
    name: str
    description: str
    headquarters: str
    traits: list[FactionTrait]  # look at this again, can we just do a list[str]?
    is_recruiting: bool


@dataclass
class JumpGate:
    symbol: str
    connections: list[str]


@dataclass
class TradeGood:  # WaypointModifier, WaypointTrait, and TradeGood share the same structure
    symbol: str
    name: str
    description: str


@dataclass
class MarketTradeGood:
    symbol: str
    type: str
    trade_volume: int
    supply: str
    activity: str
    purchase_price: int
    sell_price: int


@dataclass
class MarketTransaction:
    waypoint_symbol: str
    ship_symbol: str
    trade_symbol: str
    type: str
    units: int
    price_per_unit: int
    total_price: int
    timestamp: str


@dataclass
class Market:
    symbol: str
    exports: list[TradeGood]
    imports: list[TradeGood]
    exchange: list[TradeGood]
    transactions: list[MarketTransaction] = None  # optional
    trade_goods: list[MarketTradeGood] = None


@dataclass
class WaypointModifier:  # WaypointModifier, WaypointTrait, and TradeGood share the same structure
    symbol: str
    name: str
    description: str


@dataclass
class WaypointTrait:  # WaypointModifier, WaypointTrait, and TradeGood share the same structure
    symbol: str
    name: str
    description: str


@dataclass
class Waypoint:
    symbol: str
    type: str
    x: int
    y: int
    orbitals: list[str]
    faction: FactionSymbol
    traits: list[WaypointTrait]
    modifiers: list[WaypointModifier]
    chart: Chart
    is_under_construction: bool
    orbits: str = None  # optional


@dataclass
class Meta:  # for pagination
    total: int
    page: int
    limit: int


@dataclass
class ShipCargoItem:
    symbol: str
    name: str
    description: str
    units: int


@dataclass
class ShipCargo:
    capacity: int
    units: int
    inventory: list[ShipCargoItem]


@dataclass
class ShipCrew:
    current: int
    required: int
    capacity: int
    rotation: str
    morale: int
    wages: int


@dataclass
class ShipRequirements:
    crew: int
    power: int = None  # optional
    slots: int = None


@dataclass
class ShipEngine:
    symbol: str
    name: str
    description: str
    condition: int
    speed: int
    requirements: ShipRequirements


@dataclass
class ShipFrame:
    symbol: str
    name: str
    description: str
    condition: int
    module_slots: int
    mounting_points: int
    fuel_capacity: int
    requirements: ShipRequirements


@dataclass
class ShipFuelConsumed:
    amount: int
    timestamp: str


@dataclass
class ShipFuel:
    current: int
    capacity: int
    consumed: ShipFuelConsumed  # optional


@dataclass
class ShipModule:
    symbol: str
    name: str
    description: str
    requirements: ShipRequirements
    capacity: int = None  # optional
    range: int = None


@dataclass
class ShipMount:
    symbol: str
    name: str
    description: str
    strength: int
    requirements: ShipRequirements
    deposits: list[str] = None  # optional field, + look at this again


@dataclass
class ShipNavRouteWaypoint:
    symbol: str
    type: str
    system_symbol: str
    x: int
    y: int


@dataclass
class ShipNavRoute:
    destination: ShipNavRouteWaypoint
    origin: ShipNavRouteWaypoint
    departure_time: str
    arrival: str


@dataclass
class ShipNav:
    system_symbol: str
    waypoint_symbol: str
    route: ShipNavRoute
    status: str
    flight_mode: str


@dataclass
class ShipReactor:
    symbol: str
    name: str
    description: str
    condition: int
    power_output: int
    requirements: ShipRequirements


@dataclass
class ShipRegistration:
    name: str
    faction_symbol: str
    role: str


@dataclass
class Ship:
    symbol: str
    registration: ShipRegistration
    nav: ShipNav
    frame: ShipFrame
    reactor: ShipReactor
    engine: ShipEngine
    mounts: list[ShipMount]
    crew: ShipCrew = None  # optional fields (for scanned)
    cooldown: Cooldown = None
    modules: list[ShipModule] = None
    cargo: ShipCargo = None
    fuel: ShipFuel = None


@dataclass
class SurveyDeposit:
    symbol: str


@dataclass
class Survey:
    signature: str
    symbol: str
    deposits: list[SurveyDeposit]
    expiration: str
    size: str


@dataclass
class SystemWaypoint:
    symbol: str
    type: str
    x: int
    y: int
    orbitals: list[str]
    orbits: str = None  # optional


@dataclass
class System:
    symbol: str
    sector_symbol: str
    type: str
    x: int
    y: int
    waypoints: list[SystemWaypoint]
    factions: list[FactionSymbol]


class_dict = {}
list_dict = {}
global_objects = globals()
classes_in_global_namespace = {name: obj for name, obj in global_objects.items() if isinstance(obj, type)}
for name, obj in classes_in_global_namespace.items():
    class_dict[name] = obj
    list_dict[list[obj]] = obj


def parser(data, model):
    if model in list_dict:  # if we fit things into a list
        result = []
        for i in data:
            result.append(parser(data=i, model=list_dict[model]))
        return result;
    else:
        class_info = {}  # dict passed to constructor
        for key, value in data.items():
            for i in fields(model):
                if i.name == to_snake(key):  # dont forget to deal w camel case whatevs
                    if i.type in list_dict:  # if type is list of a models class
                        class_info[i.name] = parser(data=value, model=i.type)
                    elif i.type in class_dict.values():  # elif type is a models class
                        class_info[i.name] = parser(data=value, model=i.type)
                    else:  # primitive
                        class_info[i.name] = value
                    break

        return model(**class_info)


def unpack(k):
    if type(k) is list:  # if we fit things into a list
        result = []
        for i in k:
            result.append(unpack(i))
        return result;
    res = {}
    if type(k) is dict:
        for attr, value in k.items():
            if type(value) is list or type(value) in class_dict.values():  # type is class or list of class
                value = unpack(value)
            res[to_lower_camel_case(attr)] = value
        return res
    for attr, value in k.__dict__.items():
        if type(value) is list or type(value) in class_dict.values():  # type is class or list of class
            value = unpack(value)
        res[to_lower_camel_case(attr)] = value
    return res


def to_snake(name):
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()


def to_camel_case(snake_str):
    return "".join(x.capitalize() for x in snake_str.lower().split("_"))


def to_lower_camel_case(snake_str):
    # We capitalize the first letter of each component except the first one
    # with the 'capitalize' method and join them together.
    camel_string = to_camel_case(snake_str)
    return snake_str[0].lower() + camel_string[1:]
