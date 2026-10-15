"""Create the free-tier Clause Check resources in eu-west-2.

Creates one Lambda function, its Function URL, one DynamoDB table, and an IAM
role for that function. Does not create EC2, NAT, VPC endpoints, Bedrock, or S3.
"""

import json
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import load_settings  # noqa: E402
from scripts.package_lambda import package  # noqa: E402

REGION = "eu-west-2"
FUNCTION_NAME = "clause-check"
TABLE_NAME = "clause-check"
ROLE_NAME = "clause-check-lambda"


def client(name: str):
    return boto3.client(name, region_name=REGION)


def account_id() -> str:
    return boto3.client("sts").get_caller_identity()["Account"]


def ensure_table() -> None:
    dynamodb = client("dynamodb")
    try:
        dynamodb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[{"AttributeName": "review_id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "review_id", "KeyType": "HASH"}],
            BillingMode="PROVISIONED",
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceInUseException":
            raise
    waiter = dynamodb.get_waiter("table_exists")
    waiter.wait(TableName=TABLE_NAME)


def ensure_role(acct: str) -> str:
    iam = boto3.client("iam")
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    try:
        role = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Clause Check Lambda, DynamoDB and its own logs",
        )
        role_arn = role["Role"]["Arn"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
        role_arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:PutItem"],
                "Resource": f"arn:aws:dynamodb:{REGION}:{acct}:table/{TABLE_NAME}",
            },
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": [
                    f"arn:aws:logs:{REGION}:{acct}:log-group:/aws/lambda/{FUNCTION_NAME}",
                    f"arn:aws:logs:{REGION}:{acct}:log-group:/aws/lambda/{FUNCTION_NAME}:*",
                ],
            },
        ],
    }
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="clause-check-runtime",
        PolicyDocument=json.dumps(policy),
    )
    return role_arn


def ensure_function(role_arn: str, archive: Path, settings) -> None:
    lam = client("lambda")
    environment = {
        "Variables": {
            "API_TOKEN": settings.api_token,
            "GEMINI_API_KEY": settings.gemini_api_key or "",
            "GEMINI_MODEL": settings.gemini_model,
            "STORE": "dynamodb",
            "DYNAMODB_TABLE": TABLE_NAME,
        }
    }
    kwargs = dict(
        FunctionName=FUNCTION_NAME,
        Runtime="python3.12",
        Role=role_arn,
        Handler="app.lambda_handler.handler",
        Timeout=30,
        MemorySize=256,
        Environment=environment,
        Architectures=["x86_64"],
    )
    zip_bytes = archive.read_bytes()
    try:
        lam.create_function(Code={"ZipFile": zip_bytes}, Publish=True, **kwargs)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceConflictException":
            raise
        lam.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=zip_bytes, Publish=True)
        _wait_updated(lam)
        lam.update_function_configuration(**kwargs)
    _wait_updated(lam)


def _wait_updated(lam) -> None:
    for _ in range(30):
        state = lam.get_function_configuration(FunctionName=FUNCTION_NAME)
        if state.get("LastUpdateStatus", "Successful") == "Successful" and state.get("State", "Active") == "Active":
            return
        time.sleep(2)
    raise RuntimeError("Lambda function did not become active")


def ensure_url() -> str:
    lam = client("lambda")
    try:
        url = lam.create_function_url_config(FunctionName=FUNCTION_NAME, AuthType="NONE")["FunctionUrl"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceConflictException":
            raise
        url = lam.get_function_url_config(FunctionName=FUNCTION_NAME)["FunctionUrl"]
    for action, statement_id in (
        ("lambda:InvokeFunctionUrl", "clause-check-public-url"),
        ("lambda:InvokeFunction", "clause-check-public-invoke"),
    ):
        extra = {"FunctionUrlAuthType": "NONE"} if action.endswith("Url") else {}
        try:
            lam.add_permission(
                FunctionName=FUNCTION_NAME,
                StatementId=statement_id,
                Action=action,
                Principal="*",
                **extra,
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ResourceConflictException":
                raise
    return url


def ensure_log_retention() -> None:
    logs = client("logs")
    name = f"/aws/lambda/{FUNCTION_NAME}"
    try:
        logs.create_log_group(logGroupName=name)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise
    logs.put_retention_policy(logGroupName=name, retentionInDays=3)


def main() -> int:
    try:
        acct = account_id()
    except NoCredentialsError:
        print(
            "This computer has no AWS access key. Sign in at the console, create an access key "
            "under Security credentials, then run `aws configure` in Terminal. Do not paste the key into chat.",
            file=sys.stderr,
        )
        return 1
    settings = load_settings()
    if not settings.api_token:
        print("API_TOKEN is empty in .env", file=sys.stderr)
        return 1
    print(f"account {acct} region {REGION}")
    ensure_table()
    role_arn = ensure_role(acct)
    # IAM needs a short pause before Lambda can assume a new role.
    time.sleep(10)
    archive = package()
    ensure_function(role_arn, archive, settings)
    ensure_log_retention()
    url = ensure_url()
    print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
