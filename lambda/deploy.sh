#!/usr/bin/env bash
# Build the container image, push it to ECR and create/update the Lambda function + public Function URL.
# Idempotent: rerun after code or data changes. Requires: aws cli (configured), docker (buildx), uv.
#
#   ./lambda/deploy.sh            # full build + deploy
#   ./lambda/deploy.sh --no-build # only update configuration / URL
set -euo pipefail
cd "$(dirname "$0")/.."

NAME="${LCSH_LAMBDA_NAME:-lcsh-validator}"
REGION="${AWS_REGION:-$(aws configure get region || echo us-east-1)}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
ECR="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
IMAGE="$ECR/$NAME:latest"
ROLE="$NAME-lambda-role"
MEMORY="${LCSH_LAMBDA_MEMORY:-2048}"
TIMEOUT="${LCSH_LAMBDA_TIMEOUT:-180}"
BUILD=1
[[ "${1:-}" == "--no-build" ]] && BUILD=0

# --- API key from .env (ANTHROPIC_KEY=...) -------------------------------------------------------
if [[ -z "${ANTHROPIC_KEY:-}" && -f .env ]]; then
  ANTHROPIC_KEY="$(grep -E '^ANTHROPIC_KEY=' .env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '[:space:]')"
fi
[[ -n "${ANTHROPIC_KEY:-}" ]] || { echo "ANTHROPIC_KEY not set (put ANTHROPIC_KEY=... in .env)"; exit 1; }

# --- image ---------------------------------------------------------------------------------------
if [[ $BUILD == 1 ]]; then
  # runtime needs only anthropic + pyyaml; lxml/pymupdf are build-time (data extraction) deps
  uv export --no-dev --no-hashes --no-emit-project --frozen | grep -viE '^(lxml|pymupdf)==' > lambda/requirements.txt
  aws ecr describe-repositories --repository-names "$NAME" --region "$REGION" >/dev/null 2>&1 \
    || aws ecr create-repository --repository-name "$NAME" --region "$REGION" --image-scanning-configuration scanOnPush=false >/dev/null
  aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR" >/dev/null
  echo "building + pushing $IMAGE (arm64)"
  docker buildx build --platform linux/arm64 --provenance=false --sbom=false -f lambda/Dockerfile -t "$IMAGE" --push .
fi

# --- role ----------------------------------------------------------------------------------------
# LCSH_LAMBDA_ROLE names an existing execution role (only CloudWatch Logs access is needed).
# Otherwise a dedicated role is created; if the AWS user may not create roles, fall back to
# lambda_basic_execution when it exists.
ROLE="${LCSH_LAMBDA_ROLE:-$ROLE}"
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  echo "creating role $ROLE"
  if aws iam create-role --role-name "$ROLE" --assume-role-policy-document '{
      "Version": "2012-10-17",
      "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}' >/dev/null; then
    aws iam attach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    echo "waiting for the role to propagate"; sleep 12
  elif aws iam get-role --role-name lambda_basic_execution >/dev/null 2>&1; then
    echo "cannot create roles with this AWS user; using existing role lambda_basic_execution"
    ROLE=lambda_basic_execution
  else
    echo "cannot create role $ROLE and no fallback role found; set LCSH_LAMBDA_ROLE to an existing Lambda execution role"; exit 1
  fi
fi
ROLE_ARN="$(aws iam get-role --role-name "$ROLE" --query Role.Arn --output text)"
ENV_JSON="{\"Variables\":{\"ANTHROPIC_API_KEY\":\"$ANTHROPIC_KEY\",\"LCSH_MODEL\":\"${LCSH_MODEL:-claude-haiku-5-5}\"}}"

# --- function ------------------------------------------------------------------------------------
if aws lambda get-function --function-name "$NAME" --region "$REGION" >/dev/null 2>&1; then
  if [[ $BUILD == 1 ]]; then
    echo "updating code"
    aws lambda update-function-code --function-name "$NAME" --region "$REGION" --image-uri "$IMAGE" --publish >/dev/null
    aws lambda wait function-updated --function-name "$NAME" --region "$REGION"
  fi
  echo "updating configuration"
  aws lambda update-function-configuration --function-name "$NAME" --region "$REGION" \
    --memory-size "$MEMORY" --timeout "$TIMEOUT" --environment "$ENV_JSON" >/dev/null
  aws lambda wait function-updated --function-name "$NAME" --region "$REGION"
else
  echo "creating function $NAME"
  aws lambda create-function --function-name "$NAME" --region "$REGION" --package-type Image --code ImageUri="$IMAGE" \
    --role "$ROLE_ARN" --architectures arm64 --memory-size "$MEMORY" --timeout "$TIMEOUT" --environment "$ENV_JSON" \
    --description "LCSH subject heading validator (SHM rules + Claude Haiku 5.5)" >/dev/null
  aws lambda wait function-active --function-name "$NAME" --region "$REGION"
fi
# no reserved-concurrency cap (it made parallel batches fail with HTTP 429); set
# LCSH_LAMBDA_CONCURRENCY to cap spend if the public URL ever gets abused
if [[ -n "${LCSH_LAMBDA_CONCURRENCY:-}" ]]; then
  aws lambda put-function-concurrency --function-name "$NAME" --region "$REGION" --reserved-concurrent-executions "$LCSH_LAMBDA_CONCURRENCY" >/dev/null
else
  aws lambda delete-function-concurrency --function-name "$NAME" --region "$REGION" >/dev/null 2>&1 || true
fi

# --- public URL ----------------------------------------------------------------------------------
CORS='{"AllowOrigins":["*"],"AllowMethods":["GET","POST"],"AllowHeaders":["content-type"],"MaxAge":86400}'
if aws lambda get-function-url-config --function-name "$NAME" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-url-config --function-name "$NAME" --region "$REGION" --auth-type NONE --cors "$CORS" >/dev/null
else
  aws lambda create-function-url-config --function-name "$NAME" --region "$REGION" --auth-type NONE --cors "$CORS" >/dev/null
fi
aws lambda add-permission --function-name "$NAME" --region "$REGION" --statement-id public-function-url \
  --action lambda:InvokeFunctionUrl --principal '*' --function-url-auth-type NONE >/dev/null 2>&1 || true
URL="$(aws lambda get-function-url-config --function-name "$NAME" --region "$REGION" --query FunctionUrl --output text)"

# --- tell the web page where the API is ----------------------------------------------------------
# keep the feedback URL line (written by deploy_feedback.sh) intact
{ echo '// written by lambda/deploy.sh and lambda/deploy_feedback.sh'; grep -v 'LCSH_API_URL\|^//' docs/config.js 2>/dev/null || true; printf 'window.LCSH_API_URL = "%s";\n' "$URL"; } > docs/config.js.tmp
mv docs/config.js.tmp docs/config.js
echo
echo "function URL: $URL"
echo "docs/config.js updated; test with:"
echo "  curl -s -X POST '$URL' -H 'content-type: application/json' -d '{\"heading\":\"Taxation--France--Paris\"}' | python3 -m json.tool | head -40"
