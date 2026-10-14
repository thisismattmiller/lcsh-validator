#!/usr/bin/env bash
# Deploy the feedback Lambda (zip, no dependencies beyond boto3 in the runtime) + public Function URL.
# Reports land in s3://$BUCKET/reports/YYYY/MM/DD/<timestamp>-<id>.json. Idempotent.
set -euo pipefail
cd "$(dirname "$0")/.."
NAME="${LCSH_FEEDBACK_NAME:-lcsh-validator-feedback}"
REGION="${AWS_REGION:-$(aws configure get region || echo us-east-1)}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${LCSH_FEEDBACK_BUCKET:-lcsh-validator-feedback-$ACCOUNT}"
ROLE="${LCSH_LAMBDA_ROLE:-lambda_basic_execution}"   # write access is granted by the bucket policy
ROLE_ARN="$(aws iam get-role --role-name "$ROLE" --query Role.Arn --output text)"
ZIP="$(mktemp -d)/feedback.zip"
(cd lambda && zip -q -j "$ZIP" feedback_handler.py)

aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null || aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" >/dev/null
ENV_JSON="{\"Variables\":{\"FEEDBACK_BUCKET\":\"$BUCKET\"}}"
if aws lambda get-function --function-name "$NAME" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$NAME" --region "$REGION" --zip-file "fileb://$ZIP" >/dev/null
  aws lambda wait function-updated --function-name "$NAME" --region "$REGION"
  aws lambda update-function-configuration --function-name "$NAME" --region "$REGION" --environment "$ENV_JSON" --timeout 15 >/dev/null
  aws lambda wait function-updated --function-name "$NAME" --region "$REGION"
else
  aws lambda create-function --function-name "$NAME" --region "$REGION" --runtime python3.14 --architectures arm64 \
    --handler feedback_handler.handler --zip-file "fileb://$ZIP" --role "$ROLE_ARN" --timeout 15 --memory-size 256 \
    --environment "$ENV_JSON" --description "LCSH validator: stores 'report incorrect validation' feedback in S3" >/dev/null
  aws lambda wait function-active --function-name "$NAME" --region "$REGION"
fi
aws lambda delete-function-concurrency --function-name "$NAME" --region "$REGION" >/dev/null 2>&1 || true
CORS='{"AllowOrigins":["*"],"AllowMethods":["POST"],"AllowHeaders":["content-type"],"MaxAge":86400}'
if aws lambda get-function-url-config --function-name "$NAME" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-url-config --function-name "$NAME" --region "$REGION" --auth-type NONE --cors "$CORS" >/dev/null
else
  aws lambda create-function-url-config --function-name "$NAME" --region "$REGION" --auth-type NONE --cors "$CORS" >/dev/null
fi
aws lambda add-permission --function-name "$NAME" --region "$REGION" --statement-id public-function-url \
  --action lambda:InvokeFunctionUrl --principal '*' --function-url-auth-type NONE >/dev/null 2>&1 || true
URL="$(aws lambda get-function-url-config --function-name "$NAME" --region "$REGION" --query FunctionUrl --output text)"
# keep the other URL line in docs/config.js
grep -v 'LCSH_FEEDBACK_URL' docs/config.js > docs/config.js.tmp || true
printf 'window.LCSH_FEEDBACK_URL = "%s";\n' "$URL" >> docs/config.js.tmp
mv docs/config.js.tmp docs/config.js
echo "feedback URL: $URL   bucket: s3://$BUCKET/reports/"
