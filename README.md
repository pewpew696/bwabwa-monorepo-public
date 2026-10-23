# Bwabwa Monorepo

Tools for the browser strategy game WarEra.io, written in Python.

## Projects
- **bwabwabot**: Discord bot with market analytics, fair-price valuation, and country intel commands
- **bwabwaweb**: FastAPI web app serving market data, plus a combat simulator

## Setup
1. `cd bwabwabot` (or `bwabwaweb`)
2. `pip install -r requirements.txt` (web: `requirements-web.txt`)
3. Copy `.env.example` to `.env` and fill in your own values
4. Bot: `python main.py`

## Tests
`pip install -r requirements-dev.txt && pytest` (inside `bwabwabot`)
