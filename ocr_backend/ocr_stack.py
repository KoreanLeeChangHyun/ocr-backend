from aws_cdk import (
    Stack,
    aws_lambda as lambda_,
    aws_s3 as s3,
    aws_apigateway as apigw,
    aws_cloudwatch as cloudwatch,
    aws_iam as iam,
    Duration,
    RemovalPolicy,
    CfnOutput
)
from constructs import Construct

class OcrBackendStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # S3 버킷 생성
        bucket = s3.Bucket(
            self, "OcrStorageBucket",
            bucket_name="ocr-temp-storage",
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    expiration=Duration.days(1)
                )
            ],
            public_read_access=False,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            cors=[
                s3.CorsRule(
                    allowed_headers=["*"],
                    allowed_methods=[s3.HttpMethods.GET, s3.HttpMethods.PUT, s3.HttpMethods.POST, s3.HttpMethods.DELETE, s3.HttpMethods.HEAD],
                    allowed_origins=["*"],
                    max_age=3000
                )
            ]
        )

        # Lambda 함수 생성
        function = lambda_.Function(
            self, "OcrFunction",
            runtime=lambda_.Runtime.PYTHON_3_9,
            handler="main.handler",
            code=lambda_.Code.from_asset("ocr_backend/lambda"),
            memory_size=3008,
            timeout=Duration.seconds(60),
            environment={
                "S3_BUCKET": bucket.bucket_name,
                "OPENAI_API_KEY": "{{resolve:ssm:/ocr/OPENAI_API_KEY}}"
            }
        )

        # Lambda 함수에 S3 접근 권한 부여
        bucket.grant_read_write(function)

        # API Gateway 생성
        api = apigw.LambdaRestApi(
            self, "OcrApi",
            handler=function,
            proxy=True,
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=apigw.Cors.DEFAULT_HEADERS,
                max_age=Duration.days(1)
            )
        )

        # CloudWatch 알람
        error_alarm = cloudwatch.Alarm(
            self, "HighErrorRate",
            metric=function.metric_errors(),
            threshold=1,
            evaluation_periods=1,
            period=Duration.minutes(5),
            alarm_description="Lambda 함수의 에러율이 높습니다"
        )

        duration_alarm = cloudwatch.Alarm(
            self, "HighDuration",
            metric=function.metric_duration(),
            threshold=50000,
            evaluation_periods=1,
            period=Duration.minutes(5),
            alarm_description="Lambda 함수의 실행 시간이 너무 깁니다"
        )

        # 출력값 설정
        CfnOutput(self, "ApiEndpoint", value=api.url)
        CfnOutput(self, "BucketName", value=bucket.bucket_name)
