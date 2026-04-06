# Blitz-Scale Edge Observer - Makefile
# One-command operations for deployment, demo, and testing

.PHONY: help deploy-backend deploy-edge run-demo test-all test-unit test-load clean lint format setup bootstrap preflight preflight-ci

# Default target
help:
	@echo "Blitz-Scale Edge Observer - Available Commands"
	@echo "=============================================="
	@echo ""
	@echo "Deployment:"
	@echo "  make deploy-backend    - Deploy EKS + Kinesis infrastructure (Terraform)"
	@echo "  make deploy-edge       - Deploy Cloudflare Worker (Wrangler)"
	@echo "  make deploy-all        - Deploy both backend and edge"
	@echo ""
	@echo "Demo:"
	@echo "  make run-demo          - Run full demo (dry-run scaling + test events + client sim)"
	@echo "  make demo-scaling      - Run predictive scaling in dry-run mode"
	@echo "  make demo-client       - Start fantasy client simulator"
	@echo "  make demo-inject       - Inject test fantasy events"
	@echo "  make validate-scaler-dryrun - Validate predictive scaler in dry-run mode"
	@echo "  make validate-scaler-live   - Validate predictive scaler in live mode (staging only)"
	@echo ""
	@echo "Testing:"
	@echo "  make test-all          - Run all test suites"
	@echo "  make test-unit         - Run Python unit tests"
	@echo "  make test-load         - Run k6 load tests"
	@echo "  make lint              - Run linting (Ruff, tfsec)"
	@echo ""
	@echo "Operations:"
	@echo "  make format            - Format code (Ruff)"
	@echo "  make clean             - Clean up local artifacts"
	@echo "  make setup             - Alias for bootstrap"
	@echo "  make bootstrap         - Install local dependencies and validate required tools"
	@echo "  make preflight         - Validate local auth and deployment prerequisites"
	@echo "  make preflight-ci      - Validate CI deployment prerequisites"
	@echo ""

# ==========================================
# Deployment Targets
# ==========================================

deploy-backend:
	@echo "🚀 Deploying Backend Infrastructure (EKS + Kinesis)..."
	cd terraform/eks && terraform init
	cd terraform/eks && terraform plan -out=tfplan
	cd terraform/eks && terraform apply -auto-approve tfplan
	@echo "✅ Backend deployment complete"

deploy-edge:
	@echo "🚀 Deploying Cloudflare Edge Worker..."
	cd edge && npm install
	cd edge && npx wrangler deploy
	@echo "✅ Edge deployment complete"

deploy-all: deploy-backend deploy-edge
	@echo "✅ Full deployment complete"

# ==========================================
# Demo Targets
# ==========================================

run-demo: setup
	@echo "🎮 Starting Blitz-Scale Edge Observer Demo..."
	@echo ""
	@echo "Step 1: Testing predictive scaling (dry-run)..."
	DRY_RUN_MODE=true python3 scaling/scheduled_scaler_lambda.py
	@echo ""
	@echo "Step 2: Injecting test fantasy events..."
	python3 scripts/inject_test_events.py --count 5
	@echo ""
	@echo "Step 3: Starting fantasy client simulator..."
	@echo "(Press Ctrl+C to stop)"
	python3 streaming/fantasy_client_sim.py --mode fantasy --duration 60

demo-scaling:
	@echo "🔄 Running predictive scaling in dry-run mode..."
	DRY_RUN_MODE=true python scaling/scheduled_scaler_lambda.py

demo-client:
	@echo "📱 Starting fantasy client simulator..."
	python3 streaming/fantasy_client_sim.py --mode fantasy

demo-inject:
	@echo "🎯 Injecting test fantasy events..."
	python3 scripts/inject_test_events.py --count 10 --game-id NFL_101

validate-scaler-dryrun:
	@echo "🔍 Validating predictive scaler (dry-run)..."
	DRY_RUN_MODE=true python3 scaling/scheduled_scaler_lambda.py

validate-scaler-live:
	@echo "⚠️  Validating predictive scaler (live mode)"
	@test "$${CONFIRM_LIVE}" = "yes" || (echo "Set CONFIRM_LIVE=yes to run live validation" && exit 1)
	DRY_RUN_MODE=false python3 scaling/scheduled_scaler_lambda.py

sandbox-start:
	@echo "📦 Starting Local Sandbox..."
	docker-compose -f docker-compose.local.yml up -d
	bash scripts/setup_localstack.sh
	@echo "LocalStack and Redis are running."

sandbox-demo:
	@echo "🎮 Local Demo Instructions:"
	@echo "1. Run edge worker:        cd edge && npx wrangler dev"
	@echo "2. Run local poller:       python3 streaming/local_kinesis_poller.py"
	@echo "3. Run client simulator:   python3 streaming/fantasy_client_sim.py --url ws://localhost:8787/realtime"
	@echo "4. Inject test events:     python3 scripts/inject_test_events.py --endpoint-url http://localhost:4566"

sandbox-stop:
	@echo "🛑 Stopping Local Sandbox..."
	docker-compose -f docker-compose.local.yml down

# ==========================================
# Testing Targets
# ==========================================

test-all: test-unit test-load lint
	@echo "✅ All tests passed"

test-unit:
	@echo "🧪 Running unit tests..."
	pip install pytest pytest-asyncio aioredis boto3 pydantic kubernetes aws-xray-sdk \
		opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-botocore aiohttp
	PYTHONPATH=. pytest tests/unit/ -v

test-load:
	@echo "⚡ Running load tests with k6..."
	@which k6 > /dev/null || (echo "❌ k6 not installed. Install: https://k6.io/docs/get-started/installation/" && exit 1)
	k6 run tests/load/k6_load_test.js

# ==========================================
# Linting & Formatting
# ==========================================

lint:
	@echo "🔍 Running linters..."
	@echo "Python (Ruff)..."
	@which ruff > /dev/null && ruff check . || echo "⚠️  Ruff not installed: pip install ruff"
	@echo "Terraform (tfsec)..."
	@which tfsec > /dev/null && tfsec . || echo "⚠️  tfsec not installed: https://aquasecurity.github.io/tfsec/"
	@echo "JavaScript..."
	@cd edge && npm run lint 2>/dev/null || echo "⚠️  ESLint not configured"

format:
	@echo "✨ Formatting code..."
	@which ruff > /dev/null && ruff format . || echo "⚠️  Ruff not installed: pip install ruff"
	@echo "✅ Code formatted"

# ==========================================
# Setup & Utilities
# ==========================================

setup:
	bash scripts/bootstrap.sh

bootstrap:
	bash scripts/bootstrap.sh

preflight:
	bash scripts/preflight.sh

preflight-ci:
	bash scripts/preflight-ci.sh

clean:
	@echo "🧹 Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.zip" -path "*/terraform/*" -delete 2>/dev/null || true
	find . -type d -name ".terraform" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Cleanup complete"

# ==========================================
# AWS Operations
# ==========================================

logs-scaler:
	@echo "📜 Viewing predictive scaler logs..."
	aws logs tail /aws/lambda/blitz-edge-scheduled-scaler --follow

logs-processor:
	@echo "📜 Viewing delta processor logs..."
	aws logs tail /aws/lambda/fantasy-data-delta-processor --follow

invoke-scaler:
	@echo "🔔 Manually invoking predictive scaler..."
	aws lambda invoke \
		--function-name blitz-edge-scheduled-scaler \
		--payload '{}' \
		response.json
	@cat response.json && rm response.json

# ==========================================
# Terraform Operations
# ==========================================

plan:
	@echo "📋 Running Terraform plan..."
	cd terraform/eks && terraform plan

destroy:
	@echo "⚠️  Destroying infrastructure..."
	@echo "Are you sure? [y/N] " && read ans && [ $${ans:-N} = y ] || exit 1
	cd terraform/eks && terraform destroy -auto-approve
	@echo "✅ Infrastructure destroyed"
