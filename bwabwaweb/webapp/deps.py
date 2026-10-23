"""Wiring dependency FastAPI: service, sesi, dan gerbang tier."""
from functools import lru_cache
from typing import Callable

from fastapi import Cookie, Depends, Request

from webapp.core.errors import TierRequiredError, UnauthorizedError
from webapp.core.settings import COOKIE_IDENTITY, COOKIE_UPGRADE, get_settings
from webapp.queries import (
    queries_bonus,
    queries_cache,
    queries_identity,
    queries_intel,
    queries_market,
    queries_fiscal,
    queries_territory,
    queries_traders,
    queries_companies,
)
from webapp.web_services.auth_service import (
    TIER_BASIC,
    TIER_PRO,
    AuthService,
    SessionInfo,
)
from webapp.web_services.home_service import HomeService
from webapp.web_services.bonus_service import BonusService
from webapp.web_services.intel_service import IntelService
from webapp.web_services.player_service import PlayerService
from webapp.web_services.mu_service import MuService
from webapp.web_services.open_orders_service import OpenOrdersService
from webapp.web_services.portfolio_service import PortfolioService
from webapp.web_services.simulator_service import SimulatorService
from webapp.web_services.builder_service import BuilderService
from webapp.web_services.territory_service import TerritoryService
from webapp.web_services.market_service import MarketService
from webapp.web_services.token_service import TokenService
from webapp.web_services.traders_service import TradersService
from webapp.web_services.top_traders_service import TopTradersService
from webapp.web_services.country_stock_service import CountryStockService
from webapp.web_services.fairprice_service import FairpriceService
from webapp.web_services.fiscal_service import FiscalService
from webapp.web_services.companies_service import CompaniesService

TIER_RANK = {TIER_BASIC: 1, TIER_PRO: 2}
USER_AGENT_MAX_LENGTH = 120


@lru_cache(maxsize=1)
def get_token_service() -> TokenService:
    return TokenService(get_settings().jwt_secret)


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    return AuthService(get_settings(), get_token_service(), queries_identity)


@lru_cache(maxsize=1)
def get_home_service() -> HomeService:
    return HomeService(queries_market)


@lru_cache(maxsize=1)
def get_market_service() -> MarketService:
    return MarketService(queries_market, queries_cache)


@lru_cache(maxsize=1)
def get_bonus_service() -> BonusService:
    return BonusService(queries_bonus)


@lru_cache(maxsize=1)
def get_territory_service() -> TerritoryService:
    return TerritoryService(queries_territory)


@lru_cache(maxsize=1)
def get_intel_service() -> IntelService:
    return IntelService(queries_intel)


@lru_cache(maxsize=1)
def get_player_service() -> PlayerService:
    return PlayerService()


@lru_cache(maxsize=1)
def get_mu_service() -> MuService:
    return MuService()


@lru_cache(maxsize=1)
def get_portfolio_service() -> PortfolioService:
    return PortfolioService()


@lru_cache(maxsize=1)
def get_simulator_service() -> SimulatorService:
    return SimulatorService()


@lru_cache(maxsize=1)
def get_builder_service() -> BuilderService:
    return BuilderService()


@lru_cache(maxsize=1)
def get_traders_service() -> TradersService:
    return TradersService(queries_traders)


@lru_cache(maxsize=1)
def get_top_traders_service() -> TopTradersService:
    return TopTradersService()


@lru_cache(maxsize=1)
def get_country_stock_service() -> CountryStockService:
    return CountryStockService()


@lru_cache(maxsize=1)
def get_fairprice_service() -> FairpriceService:
    return FairpriceService()


@lru_cache(maxsize=1)
def get_fiscal_service() -> FiscalService:
    return FiscalService(queries_fiscal)


@lru_cache(maxsize=1)
def get_companies_service() -> CompaniesService:
    return CompaniesService(queries_companies, queries_fiscal, queries_territory)


@lru_cache(maxsize=1)
def get_open_orders_service() -> OpenOrdersService:
    return OpenOrdersService()


def read_client_ip(request: Request) -> str:
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    return request.client.host if request.client else ""


def _read_device_info(request: Request) -> str:
    headers = request.headers
    hint_names = ("sec-ch-ua-model", "sec-ch-ua-platform", "sec-ch-ua-platform-version")
    hints = " ".join(headers.get(name, "").strip('"') for name in hint_names).strip()
    user_agent = headers.get("user-agent", "")[:USER_AGENT_MAX_LENGTH]
    return f"{hints} | {user_agent}".strip(" |")


def get_optional_session(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    identity_token: str | None = Cookie(default=None, alias=COOKIE_IDENTITY),
    upgrade_token: str | None = Cookie(default=None, alias=COOKIE_UPGRADE),
) -> SessionInfo | None:
    return auth_service.find_session(
        identity_token, upgrade_token, _read_device_info(request), read_client_ip(request)
    )


def get_required_session(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    identity_token: str | None = Cookie(default=None, alias=COOKIE_IDENTITY),
    upgrade_token: str | None = Cookie(default=None, alias=COOKIE_UPGRADE),
) -> SessionInfo:
    session = auth_service.find_session(
        identity_token, upgrade_token, _read_device_info(request), read_client_ip(request)
    )
    if session is None:
        raise UnauthorizedError("sesi tidak valid")
    return session


def require_tier(minimum_tier: str) -> Callable[..., SessionInfo]:
    def check_tier(session: SessionInfo = Depends(get_required_session)) -> SessionInfo:
        # Basic = cukup login. Pro = butuh upgrade pwd 1.
        if minimum_tier == TIER_BASIC:
            return session
        current_rank = TIER_RANK.get(session.tier or TIER_BASIC, 1)
        required_rank = TIER_RANK.get(minimum_tier, 99)
        if current_rank < required_rank:
            raise TierRequiredError(minimum_tier)
        return session
    return check_tier
