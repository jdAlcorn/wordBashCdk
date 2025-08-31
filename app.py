#!/usr/bin/env python3
import aws_cdk as cdk
from network_stack import NetworkStack
from data_stack import DataStack
from compute_stack import ComputeStack

app = cdk.App()

# Get configuration from context
env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region=app.node.try_get_context("region")
)

# Deploy stacks in dependency order
network_stack = NetworkStack(app, "WordBashNetworkStack", env=env)
data_stack = DataStack(app, "WordBashDataStack", env=env)
compute_stack = ComputeStack(
    app, "WordBashComputeStack",
    vpc=network_stack.vpc,
    table=data_stack.table,
    env=env
)

# Stack dependencies
compute_stack.add_dependency(network_stack)
compute_stack.add_dependency(data_stack)

app.synth()
