from aws_cdk import (
    Aws,
    BundlingOptions,
    CfnOutput,
    CfnParameter,
    Duration,
    RemovalPolicy,
    Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
)
from constructs import Construct

from stacks.core_stack import AgenticRetrievalCoreStack


class AgenticRetrievalAgentCoreGatewayStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        core_stack: AgenticRetrievalCoreStack,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)
        self.add_dependency(core_stack)

        bedrock_embedding_model = CfnParameter(
            self,
            "BedrockEmbeddingModel",
            type="String",
            default="us.cohere.embed-v4:0",
            description="Bedrock embedding model or inference profile used by AgentCore Gateway vector tools.",
        )

        gateway_security_group = ec2.SecurityGroup(
            self,
            "AgentCoreGatewayLambdaSecurityGroup",
            vpc=core_stack.vpc,
            description="Egress for the optional AgentCore Gateway Lambda.",
            allow_all_outbound=True,
        )
        ec2.CfnSecurityGroupIngress(
            self,
            "AuroraIngressFromAgentCoreGateway",
            group_id=core_stack.db_security_group.security_group_id,
            ip_protocol="tcp",
            from_port=5432,
            to_port=5432,
            source_security_group_id=gateway_security_group.security_group_id,
            description="AgentCore Gateway Lambda access to Aurora PostgreSQL.",
        )

        endpoint_security_group = ec2.SecurityGroup(
            self,
            "VpcEndpointSecurityGroup",
            vpc=core_stack.vpc,
            description="Interface endpoint access for private Lambda calls to AWS APIs.",
            allow_all_outbound=True,
        )
        endpoint_security_group.add_ingress_rule(
            peer=gateway_security_group,
            connection=ec2.Port.tcp(443),
            description="Allow AgentCore Gateway Lambda to call private AWS service endpoints.",
        )

        endpoint_subnets = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC)
        ec2.InterfaceVpcEndpoint(
            self,
            "SecretsManagerEndpoint",
            vpc=core_stack.vpc,
            service=ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
            subnets=endpoint_subnets,
            security_groups=[endpoint_security_group],
            private_dns_enabled=True,
        )
        ec2.InterfaceVpcEndpoint(
            self,
            "BedrockRuntimeEndpoint",
            vpc=core_stack.vpc,
            service=ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME,
            subnets=endpoint_subnets,
            security_groups=[endpoint_security_group],
            private_dns_enabled=True,
        )

        gateway_function_name = f"{Aws.STACK_NAME}-agentcore-gateway"
        gateway_log_group = logs.LogGroup(
            self,
            "AgentCoreGatewayLambdaLogGroup",
            log_group_name=f"/aws/lambda/{gateway_function_name}",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        gateway_lambda = _lambda.Function(
            self,
            "AgentCoreGatewayLambda",
            function_name=gateway_function_name,
            runtime=_lambda.Runtime.PYTHON_3_12,
            architecture=_lambda.Architecture.X86_64,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset(
                "../../agentcore/gateway",
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    platform="linux/amd64",
                    command=[
                        "bash",
                        "-c",
                        (
                            "python -m pip install --no-cache-dir "
                            "-r /asset-input/requirements.txt -t /asset-output "
                            "&& cp /asset-input/handler.py /asset-output/ "
                            "&& cp /asset-input/retrieval_tools.json /asset-output/"
                        ),
                    ],
                ),
            ),
            timeout=Duration.seconds(60),
            memory_size=1024,
            log_group=gateway_log_group,
            vpc=core_stack.vpc,
            vpc_subnets=endpoint_subnets,
            allow_public_subnet=True,
            security_groups=[gateway_security_group],
            environment={
                "AURORA_SECRET_ARN": core_stack.db_secret.secret_arn,
                "AURORA_CLUSTER_ENDPOINT": core_stack.cluster.cluster_endpoint.hostname,
                "AURORA_DATABASE_NAME": core_stack.database_name,
                "BEDROCK_EMBEDDING_MODEL": bedrock_embedding_model.value_as_string,
                "EMBED_DIM": "1024",
            },
        )
        core_stack.db_secret.grant_read(gateway_lambda)
        gateway_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:{Aws.PARTITION}:bedrock:{Aws.REGION}:{Aws.ACCOUNT_ID}:inference-profile/{bedrock_embedding_model.value_as_string}",
                    f"arn:{Aws.PARTITION}:bedrock:*::foundation-model/cohere.embed-v4:0",
                ],
            )
        )

        CfnOutput(self, "AgentCoreGatewayLambdaArn", value=gateway_lambda.function_arn)
