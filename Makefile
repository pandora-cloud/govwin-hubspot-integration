.PHONY: help install install-dev test lint format typecheck deploy destroy clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install production dependencies
	pip install -r requirements.txt

install-dev: ## Install development dependencies
	pip install -r requirements-dev.txt

test: ## Run unit tests
	pytest tests/unit -v

test-all: ## Run all tests including integration
	pytest tests/ -v

lint: ## Run linter
	ruff check src/ tests/

format: ## Auto-format code
	ruff format src/ tests/
	ruff check --fix src/ tests/

typecheck: ## Run type checker
	mypy src/

deploy: ## Deploy infrastructure with Terraform
	cd terraform && terraform init && terraform apply

plan: ## Preview Terraform changes
	cd terraform && terraform init && terraform plan

destroy: ## Destroy all Terraform-managed infrastructure
	cd terraform && terraform destroy

package: ## Package Lambda functions
	@echo "Cleaning __pycache__ before packaging..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "Packaging Lambda functions..."
	pip install -r requirements.txt -t package/python/
	cd package && zip -r ../lambda-layer.zip python/

clean: ## Remove build artifacts
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache
	rm -rf dist build *.egg-info
	rm -rf package/ lambda-layer.zip
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
