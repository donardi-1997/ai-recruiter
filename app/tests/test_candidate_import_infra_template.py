"""Offline CloudFormation contracts for candidate-import infrastructure."""

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = REPO_ROOT / "infra" / "candidate-import.yml"


def _template() -> dict:
    return yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8"))


def _statements(policy_document: dict) -> list[dict]:
    statements = policy_document.get("Statement", [])
    return statements if isinstance(statements, list) else [statements]


def test_candidate_import_template_has_private_bucket_and_dlq():
    template = _template()
    resources = template["Resources"]
    queue = resources["ImportQueue"]["Properties"]

    assert queue["ReceiveMessageWaitTimeSeconds"] == 20
    assert queue["RedrivePolicy"]["maxReceiveCount"] == 5
    assert queue["RedrivePolicy"]["deadLetterTargetArn"] == {
        "Fn::GetAtt": ["ImportDlq", "Arn"]
    }

    bucket = resources["ImportStagingBucket"]["Properties"]
    assert bucket["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    }
    assert bucket["LifecycleConfiguration"]["Rules"][0]["ExpirationInDays"] == 1
    assert bucket["LifecycleConfiguration"]["Rules"][0]["Status"] == "Enabled"
    assert bucket["BucketEncryption"]["ServerSideEncryptionConfiguration"]


def test_candidate_import_bucket_cors_is_explicit_and_upload_only():
    template = _template()
    cors = template["Resources"]["ImportStagingBucket"]["Properties"]["CorsConfiguration"]
    rule = cors["CorsRules"][0]

    assert set(rule["AllowedMethods"]) == {"POST", "HEAD"}
    assert set(rule["AllowedOrigins"]) == {
        "https://ai.adrianguerra.net",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
    }
    assert "*" not in rule["AllowedOrigins"]


def test_candidate_import_runtime_policies_are_resource_scoped():
    template = _template()
    resources = template["Resources"]

    bucket_policy = resources["ImportStagingBucketPolicy"]["Properties"]
    queue_policy = resources["ImportQueuePolicy"]["Properties"]

    assert bucket_policy["PolicyDocument"]["Statement"]
    assert queue_policy["PolicyDocument"]["Statement"]

    for policy in (bucket_policy["PolicyDocument"], queue_policy["PolicyDocument"]):
        for statement in _statements(policy):
            assert statement["Principal"] == {"AWS": {"Ref": "RuntimeRoleArn"}}
            assert statement["Resource"] != "*"
            if isinstance(statement["Resource"], list):
                assert "*" not in statement["Resource"]

    bucket_actions = {
        action
        for statement in _statements(bucket_policy["PolicyDocument"])
        for action in statement["Action"]
    }
    assert bucket_actions == {
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket",
    }

    queue_actions = {
        action
        for statement in _statements(queue_policy["PolicyDocument"])
        for action in statement["Action"]
    }
    assert queue_actions == {
        "sqs:SendMessage",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:ChangeMessageVisibility",
        "sqs:GetQueueAttributes",
    }


def test_candidate_import_template_exposes_runtime_outputs_and_parameter():
    template = _template()

    assert template["Parameters"]["RuntimeRoleArn"]["Type"] == "String"
    assert set(template["Outputs"]) >= {
        "ImportStagingBucket",
        "ImportQueueUrl",
        "ImportQueueArn",
        "ImportDlqUrl",
    }
    assert template["Outputs"]["ImportStagingBucket"]["Value"] == {
        "Ref": "ImportStagingBucket"
    }
    assert template["Outputs"]["ImportQueueUrl"]["Value"] == {"Ref": "ImportQueue"}
    assert template["Outputs"]["ImportQueueArn"]["Value"] == {
        "Fn::GetAtt": ["ImportQueue", "Arn"]
    }
    assert template["Outputs"]["ImportDlqUrl"]["Value"] == {"Ref": "ImportDlq"}
