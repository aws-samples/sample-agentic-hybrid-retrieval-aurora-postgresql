from aws_cdk import (
    CfnOutput,
    CfnParameter,
    Duration,
    RemovalPolicy,
    Stack,
    aws_ec2 as ec2,
    aws_lambda as _lambda,
    aws_rds as rds,
    aws_s3 as s3,
)
from constructs import Construct

class AgenticRetrievalCoreStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        self.raw_bucket = s3.Bucket(self, "RawSourceLandingBucket", versioned=True)
        self.curated_bucket = s3.Bucket(self, "CuratedSourceBucket", versioned=True)

        database_name = CfnParameter(
            self,
            "DatabaseName",
            type="String",
            default="retrieval",
            description="Initial Aurora PostgreSQL database name.",
        )
        client_access_cidr = CfnParameter(
            self,
            "ClientAccessCidr",
            type="String",
            default="127.0.0.1/32",
            description=(
                "CIDR allowed to connect to Aurora on port 5432. "
                "Pass your current /32 client IP for a local workshop connection."
            ),
        )
        retrieval_api_url = CfnParameter(
            self,
            "RetrievalApiUrl",
            type="String",
            default="",
            description="Optional base URL for the retrieval API used by the Bedrock Agent action Lambda.",
        )
        self.database_name = database_name.value_as_string

        self.vpc = ec2.Vpc(
            self,
            "RetrievalVpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
        )

        self.db_security_group = ec2.SecurityGroup(
            self,
            "AuroraSecurityGroup",
            vpc=self.vpc,
            description="Controls direct workshop access to the Aurora PostgreSQL retrieval cluster.",
            allow_all_outbound=True,
        )
        self.db_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(client_access_cidr.value_as_string),
            connection=ec2.Port.tcp(5432),
            description="Client access for workshop schema load and local API connection.",
        )

        self.db_secret = rds.DatabaseSecret(
            self,
            "AuroraConnectionSecret",
            username="retrieval_admin",
        )

        self.cluster = rds.DatabaseCluster(
            self,
            "AuroraPostgresRetrievalCluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.of("18.3", "18")
            ),
            credentials=rds.Credentials.from_secret(self.db_secret),
            default_database_name=database_name.value_as_string,
            writer=rds.ClusterInstance.serverless_v2(
                "writer",
                publicly_accessible=True,
                enable_performance_insights=True,
            ),
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_groups=[self.db_security_group],
            serverless_v2_min_capacity=0.5,
            serverless_v2_max_capacity=2,
            backup=rds.BackupProps(retention=Duration.days(1)),
            cloudwatch_logs_exports=["postgresql"],
            deletion_protection=False,
            removal_policy=RemovalPolicy.SNAPSHOT,
        )

        # Placeholder action Lambda for Bedrock Agent action groups.
        self.action_lambda = _lambda.Function(
            self,
            "BedrockAgentActionLambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="lambda_handler.lambda_handler",
            code=_lambda.Code.from_asset("../../bedrock-agent"),
            timeout=Duration.seconds(60),
            environment={
                "RETRIEVAL_API_URL": retrieval_api_url.value_as_string,
                "AURORA_SECRET_ARN": self.db_secret.secret_arn,
                "AURORA_CLUSTER_ENDPOINT": self.cluster.cluster_endpoint.hostname,
                "AURORA_DATABASE_NAME": self.database_name,
            },
        )
        self.db_secret.grant_read(self.action_lambda)

        CfnOutput(self, "AuroraClusterIdentifier", value=self.cluster.cluster_identifier)
        CfnOutput(self, "AuroraEndpoint", value=self.cluster.cluster_endpoint.socket_address)
        CfnOutput(self, "AuroraReaderEndpoint", value=self.cluster.cluster_read_endpoint.socket_address)
        CfnOutput(self, "AuroraSecretArn", value=self.db_secret.secret_arn)
        CfnOutput(self, "AuroraDatabaseName", value=self.database_name)
        CfnOutput(
            self,
            "AuroraDatabaseUrlCommand",
            value=f"scripts/aurora_database_url.sh {self.db_secret.secret_arn} {self.cluster.cluster_endpoint.hostname} {self.database_name}",
        )
