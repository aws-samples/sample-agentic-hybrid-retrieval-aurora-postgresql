from aws_cdk import CfnParameter, Stack, Duration, aws_s3 as s3, aws_secretsmanager as secretsmanager, aws_lambda as _lambda
from constructs import Construct

class AgenticRetrievalCoreStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        self.raw_bucket = s3.Bucket(self, "RawSourceLandingBucket", versioned=True)
        self.curated_bucket = s3.Bucket(self, "CuratedSourceBucket", versioned=True)

        retrieval_api_url = CfnParameter(
            self,
            "RetrievalApiUrl",
            type="String",
            default="",
            description="Optional base URL for the retrieval API used by the Bedrock Agent action Lambda.",
        )

        self.db_secret = secretsmanager.Secret(
            self,
            "AuroraConnectionSecret",
            description="Aurora PostgreSQL connection settings for agentic hybrid retrieval demo"
        )

        # Placeholder action Lambda for Bedrock Agent action groups.
        self.action_lambda = _lambda.Function(
            self,
            "BedrockAgentActionLambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="lambda_handler.lambda_handler",
            code=_lambda.Code.from_asset("../../bedrock-agent"),
            timeout=Duration.seconds(60),
            environment={"RETRIEVAL_API_URL": retrieval_api_url.value_as_string},
        )
