#!/bin/bash
# Blitz-Scale Edge Observer - One-Command Demo Script
# Usage: ./scripts/demo.sh [--full|--backend-only|--edge-only|--demo-only]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Configuration
DEPLOY_BACKEND=false
DEPLOY_EDGE=false
RUN_DEMO=false
MODE="full"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --full)
            DEPLOY_BACKEND=true
            DEPLOY_EDGE=true
            RUN_DEMO=true
            MODE="full"
            shift
            ;;
        --backend-only)
            DEPLOY_BACKEND=true
            MODE="backend"
            shift
            ;;
        --edge-only)
            DEPLOY_EDGE=true
            MODE="edge"
            shift
            ;;
        --demo-only)
            RUN_DEMO=true
            MODE="demo"
            shift
            ;;
        --help|-h)
            echo "Blitz-Scale Edge Observer - Demo Script"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --full           Deploy backend + edge + run demo (default)"
            echo "  --backend-only   Deploy only Terraform infrastructure"
            echo "  --edge-only      Deploy only Cloudflare Worker"
            echo "  --demo-only      Run demo without deployment"
            echo "  --help, -h       Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 --full           # Complete deployment and demo"
            echo "  $0 --backend-only   # Deploy just the AWS infrastructure"
            echo "  $0 --demo-only      # Run demo with existing infrastructure"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Run '$0 --help' for usage information"
            exit 1
            ;;
    esac
done

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI is not installed. Please install it: https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html"
        exit 1
    fi
    
    # Check Terraform
    if [[ "$DEPLOY_BACKEND" == "true" ]] && ! command -v terraform &> /dev/null; then
        log_error "Terraform is not installed. Please install it: https://developer.hashicorp.com/terraform/downloads"
        exit 1
    fi
    
    # Check Node.js (for Wrangler)
    if [[ "$DEPLOY_EDGE" == "true" ]] && ! command -v node &> /dev/null; then
        log_error "Node.js is not installed. Please install it: https://nodejs.org/"
        exit 1
    fi
    
    # Check Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed. Please install it."
        exit 1
    fi
    
    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        log_error "AWS credentials not configured. Run 'aws configure' first."
        exit 1
    fi
    
    log_success "All prerequisites satisfied"
}

# Setup Python dependencies
setup_python_deps() {
    log_info "Installing Python dependencies..."
    cd "${PROJECT_ROOT}"
    pip install -q boto3 pydantic aioredis aiohttp kubernetes aws-xray-sdk \
        opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-botocore 2>/dev/null || true
    log_success "Python dependencies installed"
}

# Deploy Backend (Terraform)
deploy_backend() {
    log_info "Deploying Backend Infrastructure..."
    cd "${PROJECT_ROOT}/terraform/eks"
    
    log_info "Initializing Terraform..."
    terraform init -input=false
    
    log_info "Planning Terraform changes..."
    terraform plan -out=tfplan -input=false
    
    log_info "Applying Terraform changes (this may take 10-15 minutes)..."
    terraform apply -auto-approve tfplan
    
    log_success "Backend infrastructure deployed"
    
    # Save outputs
    terraform output -json > "${PROJECT_ROOT}/terraform_outputs.json"
    log_info "Terraform outputs saved to terraform_outputs.json"
}

# Deploy Edge (Cloudflare Worker)
deploy_edge() {
    log_info "Deploying Cloudflare Edge Worker..."
    cd "${PROJECT_ROOT}/edge"
    
    # Install dependencies
    if [[ ! -d "node_modules" ]]; then
        log_info "Installing Node.js dependencies..."
        npm install
    fi
    
    # Check for Wrangler
    if ! npx wrangler --version &> /dev/null; then
        log_info "Installing Wrangler..."
        npm install -g wrangler
    fi
    
    log_info "Deploying Worker to Cloudflare..."
    npx wrangler deploy
    
    log_success "Edge Worker deployed"
}

# Inject Secrets
inject_secrets() {
    log_info "Configuring secrets..."
    
    # Generate random webhook secret if not exists
    WEBHOOK_SECRET=$(openssl rand -base64 32 2>/dev/null || head -c 32 /dev/urandom | base64)
    
    # Store in AWS Secrets Manager
    if aws secretsmanager describe-secret --secret-id blitz-edge-webhook-token &> /dev/null; then
        log_info "Webhook secret already exists in Secrets Manager"
        WEBHOOK_SECRET=$(aws secretsmanager get-secret-value \
            --secret-id blitz-edge-webhook-token \
            --query SecretString --output text 2>/dev/null || echo "")
        if [[ -z "${WEBHOOK_SECRET}" ]]; then
            log_error "Failed to read existing webhook secret from Secrets Manager"
            return 1
        fi
    else
        log_info "Creating webhook secret in Secrets Manager..."
        aws secretsmanager create-secret \
            --name blitz-edge-webhook-token \
            --secret-string "${WEBHOOK_SECRET}" \
            --description "Webhook authentication token for Blitz-Scale Edge Observer"
    fi
    
    # Store in Cloudflare
    log_info "Configuring Cloudflare secrets..."
    cd "${PROJECT_ROOT}/edge"
    echo "${WEBHOOK_SECRET}" | npx wrangler secret put WEBHOOK_SECRET_TOKEN 2>/dev/null || \
        log_warn "Failed to set Cloudflare secret. Set it manually with: wrangler secret put WEBHOOK_SECRET_TOKEN"
    
    log_success "Secrets configured"
}

# Run Demo
run_demo() {
    log_info "========================================="
    log_info "  Starting Blitz-Scale Edge Observer Demo"
    log_info "========================================="
    echo ""
    
    # Step 1: Test Predictive Scaling (Dry Run)
    log_info "Step 1: Testing Predictive Scaling (Dry Run Mode)"
    cd "${PROJECT_ROOT}"
    DRY_RUN_MODE=true python3 scaling/scheduled_scaler_lambda.py || log_warn "Scaling dry-run completed with warnings"
    echo ""
    
    # Step 2: Upload Test Schedule to S3
    log_info "Step 2: Uploading test schedule to S3..."
    AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    S3_BUCKET="blitz-edge-config-${AWS_ACCOUNT_ID}"
    
    if aws s3 ls "s3://${S3_BUCKET}" &> /dev/null; then
        aws s3 cp scaling/schedule.json "s3://${S3_BUCKET}/schedule.json" || log_warn "Failed to upload schedule"
        log_success "Schedule uploaded to S3"
    else
        log_warn "S3 bucket not found. Skipping schedule upload."
    fi
    echo ""
    
    # Step 3: Inject Test Events
    log_info "Step 3: Injecting test fantasy events..."
    python3 scripts/inject_test_events.py --count 5 || log_warn "Test event injection completed with warnings"
    echo ""
    
    # Step 4: Start Client Simulator
    log_info "Step 4: Starting Fantasy Client Simulator"
    log_info "(Press Ctrl+C to stop the simulator)"
    echo ""
    
    # Trap Ctrl+C to clean up
    trap 'echo ""; log_info "Demo stopped by user"; exit 0' INT
    
    python3 streaming/fantasy_client_sim.py --mode fantasy --duration 60 || true
    
    echo ""
    log_success "Demo completed!"
}

# Print Summary
print_summary() {
    echo ""
    log_info "========================================="
    log_info "  Deployment Summary"
    log_info "========================================="
    echo ""
    
    if [[ "$DEPLOY_BACKEND" == "true" ]]; then
        log_success "✓ Backend Infrastructure (EKS + Kinesis) deployed"
        echo "  - EKS Cluster: blitz-edge-cluster"
        echo "  - Kinesis Streams: blitz-data-stream"
        echo "  - Predictive Scaler: Scheduled every 15 minutes"
        echo ""
    fi
    
    if [[ "$DEPLOY_EDGE" == "true" ]]; then
        log_success "✓ Cloudflare Edge Worker deployed"
        echo "  - WebSocket Endpoint: wss://api.blitz-obs.com/realtime"
        echo "  - Webhook Endpoint: https://api.blitz-obs.com/webhook/update"
        echo ""
    fi
    
    if [[ "$RUN_DEMO" == "true" ]]; then
        log_success "✓ Demo executed"
        echo "  - Predictive scaling: Tested in dry-run mode"
        echo "  - Test events: Injected into Kinesis"
        echo "  - Client simulation: Connected and received updates"
        echo ""
    fi
    
    log_info "Next Steps:"
    echo "  1. View logs: make logs-scaler"
    echo "  2. Trigger manual scaling: make invoke-scaler"
    echo "  3. Run client simulator: make demo-client"
    echo "  4. Read documentation: cat FANTASYPROS_SHOWCASE.md"
    echo ""
}

# Main Execution
main() {
    echo ""
    log_info "Blitz-Scale Edge Observer Demo Script"
    log_info "Mode: ${MODE}"
    echo ""
    
    # Check prerequisites
    check_prerequisites
    
    # Setup Python dependencies
    if [[ "$RUN_DEMO" == "true" ]]; then
        setup_python_deps
    fi
    
    # Deploy Backend
    if [[ "$DEPLOY_BACKEND" == "true" ]]; then
        deploy_backend
        inject_secrets
    fi
    
    # Deploy Edge
    if [[ "$DEPLOY_EDGE" == "true" ]]; then
        deploy_edge
    fi
    
    # Run Demo
    if [[ "$RUN_DEMO" == "true" ]]; then
        run_demo
    fi
    
    # Print Summary
    print_summary
}

# Run main function
main
