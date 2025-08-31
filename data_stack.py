from aws_cdk import Stack, CfnOutput, RemovalPolicy, aws_dynamodb as dynamodb
from constructs import Construct

class DataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # DynamoDB table for WordBash games
        self.table = dynamodb.Table(
            self, "WordBashGamesTable",
            table_name="wordbash_games",
            partition_key=dynamodb.Attribute(
                name="game_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,  # On-demand billing
            removal_policy=RemovalPolicy.RETAIN if Stack.of(self).node.try_get_context("keep_data") else RemovalPolicy.DESTROY
        )
        
        # CloudFormation exports for cross-stack references
        CfnOutput(
            self, "TableArn",
            value=self.table.table_arn,
            export_name=f"{self.stack_name}-TableArn"
        )
        
        CfnOutput(
            self, "TableName",
            value=self.table.table_name,
            export_name=f"{self.stack_name}-TableName"
        )
