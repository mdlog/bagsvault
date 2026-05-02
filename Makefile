.PHONY: help install install-backend install-frontend \
	dev dev-backend dev-frontend \
	test test-backend test-frontend \
	lint lint-backend lint-frontend \
	format format-backend format-frontend \
	build docker-up docker-down docker-build clean

# Default goal
.DEFAULT_GOAL := help

BACKEND_DIR := backend
FRONTEND_DIR := frontend

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

## ----- install -----

install: install-backend install-frontend ## Install backend + frontend dependencies

install-backend: ## Install backend Python dependencies
	cd $(BACKEND_DIR) && pip install -r requirements.txt

install-frontend: ## Install frontend Node dependencies
	cd $(FRONTEND_DIR) && yarn install

## ----- dev -----

dev: ## Run backend and frontend together (Ctrl-C to stop both)
	@$(MAKE) -j 2 dev-backend dev-frontend

dev-backend: ## Run backend dev server (uvicorn --reload)
	cd $(BACKEND_DIR) && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend: ## Run frontend dev server (CRACO)
	cd $(FRONTEND_DIR) && yarn start

## ----- test -----

test: test-backend test-frontend ## Run all tests

test-backend: ## Run backend tests (pytest)
	cd $(BACKEND_DIR) && pytest

test-frontend: ## Run frontend tests (CRA test runner, non-watch)
	cd $(FRONTEND_DIR) && CI=true yarn test

## ----- lint -----

lint: lint-backend lint-frontend ## Run all linters

lint-backend: ## Run backend linters (black, isort, flake8, mypy)
	cd $(BACKEND_DIR) && black --check . && isort --check-only . && flake8 . && mypy app

lint-frontend: ## Run frontend linters (eslint + prettier check)
	cd $(FRONTEND_DIR) && yarn lint && yarn format:check

## ----- format -----

format: format-backend format-frontend ## Auto-format code

format-backend: ## Format backend (black + isort)
	cd $(BACKEND_DIR) && black . && isort .

format-frontend: ## Format frontend (prettier)
	cd $(FRONTEND_DIR) && yarn format

## ----- build -----

build: ## Build production frontend bundle
	cd $(FRONTEND_DIR) && yarn build

## ----- docker -----

docker-build: ## Build all docker images
	docker compose build

docker-up: ## Start all services (mongo + backend + frontend)
	docker compose up -d

docker-down: ## Stop all services
	docker compose down

## ----- clean -----

clean: ## Remove caches and build artifacts
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .mypy_cache -prune -exec rm -rf {} + 2>/dev/null || true
	@rm -rf $(FRONTEND_DIR)/build $(FRONTEND_DIR)/coverage 2>/dev/null || true
	@echo "Cleaned caches and build artifacts"
