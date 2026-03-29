#!/bin/bash

# Blitz-Scale Edge Observer - Secret Injection Utility
# This script populates GitHub Secrets from a local .env.secrets file.

set -e

ENV_FILE=".env.secrets"
EXAMPLE_FILE=".env.secrets.example"

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed. Please install it first."
    exit 1
fi

# Check if authenticated
if ! gh auth status &> /dev/null; then
    echo "Error: Not authenticated with GitHub. Please run 'gh auth login'."
    exit 1
fi

# Check if .env.secrets exists
if [ ! -f "$ENV_FILE" ]; then
    echo "Error: $ENV_FILE not found."
    echo "Please create it using $EXAMPLE_FILE as a template."
    exit 1
fi

echo "Injecting secrets into GitHub..."

# Read .env.secrets and set secrets
while IFS='=' read -r key value || [ -n "$key" ]; do
    # Skip comments and empty lines
    [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
    
    # Trim whitespace
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | xargs)
    
    if [ -n "$key" ] && [ -n "$value" ]; then
        echo "Setting secret: $key"
        echo "$value" | gh secret set "$key"
    fi
done < "$ENV_FILE"

echo "Success! All secrets have been populated."
echo "You can now trigger the production deployment workflow."
