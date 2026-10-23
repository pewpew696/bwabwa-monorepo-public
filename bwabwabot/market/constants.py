# market/constants.py
from __future__ import annotations

# Data murni di services/economy/constants.py. Re-export untuk backward compat.
from services.economy.constants import (
    ITEM_LABELS, ITEM_SHORT, EQUIPMENT_GRADES,
    API_KEY_TO_ITEM_ID, ITEM_ID_TO_API_KEY,
    AMMO_OR_CONSTRUCTION_IDS, FOOD_OR_BUFF_IDS,
    ITEM_LABEL_TO_CODE,
)

BASE_URL          = "https://api2.warera.io/trpc"
PRICES_URL        = f"{BASE_URL}/itemTrading.getPrices"
ORDERS_URL        = f"{BASE_URL}/tradingOrder.getTopOrders"
COUNTRIES_URL     = f"{BASE_URL}/country.getAllCountries"
COUNTRY_BY_ID_URL = f"{BASE_URL}/country.getCountryById"
REGIONS_URL       = f"{BASE_URL}/region.getRegionsObject"
PARTY_URL         = f"{BASE_URL}/party.getById"
ROUND_URL         = f"{BASE_URL}/round.getById"
COMPANIES_URL     = f"{BASE_URL}/company.getCompanies"
COMPANY_URL       = f"{BASE_URL}/company.getById"
WORKERS_URL       = f"{BASE_URL}/worker.getWorkers"
GOVERNMENT_URL    = f"{BASE_URL}/government.getByCountryId"

TRANSACTION_URL = f"{BASE_URL}/transaction.getPaginatedTransactions"
USER_LITE_URL   = f"{BASE_URL}/user.getUserLite"
SEARCH_URL      = f"{BASE_URL}/search.searchAnything"

