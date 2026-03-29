#!/bin/bash
# Package Lambda dependencies for the predictive scaler
# Usage: ./scripts/package_lambda.sh

set -e

echo "📦 Packaging Lambda dependencies..."

# Create temporary directory
mkdir -p /tmp/lambda_layer/python
cd /tmp/lambda_layer

# Install dependencies
pip install --target=python \
    boto3 \
    kubernetes \
    botocore \
    urllib3 \
    certifi \
    charset-normalizer \
    idna \
    requests \
    six \
    python-dateutil \
    pyyaml \
    google-auth \
    oauthlib \
    requests-oauthlib \
    --quiet

# Remove unnecessary files to reduce size
find python -name "*.pyc" -delete
find python -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find python -name "*.dist-info" -type d -exec rm -rf {} + 2>/dev/null || true

# Create zip file
zip -r lambda_layer.zip python/ -q

# Move to terraform directory
mv lambda_layer.zip /home/kindson/Blitz-Scale\ Edge\ Observer/blitz-scale-edge-observer/terraform/eks/

# Cleanup
cd /
rm -rf /tmp/lambda_layer

echo "✅ Lambda layer packaged: terraform/eks/lambda_layer.zip"
ls -lh /home/kindson/Blitz-Scale\ Edge\ Observer/blitz-scale-edge-observer/terraform/eks/lambda_layer.zip
