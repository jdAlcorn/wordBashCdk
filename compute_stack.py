from aws_cdk import (
    Stack, CfnOutput, Duration,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
    aws_iam as iam,
    aws_dynamodb as dynamodb,
    aws_ssm as ssm,
    aws_applicationautoscaling as appscaling,
    aws_ecr_assets as ecr_assets
)
from constructs import Construct

class ComputeStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.Vpc, 
                 table: dynamodb.Table, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Get configurable paths from context
        web_path = self.node.try_get_context("web_image_path") or "../web"
        game_path = self.node.try_get_context("game_image_path") or "../game"
        
        # ECS Cluster
        cluster = ecs.Cluster(self, "WordBashCluster", vpc=vpc)

        # Application Load Balancer
        alb_sg = self._create_alb_security_group(vpc)
        alb = elbv2.ApplicationLoadBalancer(
            self, "WordBashALB",
            vpc=vpc,
            internet_facing=True,
            security_group=alb_sg
        )

        # Build Docker images for linux/amd64 platform
        web_image = ecr_assets.DockerImageAsset(
            self, "WebImage", 
            directory=web_path,
            platform=ecr_assets.Platform.LINUX_AMD64
        )
        game_image = ecr_assets.DockerImageAsset(
            self, "GameImage", 
            directory=game_path,
            platform=ecr_assets.Platform.LINUX_AMD64
        )
        
        # Create services
        service_sg = self._create_service_security_group(vpc, alb_sg)
        web_service = self._create_web_service(cluster, web_image, table, service_sg)
        game_service = self._create_game_service(cluster, game_image, table, service_sg)
        
        # Target groups and listener rules
        web_tg = self._create_web_target_group(vpc, web_service)
        game_tg = self._create_game_target_group(vpc, game_service)

        # HTTP listener with web service as default (catches everything)
        http_listener = alb.add_listener(
            "HttpListener",
            port=80,
            protocol=elbv2.ApplicationProtocol.HTTP,
            default_action=elbv2.ListenerAction.forward([web_tg])
        )
        
        # WebSocket rule (higher priority overrides default)
        http_listener.add_action(
            "WebSocketRule",
            priority=100,
            conditions=[elbv2.ListenerCondition.path_patterns(["/ws/*"])],
            action=elbv2.ListenerAction.forward([game_tg])
        )
        
        # Store WebSocket endpoint in SSM
        ws_endpoint = f"ws://{alb.load_balancer_dns_name}/ws"
        ws_param_path = "/wordbash/ws_endpoint"
        
        ssm.StringParameter(
            self, "WsEndpointParam",
            parameter_name=ws_param_path,
            string_value=ws_endpoint,
            description="WebSocket endpoint URL for WordBash game connections"
        )
        
        # Grant SSM access to web service
        web_service.task_definition.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter{ws_param_path}"]
            )
        )
        
        # Outputs
        CfnOutput(self, "AlbDnsName", value=alb.load_balancer_dns_name)
        CfnOutput(self, "WebServiceUrl", value=f"http://{alb.load_balancer_dns_name}")
        CfnOutput(self, "WebSocketUrl", value=ws_endpoint)
        CfnOutput(self, "DynamoDbTableName", value=table.table_name)
        CfnOutput(self, "WsEndpointParamPath", value=ws_param_path)
    
    def _create_alb_security_group(self, vpc: ec2.Vpc) -> ec2.SecurityGroup:
        sg = ec2.SecurityGroup(self, "AlbSecurityGroup", vpc=vpc)
        # Allow access from anywhere for debugging
        sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80))
        return sg
    
    def _create_service_security_group(self, vpc: ec2.Vpc, alb_sg: ec2.SecurityGroup) -> ec2.SecurityGroup:
        sg = ec2.SecurityGroup(self, "ServiceSecurityGroup", vpc=vpc)
        sg.add_ingress_rule(alb_sg, ec2.Port.tcp(8080))  # Container port
        return sg
    
    def _create_web_service(self, cluster: ecs.Cluster, image: ecr_assets.DockerImageAsset, 
                           table: dynamodb.Table, security_group: ec2.SecurityGroup) -> ecs.FargateService:
        
        # Task role with DynamoDB permissions
        task_role = iam.Role(
            self, "WebTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com")
        )
        table.grant_read_write_data(task_role)
        
        # Task definition
        task_def = ecs.FargateTaskDefinition(
            self, "WebTaskDef",
            memory_limit_mib=1024,
            cpu=512,
            task_role=task_role
        )
        
        # Container with environment variables
        container = task_def.add_container(
            "WebContainer",
            image=ecs.ContainerImage.from_docker_image_asset(image),
            port_mappings=[ecs.PortMapping(container_port=8080)],
            environment={
                "AWS_REGION": self.region,
                "LOG_LEVEL": "INFO",
                "DDB_TABLE_NAME": table.table_name,
                "WS_ENDPOINT_PARAM": "/wordbash/ws_endpoint",
                "API_BASE_URL": self.node.try_get_context("api_base_url") or ""
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="web",
                log_group=logs.LogGroup(
                    self, "WebLogGroup",
                    log_group_name="/aws/ecs/wordbash-web",
                    retention=logs.RetentionDays.TWO_WEEKS
                )
            )
        )
        
        # Fargate service
        service = ecs.FargateService(
            self, "WebService",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            security_groups=[security_group]
        )
        
        # Auto scaling
        scaling = service.auto_scale_task_count(max_capacity=4, min_capacity=1)
        scaling.scale_on_cpu_utilization(
            "WebCpuScaling",
            target_utilization_percent=50
        )
        
        return service
    
    def _create_game_service(self, cluster: ecs.Cluster, image: ecr_assets.DockerImageAsset,
                            table: dynamodb.Table, security_group: ec2.SecurityGroup) -> ecs.FargateService:
        
        # Task role with DynamoDB permissions  
        task_role = iam.Role(
            self, "GameTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com")
        )
        table.grant_read_write_data(task_role)
        
        # Task definition
        task_def = ecs.FargateTaskDefinition(
            self, "GameTaskDef",
            memory_limit_mib=1024,
            cpu=512,
            task_role=task_role
        )
        
        # Container
        container = task_def.add_container(
            "GameContainer",
            image=ecs.ContainerImage.from_docker_image_asset(image),
            port_mappings=[ecs.PortMapping(container_port=8080)],
            environment={
                "AWS_REGION": self.region,
                "LOG_LEVEL": "INFO", 
                "DDB_TABLE_NAME": table.table_name
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="game",
                log_group=logs.LogGroup(
                    self, "GameLogGroup",
                    log_group_name="/aws/ecs/wordbash-game",
                    retention=logs.RetentionDays.TWO_WEEKS
                )
            )
        )
        
        # Fargate service
        service = ecs.FargateService(
            self, "GameService",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            security_groups=[security_group]
        )
        
        # Auto scaling
        scaling = service.auto_scale_task_count(max_capacity=4, min_capacity=1)
        scaling.scale_on_cpu_utilization(
            "GameCpuScaling",
            target_utilization_percent=50
        )
        
        return service
    
    def _create_web_target_group(self, vpc: ec2.Vpc, service: ecs.FargateService) -> elbv2.ApplicationTargetGroup:
        tg = elbv2.ApplicationTargetGroup(
            self, "WebTargetGroup",
            vpc=vpc,
            port=8080,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/healthz",
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
                timeout=Duration.seconds(10),
                interval=Duration.seconds(30)
            )
        )
        service.attach_to_application_target_group(tg)
        return tg
    
    def _create_game_target_group(self, vpc: ec2.Vpc, service: ecs.FargateService) -> elbv2.ApplicationTargetGroup:
        # WebSocket-enabled target group with longer idle timeout
        tg = elbv2.ApplicationTargetGroup(
            self, "GameTargetGroup", 
            vpc=vpc,
            port=8080,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/healthz",
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
                timeout=Duration.seconds(10),
                interval=Duration.seconds(30)
            )
        )
        
        # Configure for WebSocket support - ALB handles upgrade automatically
        # Set idle timeout for long-lived WebSocket connections
        cfn_tg = tg.node.default_child
        cfn_tg.add_property_override("TargetGroupAttributes", [
            {"Key": "deregistration_delay.timeout_seconds", "Value": "30"},
            {"Key": "stickiness.enabled", "Value": "true"},
            {"Key": "stickiness.type", "Value": "lb_cookie"}
        ])
        
        service.attach_to_application_target_group(tg)
        return tg
