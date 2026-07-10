#!/usr/bin/env bash
#
# Provision the AgentCore Gateway + Runtime for the hybrid retrieval engine.
#
# What it does:
#   1. Resolves the dedicated AgentCoreGatewayLambdaArn deployed by CDK.
#   2. Runs the `@aws/agentcore` CLI against agentcore.json to create/update the
#      BYO Runtime and Gateway target.
#
# The Gateway Lambda ARN is injected into agentcore.json via the GATEWAY_LAMBDA_ARN
# environment variable (the target's lambdaArn is "${GATEWAY_LAMBDA_ARN}"). CDK
# owns the Lambda code package and network/IAM posture; this script only wires the
# deployed Lambda into AgentCore.
#
# Prerequisites:
#   - Node.js 20.19+ and the `@aws/agentcore` CLI (npx @aws/agentcore@0.18.0 ...).
#   - AWS credentials for the target account/region (us-east-1).
#   - A deployed AgenticRetrievalAgentCoreGatewayStack with AgentCoreGatewayLambdaArn output.
#
# Usage:
#   export AWS_REGION=us-east-1
#   cd infra/cdk
#   ENABLE_AGENTCORE_GATEWAY_STACK=1 npx aws-cdk deploy AgenticRetrievalCoreStack AgenticRetrievalAgentCoreGatewayStack
#   cd ../..
#   agentcore/provision.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTCORE_CLI="${AGENTCORE_CLI:-npx -y @aws/agentcore@0.18.0}"
STACK_NAME="${STACK_NAME:-AgenticRetrievalAgentCoreGatewayStack}"
GATEWAY_LAMBDA_ARN_OUTPUT="${GATEWAY_LAMBDA_ARN_OUTPUT:-AgentCoreGatewayLambdaArn}"

export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"

need_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[provision] ERROR: '$1' is required but was not found on PATH." >&2
    exit 1
  fi
}

need_command aws
need_command node
need_command npx

node - <<'NODE'
const [major, minor] = process.versions.node.split('.').map(Number);
if (major < 20 || (major === 20 && minor < 19)) {
  console.error(`[provision] ERROR: Node.js 20.19+ is required; found ${process.versions.node}.`);
  process.exit(1);
}
NODE

echo "[provision] region: $AWS_REGION"
echo "[provision] stack: $STACK_NAME"
echo "[provision] node: $(node --version)"
echo "[provision] agentcore cli: $AGENTCORE_CLI"

AWS_ACCOUNT="$(aws sts get-caller-identity --query Account --output text --region "$AWS_REGION")"
if [[ -z "$AWS_ACCOUNT" || "$AWS_ACCOUNT" == "None" ]]; then
  echo "[provision] ERROR: AWS credentials are not valid for region $AWS_REGION." >&2
  exit 1
fi
echo "[provision] aws account: $AWS_ACCOUNT"

if [[ ! -f "$ROOT_DIR/agentcore.json" ]]; then
  echo "[provision] ERROR: $ROOT_DIR/agentcore.json not found." >&2
  exit 1
fi
if [[ ! -f "$ROOT_DIR/gateway/retrieval_tools.json" ]]; then
  echo "[provision] ERROR: $ROOT_DIR/gateway/retrieval_tools.json not found." >&2
  exit 1
fi

if [[ -z "${GATEWAY_LAMBDA_ARN:-}" ]]; then
  echo "[provision] resolving $GATEWAY_LAMBDA_ARN_OUTPUT from CloudFormation"
  GATEWAY_LAMBDA_ARN="$(
    aws cloudformation describe-stacks \
      --stack-name "$STACK_NAME" \
      --region "$AWS_REGION" \
      --query "Stacks[0].Outputs[?OutputKey=='${GATEWAY_LAMBDA_ARN_OUTPUT}'].OutputValue | [0]" \
      --output text 2>/dev/null || true
  )"
fi

if [[ -z "${GATEWAY_LAMBDA_ARN:-}" || "$GATEWAY_LAMBDA_ARN" == "None" ]]; then
  cat >&2 <<EOF
[provision] ERROR: could not resolve $GATEWAY_LAMBDA_ARN_OUTPUT.

Deploy the CDK stack first, or export GATEWAY_LAMBDA_ARN explicitly:

  cd infra/cdk
  ENABLE_AGENTCORE_GATEWAY_STACK=1 npx aws-cdk deploy AgenticRetrievalCoreStack AgenticRetrievalAgentCoreGatewayStack
  cd ../..
  export GATEWAY_LAMBDA_ARN=\$(aws cloudformation describe-stacks \\
    --stack-name "$STACK_NAME" \\
    --region "$AWS_REGION" \\
    --query "Stacks[0].Outputs[?OutputKey=='${GATEWAY_LAMBDA_ARN_OUTPUT}'].OutputValue | [0]" \\
    --output text)

EOF
  exit 1
fi

export GATEWAY_LAMBDA_ARN
echo "[provision] gateway Lambda: $GATEWAY_LAMBDA_ARN"

read -r LAMBDA_RUNTIME LAMBDA_HANDLER LAMBDA_VPC_ID < <(
  aws lambda get-function-configuration \
    --function-name "$GATEWAY_LAMBDA_ARN" \
    --region "$AWS_REGION" \
    --query "[Runtime,Handler,VpcConfig.VpcId]" \
    --output text
)

if [[ "$LAMBDA_RUNTIME" != "python3.12" ]]; then
  echo "[provision] ERROR: Gateway Lambda runtime must be python3.12; found '$LAMBDA_RUNTIME'." >&2
  exit 1
fi
if [[ "$LAMBDA_HANDLER" != "handler.lambda_handler" ]]; then
  echo "[provision] ERROR: Gateway Lambda handler must be handler.lambda_handler; found '$LAMBDA_HANDLER'." >&2
  exit 1
fi
if [[ -z "$LAMBDA_VPC_ID" || "$LAMBDA_VPC_ID" == "None" ]]; then
  echo "[provision] ERROR: Gateway Lambda must be VPC-attached so it can reach Aurora." >&2
  exit 1
fi
echo "[provision] lambda runtime/handler/vpc: $LAMBDA_RUNTIME / $LAMBDA_HANDLER / $LAMBDA_VPC_ID"

echo "[provision] running AgentCore CLI against agentcore.json"
read -r -a AGENTCORE_CLI_ARGS <<< "$AGENTCORE_CLI"
( cd "$ROOT_DIR" && "${AGENTCORE_CLI_ARGS[@]}" provision --config agentcore.json )

echo "[provision] done."
